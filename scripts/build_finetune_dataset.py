#!/usr/bin/env python3
"""Build deterministic, synthetic conversational data for the QLoRA POC."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ai_presales_copilot.agent import PresalesAgent
from ai_presales_copilot.compact_contract import (
    COMPACT_SYSTEM_PROMPT,
    compact_target_from_payload,
    validate_compact_solution_dict,
)
from ai_presales_copilot.evaluation import load_cases
from ai_presales_copilot.finetuning import dataset_stats, validate_conversation, write_manifest
from ai_presales_copilot.knowledge import KnowledgeBase
from ai_presales_copilot.persistence import CheckpointStore
from ai_presales_copilot.schemas import validate_solution_dict

ROOT = Path(__file__).resolve().parents[1]
SYSTEM_PROMPT = (
    "你是企业 AI 解决方案售前顾问。你必须只输出一个合法 JSON 对象：第一个字符是 {，"
    "最后一个字符是 }；禁止 Markdown、代码围栏和解释性文字。"
    "JSON 必须包含字段：case_id、executive_summary、requirements、recommendation、architecture、"
    "implementation_steps、risks、clarifying_questions、evidence、poc_plan、model_strategy、"
    "assumptions、review_status。只能根据客户输入和检索上下文回答；没有证据时写入风险或待确认问题。"
    "不要编造价格、SLA、准确率、认证或容量；资料不足时保持保守。"
)
SYSTEM_PROMPT_VERSION = "v2-json-contract-rag-context"
COMPACT_SYSTEM_PROMPT_VERSION = "v1-compact-decision-contract-rag-context"

# Keep the target complete enough to exercise the public response contract,
# while removing runtime-only fields and avoiding pretty-printed whitespace.
# This makes the supervised signal about stable behavior and format rather than
# about a particular execution trace.
PUBLIC_TARGET_FIELDS = (
    "case_id",
    "executive_summary",
    "requirements",
    "recommendation",
    "architecture",
    "implementation_steps",
    "risks",
    "clarifying_questions",
    "evidence",
    "poc_plan",
    "model_strategy",
    "assumptions",
    "review_status",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/finetuning")
    parser.add_argument("--variants", type=int, default=3, choices=(1, 2, 3))
    parser.add_argument(
        "--target-profile",
        choices=("full", "compact"),
        default="full",
        help=(
            "full regenerates the public response contract; compact trains only the "
            "small model-facing decision contract and lets the deterministic Agent "
            "own the long POC/model-strategy fields."
        ),
    )
    args = parser.parse_args()
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    cases = load_cases(ROOT / "data/evaluation/cases.jsonl")
    examples = _build_examples(cases, args.variants, args.target_profile)
    for item in examples:
        validate_conversation(item)

    # Split by source case, so variants of one customer brief never leak across splits.
    buckets = {"train": [], "dev": [], "test": []}
    for item in examples:
        source_case = item["metadata"]["case_id"]
        stable_bucket = _stable_bucket(source_case)
        bucket = "test" if stable_bucket < 2 else "dev" if stable_bucket < 4 else "train"
        buckets[bucket].append(item)

    files: dict[str, Path] = {}
    for name, rows in buckets.items():
        path = output_dir / f"{name}.jsonl"
        path.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
        )
        files[name] = path

    llama_dir = output_dir / "llamafactory"
    llama_dir.mkdir(parents=True, exist_ok=True)
    dataset_info = {
        name: {
            "file_name": str(path.relative_to(output_dir)),
            "formatting": "sharegpt",
            "columns": {"messages": "messages"},
            "tags": {
                "role_tag": "role",
                "content_tag": "content",
                "user_tag": "user",
                "assistant_tag": "assistant",
                "system_tag": "system",
            },
        }
        for name, path in files.items()
    }
    (llama_dir / "dataset_info.json").write_text(
        json.dumps(dataset_info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_manifest(
        output_dir / "manifest.json",
        files=files,
        metadata={
            "generator": "scripts/build_finetune_dataset.py",
            "system_prompt_version": (
                SYSTEM_PROMPT_VERSION
                if args.target_profile == "full"
                else COMPACT_SYSTEM_PROMPT_VERSION
            ),
            "input_context_version": "v1-structured-brief-and-retrieved-evidence",
            "target_format": "compact_json",
            "target_profile": args.target_profile,
            "variants": args.variants,
            "source_cases": len(cases),
            "split_policy": "deterministic case-level split: test/dev/train",
            "stats": {name: dataset_stats(rows) for name, rows in buckets.items()},
        },
    )
    print(json.dumps({name: dataset_stats(rows) for name, rows in buckets.items()}, ensure_ascii=False, indent=2))
    return 0


def _build_examples(cases: list[Any], variants: int, target_profile: str) -> list[dict[str, Any]]:
    examples: list[dict[str, Any]] = []
    knowledge_base = KnowledgeBase(ROOT / "data/knowledge")
    system_prompt = SYSTEM_PROMPT if target_profile == "full" else COMPACT_SYSTEM_PROMPT
    for case in cases:
        with CheckpointStore(":memory:") as store:
            state = PresalesAgent(knowledge_base, store).run(
                case, thread_id=f"dataset:{case.case_id}"
            )
            if state.response is None:
                raise RuntimeError(f"Agent did not produce a response for {case.case_id}")
            if target_profile == "full":
                target = _training_target(state.response.to_dict())
                validate_solution_dict(target, require_all_fields=True)
            elif target_profile == "compact":
                target = compact_target_from_payload(state.response.to_dict())
                validate_compact_solution_dict(target)
            else:  # pragma: no cover - argparse constrains this value
                raise ValueError(f"unsupported target profile: {target_profile}")
            answer = json.dumps(
                target,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            model_input = _format_model_input(case, state.evidence)
        prompts = [
            f"请根据以下客户输入和检索上下文输出结构化方案：\n{model_input}",
            f"请先提取约束，再为以下客户设计 POC：\n{model_input}",
            f"请审慎检查风险后回答，不要做未经证据支持的承诺：\n{model_input}",
        ][:variants]
        for index, prompt in enumerate(prompts, start=1):
            examples.append(
                {
                    "id": f"{case.case_id}-v{index}",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt},
                        {"role": "assistant", "content": answer},
                    ],
                    "metadata": {"case_id": case.case_id, "variant": index},
                }
            )
    return examples


def _stable_bucket(value: str) -> int:
    return int(hashlib.sha256(value.encode("utf-8")).hexdigest()[:8], 16) % 10


def _training_target(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a compact, stable target for the supervised behavior contract."""

    target = {field: payload[field] for field in PUBLIC_TARGET_FIELDS if field in payload}
    target["evidence"] = target.get("evidence", [])[:3]
    for item in target.get("evidence", []):
        if isinstance(item, dict) and isinstance(item.get("excerpt"), str):
            # The model should learn to cite evidence, not memorize long
            # document chunks. Runtime retrieval remains the source of truth.
            item["excerpt"] = item["excerpt"][:180]
    return target


def _format_model_input(case: Any, evidence: list[Any]) -> str:
    """Serialize the same structured brief/RAG context used by the SFT task.

    The case-level split still prevents the answer from being memorized, while
    providing retrieved evidence makes the task a realistic RAG + generation
    experiment instead of asking the adapter to hallucinate held-out facts.
    """

    brief = {
        "industry": case.industry,
        "use_case": case.use_case,
        "data_types": case.data_types,
        "deployment": case.deployment,
        "concurrency": case.concurrency,
        "latency_requirement": case.latency_requirement,
        "compliance": case.compliance,
        "budget": case.budget,
    }
    retrieved = []
    for item in evidence[:3]:
        serialized = asdict(item)
        if isinstance(serialized.get("excerpt"), str):
            serialized["excerpt"] = serialized["excerpt"][:180]
        retrieved.append(serialized)
    context = {
        "case_id": case.case_id,
        "customer_brief": brief,
        "raw_request": case.raw_request,
        "retrieved_evidence": retrieved,
        "evidence_policy": "只能引用 retrieved_evidence；没有证据时不得编造产品事实。",
    }
    return json.dumps(context, ensure_ascii=False, separators=(",", ":"))


if __name__ == "__main__":
    raise SystemExit(main())
