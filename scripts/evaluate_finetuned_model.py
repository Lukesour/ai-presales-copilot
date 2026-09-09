#!/usr/bin/env python3
"""Compare a base model or LoRA adapter on the held-out presales test split."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

from ai_presales_copilot.compact_contract import validate_compact_solution_dict
from ai_presales_copilot.finetuning import load_conversations, sha256_file
from ai_presales_copilot.schemas import validate_solution_dict
from ai_presales_copilot.security import inspect_output, inspect_sensitive_data

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = "Qwen/Qwen2.5-0.5B-Instruct"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        default=None,
        help="Base model id/path. If omitted with --adapter, use the adapter config's base model.",
    )
    parser.add_argument("--adapter", type=Path, default=None)
    parser.add_argument("--split", type=Path, default=ROOT / "data/finetuning/test.jsonl")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--contract-profile",
        choices=("full", "compact"),
        default="full",
        help="Schema used for scoring the model-facing output contract.",
    )
    parser.add_argument(
        "--max-new-tokens",
        type=int,
        default=4096,
        help="Generation budget; 4096 avoids truncating the structured presales target.",
    )
    parser.add_argument(
        "--json-prefill",
        action="store_true",
        help="Prefill the assistant response with '{' using the chat template before generation.",
    )
    parser.add_argument(
        "--include-output-previews",
        action="store_true",
        help="Include truncated generated text in the report for debugging; disabled by default for privacy.",
    )
    parser.add_argument(
        "--preview-chars",
        type=int,
        default=800,
        help="Maximum characters per diagnostic output preview (default: 800).",
    )
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    if args.max_new_tokens < 1:
        raise ValueError("--max-new-tokens must be at least 1")
    if args.preview_chars < 1:
        raise ValueError("--preview-chars must be at least 1")
    rows = load_conversations(args.split)
    if args.limit > 0:
        rows = rows[: args.limit]

    adapter_config = None
    if args.adapter:
        adapter_config = _validate_adapter_artifact(args.adapter)
    model_name = args.model or (
        adapter_config.get("base_model_name_or_path") if adapter_config else DEFAULT_MODEL
    )
    if not model_name:
        raise ValueError(
            "Could not determine the base model. Pass --model or provide "
            "base_model_name_or_path in adapter_config.json."
        )
    if adapter_config and args.model:
        configured_base = adapter_config.get("base_model_name_or_path")
        if configured_base and configured_base != args.model:
            raise ValueError(
                "The requested base model does not match the adapter metadata: "
                f"--model={args.model!r}, adapter={configured_base!r}. "
                "Use the original base model or intentionally regenerate the adapter."
            )

    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except ImportError as exc:
        print(f"Evaluation dependencies are optional; install the finetune extra: {exc}")
        return 3

    print(f"Loading base model: {model_name}")
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    model, model_dtype, model_device = _load_inference_model(
        AutoModelForCausalLM, model_name, torch
    )
    if args.adapter:
        try:
            from peft import PeftConfig, PeftModel
        except ImportError as exc:
            print(f"PEFT is required to evaluate an adapter: {exc}")
            return 3
        # Parse the config with PEFT as a second validation layer before
        # attaching weights. This catches malformed or partial artifacts with
        # a useful message instead of a later generate() failure.
        peft_config = PeftConfig.from_pretrained(str(args.adapter))
        print(
            "Loading adapter: "
            f"{args.adapter} (peft_type={peft_config.peft_type}, "
            f"base={peft_config.base_model_name_or_path})"
        )
        try:
            model = PeftModel.from_pretrained(
                model,
                str(args.adapter),
                is_trainable=False,
            )
        except ImportError as exc:
            if "incompatible version of torchao" in str(exc):
                raise RuntimeError(
                    "PEFT found an incompatible optional torchao installation. "
                    "This project uses bitsandbytes NF4 and does not use torchao. "
                    "Restart/delete the Colab runtime, rerun the notebook setup cell "
                    "(it removes preinstalled torchao), and then rerun evaluation. "
                    "If TorchAO is intentionally required, install a version compatible "
                    "with the installed PyTorch instead of using the legacy package."
                ) from exc
            raise
        # The base model is deliberately loaded on one device for this small
        # evaluation model. Moving once after PEFT attachment keeps base and
        # adapter weights colocated and avoids device_map/adapter dispatch
        # surprises during generation.
        model = model.to(model_device)
        if hasattr(model, "set_adapter"):
            model.set_adapter("default")
    model.eval()
    device = _input_device(model)
    print(
        json.dumps(
            {
                "model": model_name,
                "adapter": str(args.adapter) if args.adapter else None,
                "device": str(device),
                "dtype": str(model_dtype).replace("torch.", ""),
                "examples": len(rows),
                "pad_token_id": tokenizer.pad_token_id,
                "eos_token_id": tokenizer.eos_token_id,
            },
            ensure_ascii=False,
        )
    )

    results: list[dict[str, Any]] = []
    generation_config = copy.deepcopy(model.generation_config)
    # The comparison is deliberately greedy and identical for base/adapter.
    # Normalize sampling-only fields inherited from Qwen's generation_config so
    # Transformers does not silently ignore them when do_sample=False.
    generation_config.do_sample = False
    generation_config.temperature = 1.0
    generation_config.top_p = 1.0
    generation_config.top_k = 50
    generation_config.num_beams = 1
    generation_config.max_new_tokens = args.max_new_tokens
    generation_config.pad_token_id = tokenizer.pad_token_id
    generation_config.eos_token_id = tokenizer.eos_token_id
    for row in rows:
        prompt_messages = [message for message in row["messages"] if message["role"] != "assistant"]
        if args.json_prefill:
            # ``continue_final_message`` keeps the assistant turn open after
            # the prefilled ``{``. This is input control, not post-hoc JSON
            # repair, and is reproducible for base and adapter alike.
            generation_messages = prompt_messages + [{"role": "assistant", "content": "{"}]
            encoded = tokenizer.apply_chat_template(
                generation_messages,
                tokenize=True,
                continue_final_message=True,
                return_tensors="pt",
                return_dict=True,
            )
        else:
            encoded = tokenizer.apply_chat_template(
                prompt_messages,
                tokenize=True,
                add_generation_prompt=True,
                return_tensors="pt",
                return_dict=True,
            )
        encoded = {key: value.to(device) for key, value in encoded.items()}
        prompt_length = encoded["input_ids"].shape[-1]
        try:
            with torch.inference_mode():
                generated = model.generate(
                    **encoded,
                    generation_config=generation_config,
                )
        except Exception as exc:
            raise RuntimeError(
                f"Generation failed for example {row['id']!r}; "
                f"device={device}, prompt_tokens={prompt_length}, "
                f"adapter={args.adapter!s}"
            ) from exc
        completion = tokenizer.decode(
            generated[0][prompt_length:], skip_special_tokens=True
        ).strip()
        if args.json_prefill:
            completion = "{" + completion
        results.append(
            _score_completion(
                row["id"],
                completion,
                contract_profile=args.contract_profile,
                include_output_preview=args.include_output_previews,
                preview_chars=args.preview_chars,
                generation_truncated=(generated.shape[-1] - prompt_length)
                >= args.max_new_tokens,
            )
        )

    report = {
        "model": model_name,
        "adapter": str(args.adapter) if args.adapter else None,
        "split": str(args.split),
        "split_sha256": sha256_file(args.split),
        "examples": len(results),
        "metrics": _summarize(results),
        "results": results,
        "runtime": {
            "torch": torch.__version__,
            "cuda_runtime": torch.version.cuda,
            "cuda_available": bool(torch.cuda.is_available()),
            "device": str(device),
            "dtype": str(model_dtype).replace("torch.", ""),
            "include_output_previews": args.include_output_previews,
            "max_new_tokens": args.max_new_tokens,
            "json_prefill": args.json_prefill,
            "contract_profile": args.contract_profile,
        },
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(json.dumps(report["metrics"], ensure_ascii=False, indent=2))
    return 0


def _validate_adapter_artifact(adapter_dir: Path) -> dict[str, Any]:
    """Validate the files required by PEFT before loading a base model."""

    if not adapter_dir.exists():
        raise FileNotFoundError(f"Adapter directory does not exist: {adapter_dir}")
    if not adapter_dir.is_dir():
        raise NotADirectoryError(f"Adapter path is not a directory: {adapter_dir}")

    config_path = adapter_dir / "adapter_config.json"
    if not config_path.is_file():
        raise FileNotFoundError(
            f"Missing {config_path}. The training output is not a complete PEFT adapter."
        )
    weight_files = [adapter_dir / "adapter_model.safetensors", adapter_dir / "adapter_model.bin"]
    existing_weights = [path for path in weight_files if path.is_file()]
    if not existing_weights:
        raise FileNotFoundError(
            f"Missing adapter weights in {adapter_dir}; expected adapter_model.safetensors "
            "or adapter_model.bin."
        )
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {config_path}: {exc}") from exc
    if not isinstance(config, dict):
        raise TypeError(f"Adapter config must be a JSON object: {config_path}")
    config["_weight_files"] = [str(path.name) for path in existing_weights]
    return config


def _load_inference_model(model_class, model_name: str, torch):
    """Load the small comparison model on one deterministic device.

    ``device_map='auto'`` is useful for big-model inference, but this project
    compares a 0.5B model on one Colab GPU. Explicit placement keeps the PEFT
    adapter and base layers on the same device and makes input placement
    unambiguous.
    """

    if torch.cuda.is_available():
        device = torch.device(f"cuda:{torch.cuda.current_device()}")
        dtype = torch.float16
    else:
        device = torch.device("cpu")
        dtype = torch.float32
    kwargs = {"dtype": dtype, "low_cpu_mem_usage": True}
    try:
        model = model_class.from_pretrained(model_name, **kwargs)
    except TypeError as exc:
        # Transformers versions before the ``dtype`` spelling use
        # ``torch_dtype``. Keep the fallback local to inference loading.
        if "dtype" not in str(exc):
            raise
        kwargs["torch_dtype"] = kwargs.pop("dtype")
        model = model_class.from_pretrained(model_name, **kwargs)
    model = model.to(device)
    return model, dtype, device


def _input_device(model):
    """Return the device used by the input embedding layer."""

    embedding = model.get_input_embeddings()
    for parameter in embedding.parameters():
        if parameter.device.type != "meta":
            return parameter.device
    raise RuntimeError(
        "Input embedding parameters are on the meta device; model loading was incomplete."
    )


def _score_completion(
    example_id: str,
    text: str,
    *,
    contract_profile: str = "full",
    include_output_preview: bool = False,
    preview_chars: int = 800,
    generation_truncated: bool = False,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": example_id,
        "json_parse": False,
        "schema_pass": False,
        "output_chars": len(text),
        "generation_truncated": generation_truncated,
    }
    if include_output_preview:
        item["output_preview"] = text[:preview_chars]
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        item["error"] = "invalid_json"
        return item
    item["json_parse"] = True
    try:
        if contract_profile == "compact":
            validate_compact_solution_dict(payload)
        else:
            validate_solution_dict(payload, require_all_fields=True)
        item["schema_pass"] = True
    except (TypeError, ValueError) as exc:
        item["error"] = str(exc)
    output_policy = inspect_output(text)
    sensitive_policy = inspect_sensitive_data(text)
    item["policy_pass"] = not output_policy.blocked and not sensitive_policy.blocked
    evidence_field = "evidence_ids" if contract_profile == "compact" else "evidence"
    item["evidence_count"] = len(payload.get(evidence_field, [])) if isinstance(payload, dict) else 0
    summary = payload.get("executive_summary", "") if isinstance(payload, dict) else ""
    item["conservative_no_evidence"] = (
        not item["evidence_count"] and isinstance(summary, str) and "资料不足" in summary
    )
    return item


def _summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)

    def count(field: str) -> int:
        return sum(bool(item.get(field)) for item in results)

    output_lengths = sorted(int(item.get("output_chars", 0)) for item in results)

    def percentile(fraction: float) -> int:
        if not output_lengths:
            return 0
        index = min(len(output_lengths) - 1, round((len(output_lengths) - 1) * fraction))
        return output_lengths[index]

    return {
        "total": total,
        "json_parse": count("json_parse"),
        "json_parse_rate": round(count("json_parse") / total, 4) if total else 0.0,
        "schema_pass": count("schema_pass"),
        "schema_pass_rate": round(count("schema_pass") / total, 4) if total else 0.0,
        "policy_pass": count("policy_pass"),
        "policy_pass_rate": round(count("policy_pass") / total, 4) if total else 0.0,
        "conservative_no_evidence": count("conservative_no_evidence"),
        "generation_truncated": count("generation_truncated"),
        "generation_truncated_rate": round(count("generation_truncated") / total, 4)
        if total
        else 0.0,
        "output_chars_p50": percentile(0.50),
        "output_chars_p90": percentile(0.90),
        "output_chars_max": output_lengths[-1] if output_lengths else 0,
    }


if __name__ == "__main__":
    raise SystemExit(main())
