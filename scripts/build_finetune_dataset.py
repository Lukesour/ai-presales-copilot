#!/usr/bin/env python3
"""Build current v2 conversational data from validated Replay snapshots."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ai_presales_copilot.compact_contract import (
    COMPACT_SYSTEM_PROMPT,
    compact_target_from_payload,
    validate_compact_solution_dict,
)
from ai_presales_copilot.evaluation import load_replays
from ai_presales_copilot.finetuning import (
    dataset_stats,
    sha256_file,
    validate_conversation,
    write_manifest,
)

ROOT = Path(__file__).resolve().parents[1]
SYSTEM_PROMPT_VERSION = "v2-requirements-first-compact-rag-context"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/finetuning")
    parser.add_argument("--variants", type=int, default=3, choices=(1, 2, 3))
    args = parser.parse_args()
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    replays = load_replays(ROOT / "data/demo/replays", ROOT / "data/demo/scenarios.json")
    examples = _build_examples(replays, args.variants)
    for item in examples:
        validate_conversation(item)

    buckets: dict[str, list[dict[str, Any]]] = {"train": [], "dev": [], "test": []}
    scenario_order = list(dict.fromkeys(item["metadata"]["scenario_id"] for item in examples))
    for item in examples:
        position = scenario_order.index(item["metadata"]["scenario_id"])
        bucket = "test" if position == 0 else "dev" if position == 1 else "train"
        buckets[bucket].append(item)

    files: dict[str, Path] = {}
    for name, rows in buckets.items():
        path = output_dir / f"{name}.jsonl"
        path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
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
            "synthetic": True,
            "source": "data/demo/replays/",
            "source_version": "v2-requirements-first-replay",
            "source_manifest": "data/evaluation/manifest.json",
            "source_manifest_sha256": sha256_file(ROOT / "data/evaluation/manifest.json"),
            "license": "internal-synthetic",
            "sensitivity": "non-sensitive",
            "purpose": "fine-tuning-experiment",
            "created_at": "2026-09-11",
            "system_prompt_version": SYSTEM_PROMPT_VERSION,
            "input_context_version": "v2-requirements-first-replay",
            "target_format": "compact_json",
            "target_profile": "compact",
            "variants": args.variants,
            "source_cases": len(replays),
            "split_policy": "deterministic scenario-level split: test/dev/train",
            "stats": {name: dataset_stats(rows) for name, rows in buckets.items()},
        },
    )
    print(json.dumps({name: dataset_stats(rows) for name, rows in buckets.items()}, ensure_ascii=False, indent=2))
    return 0


def _build_examples(replays: list[Any], variants: int) -> list[dict[str, Any]]:
    examples: list[dict[str, Any]] = []
    for replay in replays:
        response = replay.states.final.get("response")
        target = compact_target_from_payload(response)
        validate_compact_solution_dict(target)
        answer = json.dumps(target, ensure_ascii=False, separators=(",", ":"))
        model_input = _format_model_input(replay)
        prompts = [
            f"请根据当前需求和检索证据输出结构化决策：\n{model_input}",
            f"请先检查需求门，再给出保守的方案决策：\n{model_input}",
            f"请只引用当前证据并标注风险：\n{model_input}",
        ][:variants]
        for index, prompt in enumerate(prompts, start=1):
            examples.append(
                {
                    "id": f"{replay.scenario_id}-v{index}",
                    "messages": [
                        {"role": "system", "content": COMPACT_SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                        {"role": "assistant", "content": answer},
                    ],
                    "metadata": {
                        "scenario_id": replay.scenario_id,
                        "case_id": replay.case_id,
                        "variant": index,
                        "synthetic": replay.synthetic,
                        "source_replay_schema": replay.replay_schema_version,
                        "source_replay_path": f"data/demo/replays/{replay.scenario_id}.json",
                        "license": "internal-synthetic",
                        "sensitivity": "non-sensitive",
                    },
                }
            )
    return examples


def _format_model_input(replay: Any) -> str:
    response = replay.states.final.get("response") or {}
    context = {
        "case_id": replay.case_id,
        "customer_input": replay.initial_input.model_dump(mode="json") if replay.initial_input else {},
        "retrieved_evidence": [item for item in response.get("evidence", [])[:4]],
        "requirements": response.get("requirements", []),
        "evidence_policy": "只能引用 retrieved_evidence；没有证据不得编造事实或承诺。",
    }
    return json.dumps(context, ensure_ascii=False, separators=(",", ":"))

if __name__ == "__main__":
    raise SystemExit(main())
