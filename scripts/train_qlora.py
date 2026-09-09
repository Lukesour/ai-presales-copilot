#!/usr/bin/env python3
"""Run the optional TRL + PEFT QLoRA experiment on a compatible GPU."""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
from pathlib import Path

from ai_presales_copilot.finetuning import dataset_stats, load_conversations, sha256_file

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/finetune/trl_qlora.json")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--resume-from-checkpoint",
        type=Path,
        default=None,
        help="Resume from a Trainer checkpoint directory after a Colab runtime restart.",
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Run exactly one optimizer step to validate model, dtype, optimizer and Trainer wiring.",
    )
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    print(json.dumps(config, ensure_ascii=False, indent=2))

    data_paths = {
        split: ROOT / config["data"][f"{split}_file"] for split in ("train", "dev", "test")
    }
    data_stats = {}
    raw_examples = {}
    for split, path in data_paths.items():
        if not path.exists():
            print(f"Missing {path}; run make build-finetune-dataset first.")
            return 2
        raw_examples[split] = load_conversations(path)
        data_stats[split] = dataset_stats(raw_examples[split])
    manifest_path = data_paths["train"].parent / "manifest.json"
    print(json.dumps({"dataset_stats": data_stats}, ensure_ascii=False, indent=2))
    if args.dry_run:
        print("Dry run: dataset and training configuration parsed successfully.")
        return 0

    try:
        import torch
        from datasets import load_dataset
        from peft import LoraConfig, prepare_model_for_kbit_training
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
        from trl import SFTConfig, SFTTrainer
    except ImportError as exc:
        print(
            "Training dependencies are optional. Install the finetune extra in Colab before "
            f"running this command: {exc}"
        )
        return 3

    if not torch.cuda.is_available():
        print("A CUDA GPU is required for the configured 4-bit QLoRA run.")
        return 4

    dataset = load_dataset(
        "json",
        data_files={split: str(path) for split, path in data_paths.items()},
    )
    compute_dtype = _select_compute_dtype(torch, config.get("compute_dtype", "auto"))
    quantization = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=compute_dtype,
    )
    # This experiment targets one Colab GPU. A fixed map is deterministic and
    # avoids the multi-device training pitfalls of an inference-oriented auto map.
    model_kwargs = {
        "quantization_config": quantization,
        "device_map": {"": torch.cuda.current_device()},
        "dtype": compute_dtype,
        "low_cpu_mem_usage": True,
    }
    if config.get("model_revision"):
        model_kwargs["revision"] = config["model_revision"]
    try:
        model = AutoModelForCausalLM.from_pretrained(config["model_name_or_path"], **model_kwargs)
    except TypeError as exc:
        # Transformers versions before the ``dtype`` spelling used ``torch_dtype``.
        if "dtype" not in str(exc):
            raise
        model_kwargs["torch_dtype"] = model_kwargs.pop("dtype")
        model = AutoModelForCausalLM.from_pretrained(config["model_name_or_path"], **model_kwargs)
    model.config.use_cache = False
    tokenizer_kwargs = {}
    if config.get("model_revision"):
        tokenizer_kwargs["revision"] = config["model_revision"]
    tokenizer = AutoTokenizer.from_pretrained(config["model_name_or_path"], **tokenizer_kwargs)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    training = config["training"]
    token_audit = _audit_token_lengths(
        raw_examples,
        tokenizer,
        max_length=int(training["max_length"]),
    )
    print(json.dumps({"token_length_audit": token_audit}, ensure_ascii=False, indent=2))
    over_limit = {
        split: stats["full_sequence"]["over_max_length"]
        for split, stats in token_audit.items()
        if stats["full_sequence"]["over_max_length"]
    }
    if over_limit:
        message = (
            "Some conversations exceed training.max_length and would be truncated. "
            f"max_length={training['max_length']}, over_limit={over_limit}. "
            "Increase max_length or compact the supervised target before claiming a quality result."
        )
        if training.get("fail_on_truncation", False):
            raise ValueError(message)
        print(f"WARNING: {message}")
    if training.get("gradient_checkpointing", False):
        model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    dataset, loss_kwargs, loss_mode = _prepare_dataset_for_sft(dataset, tokenizer, training)
    print(json.dumps({"loss_mode": loss_mode}, ensure_ascii=False))

    lora = LoraConfig(
        r=config["lora"]["r"],
        lora_alpha=config["lora"]["alpha"],
        lora_dropout=config["lora"]["dropout"],
        target_modules=config["lora"]["target_modules"],
        task_type="CAUSAL_LM",
    )
    eval_strategy = training.get("eval_strategy", "epoch")
    save_strategy = training.get("save_strategy", "epoch")
    trainer_precision = _resolve_trainer_precision(
        training.get("trainer_precision", "auto"), compute_dtype, torch
    )
    # Accelerate may inherit this setting from an existing Colab config.
    # Make the effective precision explicit for this subprocess.
    os.environ["ACCELERATE_MIXED_PRECISION"] = (
        "no" if trainer_precision == "fp32" else trainer_precision
    )
    output_dir = _resolve_output_dir(config["output_dir"])
    trainer_output_dir = output_dir / "smoke-test" if args.smoke_test else output_dir
    training_kwargs = dict(
        output_dir=str(trainer_output_dir),
        num_train_epochs=training["epochs"],
        learning_rate=training["learning_rate"],
        per_device_train_batch_size=training["per_device_train_batch_size"],
        per_device_eval_batch_size=training["per_device_eval_batch_size"],
        gradient_accumulation_steps=training["gradient_accumulation_steps"],
        gradient_checkpointing=training["gradient_checkpointing"],
        gradient_checkpointing_kwargs={"use_reentrant": False},
        optim=training.get("optim", "paged_adamw_8bit"),
        warmup_ratio=training.get("warmup_ratio", 0.0),
        logging_steps=training["logging_steps"],
        eval_strategy=eval_strategy,
        save_strategy=save_strategy,
        save_total_limit=2,
        load_best_model_at_end=training.get("load_best_model_at_end", False),
        metric_for_best_model=training.get("metric_for_best_model", "eval_loss"),
        greater_is_better=training.get("greater_is_better", False),
        max_length=training["max_length"],
        packing=False,
        report_to=[],
        seed=training["seed"],
        bf16=trainer_precision == "bf16",
        fp16=trainer_precision == "fp16",
        **loss_kwargs,
    )
    if args.smoke_test:
        training_kwargs.update(
            {
                "max_steps": 1,
                "num_train_epochs": 1,
                "eval_strategy": "no",
                "save_strategy": "no",
                "load_best_model_at_end": False,
                "logging_steps": 1,
            }
        )
    if eval_strategy == "steps":
        training_kwargs["eval_steps"] = training.get("eval_steps", 25)
    if save_strategy == "steps":
        training_kwargs["save_steps"] = training.get("save_steps", 25)
    training_args = SFTConfig(**training_kwargs)
    trainer = SFTTrainer(
        model=model,
        processing_class=tokenizer,
        train_dataset=dataset["train"],
        eval_dataset=dataset["dev"],
        peft_config=lora,
        args=training_args,
    )
    if trainer_precision == "fp32":
        _cast_trainable_parameters(trainer.model, torch.float32)
    print(
        json.dumps(
            {
                "trainer_precision": trainer_precision,
                "trainable_parameter_dtypes": _trainable_parameter_dtypes(trainer.model),
            },
            ensure_ascii=False,
        )
    )
    resume_path = None
    if args.resume_from_checkpoint:
        resume_path = str(args.resume_from_checkpoint.resolve())
        if not args.resume_from_checkpoint.exists():
            print(f"Checkpoint does not exist: {args.resume_from_checkpoint}")
            return 5
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()
    train_started = time.perf_counter()
    train_output = trainer.train(resume_from_checkpoint=resume_path)
    train_seconds = round(time.perf_counter() - train_started, 3)
    trainer.save_model(str(trainer_output_dir))
    tokenizer.save_pretrained(str(trainer_output_dir))
    if args.smoke_test:
        test_metrics = {}
    else:
        # The held-out split is still in the raw prompt/completion format here.
        # Run it through TRL's SFT preprocessing in a separate, evaluation-only
        # trainer before calling the Transformers evaluation loop.
        test_metrics = _evaluate_held_out_test(
            model=trainer.model,
            tokenizer=tokenizer,
            test_dataset=dataset["test"],
            training_kwargs=training_kwargs,
            output_dir=trainer_output_dir,
            SFTConfig=SFTConfig,
            SFTTrainer=SFTTrainer,
        )
    (trainer_output_dir / "metrics.json").write_text(
        json.dumps(
            {
                "model_name_or_path": config["model_name_or_path"],
                "model_revision": config.get("model_revision"),
                "dataset_manifest": {
                    "path": str(manifest_path),
                    "sha256": sha256_file(manifest_path) if manifest_path.exists() else None,
                },
                "training_config": config["training"],
                "token_length_audit": token_audit,
                "train_metrics": train_output.metrics,
                "test_metrics": test_metrics,
                "runtime": {
                    **_runtime_metadata(torch),
                    "compute_dtype": str(compute_dtype).replace("torch.", ""),
                    "trainer_precision": trainer_precision,
                    "train_seconds": train_seconds,
                    "peak_gpu_memory_allocated_gb": _peak_gpu_memory(torch, "allocated"),
                    "peak_gpu_memory_reserved_gb": _peak_gpu_memory(torch, "reserved"),
                    "smoke_test": args.smoke_test,
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Adapter saved to {trainer_output_dir}")
    print(json.dumps({"test_metrics": test_metrics}, ensure_ascii=False, indent=2))
    return 0


def _resolve_output_dir(value: str | Path) -> Path:
    output_dir = Path(value)
    return output_dir if output_dir.is_absolute() else ROOT / output_dir


def _audit_token_lengths(
    examples_by_split: dict[str, list[dict[str, object]]], tokenizer, max_length: int
) -> dict[str, dict[str, object]]:
    """Measure the exact chat-template lengths before TRL starts training.

    A character count is not a safe proxy for a model context window. This
    audit makes prompt/completion truncation visible in the training log and in
    ``metrics.json``. The full sequence is the important gate because the
    target is a structured JSON object whose closing tokens must be retained.
    """

    report: dict[str, dict[str, object]] = {}
    for split, examples in examples_by_split.items():
        full_lengths: list[int] = []
        prompt_lengths: list[int] = []
        completion_lengths: list[int] = []
        for row in examples:
            messages = row["messages"]
            if not isinstance(messages, list) or not messages:
                continue
            full_ids = tokenizer.apply_chat_template(
                messages,
                tokenize=True,
                add_generation_prompt=False,
            )
            prompt_ids = tokenizer.apply_chat_template(
                messages[:-1],
                tokenize=True,
                add_generation_prompt=True,
            )
            completion = messages[-1]["content"]
            completion_ids = tokenizer(
                completion,
                add_special_tokens=False,
            )["input_ids"]
            full_lengths.append(len(full_ids))
            prompt_lengths.append(len(prompt_ids))
            completion_lengths.append(len(completion_ids))
        report[split] = {
            "full_sequence": _length_summary(full_lengths, max_length),
            "prompt": _length_summary(prompt_lengths, max_length),
            "completion": _length_summary(completion_lengths, max_length),
        }
    return report


def _length_summary(lengths: list[int], max_length: int) -> dict[str, object]:
    if not lengths:
        return {
            "examples": 0,
            "min": 0,
            "p50": 0,
            "p90": 0,
            "max": 0,
            "over_max_length": 0,
            "over_max_length_rate": 0.0,
        }
    ordered = sorted(lengths)

    def percentile(fraction: float) -> int:
        index = min(len(ordered) - 1, round((len(ordered) - 1) * fraction))
        return ordered[index]

    over = sum(value > max_length for value in ordered)
    return {
        "examples": len(ordered),
        "min": ordered[0],
        "p50": percentile(0.50),
        "p90": percentile(0.90),
        "max": ordered[-1],
        "over_max_length": over,
        "over_max_length_rate": round(over / len(ordered), 4),
    }


def _runtime_metadata(torch) -> dict[str, object]:
    metadata: dict[str, object] = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "torch": torch.__version__,
        "cuda_runtime": torch.version.cuda,
        "cuda_available": bool(torch.cuda.is_available()),
    }
    if torch.cuda.is_available():
        metadata.update(
            {
                "gpu_name": torch.cuda.get_device_name(0),
                "gpu_count": torch.cuda.device_count(),
                "bf16_supported": bool(torch.cuda.is_bf16_supported()),
                "compute_capability": ".".join(
                    str(part) for part in torch.cuda.get_device_capability(0)
                ),
            }
        )
    return metadata


def _select_compute_dtype(torch, configured: str):
    if configured == "float16":
        return torch.float16
    if configured == "bfloat16":
        if not torch.cuda.is_bf16_supported():
            raise ValueError(
                "compute_dtype=bfloat16 was requested but this GPU does not support it"
            )
        return torch.bfloat16
    if configured != "auto":
        raise ValueError("compute_dtype must be one of: auto, float16, bfloat16")
    capability = torch.cuda.get_device_capability(0)
    if capability[0] >= 8 and torch.cuda.is_bf16_supported():
        return torch.bfloat16
    return torch.float16


def _resolve_trainer_precision(configured: str, compute_dtype, torch) -> str:
    if configured == "auto":
        capability = torch.cuda.get_device_capability(0)
        # Avoid AMP/GradScaler by default on pre-Ampere cards such as T4.
        if capability[0] < 8:
            return "fp32"
        return "bf16" if compute_dtype == torch.bfloat16 else "fp16"
    if configured not in {"fp32", "fp16", "bf16"}:
        raise ValueError("trainer_precision must be one of: auto, fp32, fp16, bf16")
    if configured == "fp16" and torch.cuda.get_device_capability(0)[0] < 8:
        raise ValueError(
            "trainer_precision=fp16 is disabled on pre-Ampere GPUs; "
            "use trainer_precision=fp32 to avoid GradScaler dtype conflicts"
        )
    if configured == "bf16" and not torch.cuda.is_bf16_supported():
        raise ValueError("trainer_precision=bf16 was requested but this GPU does not support it")
    return configured


def _peak_gpu_memory(torch, kind: str) -> float | None:
    if not torch.cuda.is_available():
        return None
    value = (
        torch.cuda.max_memory_allocated()
        if kind == "allocated"
        else torch.cuda.max_memory_reserved()
    )
    return round(value / 1024**3, 3)


def _cast_trainable_parameters(model, dtype) -> None:
    """Keep adapter gradients in a GradScaler-free dtype on older NVIDIA GPUs."""

    for parameter in model.parameters():
        if parameter.requires_grad and parameter.dtype != dtype:
            parameter.data = parameter.data.to(dtype=dtype)


def _trainable_parameter_dtypes(model) -> dict[str, int]:
    counts: dict[str, int] = {}
    for parameter in model.parameters():
        if parameter.requires_grad:
            name = str(parameter.dtype).replace("torch.", "")
            counts[name] = counts.get(name, 0) + parameter.numel()
    return counts


def _build_test_evaluation_kwargs(
    training_kwargs: dict[str, object], output_dir: Path
) -> dict[str, object]:
    """Build an evaluation-only SFTConfig from the exact training settings.

    Keeping the tokenizer/template/max-length/loss settings aligned is more
    important than reusing the original Trainer object: the original trainer
    has already tokenized train/dev, while the held-out split is intentionally
    kept separate until this final evaluation stage.
    """

    evaluation_kwargs = dict(training_kwargs)
    # ``max_steps`` is only injected for the one-step smoke test. It should not
    # accidentally constrain a real held-out evaluation if this helper is reused.
    evaluation_kwargs.pop("max_steps", None)
    evaluation_kwargs.update(
        {
            "output_dir": str(output_dir / "test-eval"),
            "do_train": False,
            "do_eval": True,
            "eval_strategy": "no",
            "save_strategy": "no",
            "load_best_model_at_end": False,
            "gradient_checkpointing": False,
            "report_to": [],
        }
    )
    return evaluation_kwargs


def _evaluate_held_out_test(
    *,
    model,
    tokenizer,
    test_dataset,
    training_kwargs: dict[str, object],
    output_dir: Path,
    SFTConfig,
    SFTTrainer,
) -> dict[str, object]:
    """Evaluate a raw held-out split using TRL's canonical SFT preprocessing.

    Passing a raw prompt/completion dataset directly to the base
    ``Trainer.evaluate`` bypasses SFT tokenization in some TRL/Transformers
    combinations. Constructing a second SFTTrainer makes preprocessing explicit
    and version-robust; ``evaluate()`` then consumes the prepared dataset stored
    on that evaluator. Some supported TRL versions require a train dataset at
    construction time, so the held-out dataset is supplied in both slots while
    training is explicitly disabled and never invoked.
    """

    evaluation_args = SFTConfig(**_build_test_evaluation_kwargs(training_kwargs, output_dir))
    evaluator = SFTTrainer(
        model=model,
        processing_class=tokenizer,
        # Older supported TRL releases require train_dataset during
        # construction. This evaluator is configured with do_train=False and
        # never calls train(), so the test split is not used for optimization.
        train_dataset=test_dataset,
        eval_dataset=test_dataset,
        # The model is already wrapped by the training SFTTrainer. Passing no
        # peft_config preserves the trained adapter instead of wrapping twice.
        args=evaluation_args,
    )
    prepared_dataset = evaluator.eval_dataset
    prepared_columns = list(getattr(prepared_dataset, "column_names", []))
    if "input_ids" not in prepared_columns:
        raise RuntimeError(
            "Held-out test preprocessing did not produce input_ids; "
            f"prepared columns: {prepared_columns}"
        )
    print(
        json.dumps(
            {
                "test_eval_dataset_columns": prepared_columns,
                "test_eval_examples": len(prepared_dataset),
            },
            ensure_ascii=False,
        )
    )
    # Do not pass the raw test dataset here. The evaluator's constructor has
    # already applied the same SFT preprocessing used for train/dev.
    return evaluator.evaluate(metric_key_prefix="test")


def _prepare_dataset_for_sft(dataset, tokenizer, training: dict[str, object]):
    """Use assistant-only masks when the chat template supports them.

    Older Qwen2 chat templates may not expose TRL's ``{% generation %}``
    markers.  In that case, convert the same conversations to conversational
    prompt/completion records so ``completion_only_loss`` still excludes the
    user and system messages.
    """

    wants_assistant_only = bool(training.get("assistant_only_loss", True))
    template = tokenizer.chat_template or ""
    if wants_assistant_only and "{% generation %}" in template:
        return dataset, {"assistant_only_loss": True}, "assistant_only"

    def to_prompt_completion(row: dict[str, object]) -> dict[str, object]:
        messages = row["messages"]
        return {"prompt": messages[:-1], "completion": messages[-1:]}

    columns = dataset["train"].column_names
    converted = dataset.map(to_prompt_completion, remove_columns=columns)
    return converted, {"completion_only_loss": True}, "prompt_completion"


if __name__ == "__main__":
    raise SystemExit(main())
