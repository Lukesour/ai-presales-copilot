#!/usr/bin/env python3
"""Filter Self-Instruct/Self-QA candidates without auto-promoting gold data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ai_presales_copilot.dataset_pipeline import (
    build_manifest,
    filter_candidates,
    promote_expert_verified,
)


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in records) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, action="append", required=True)
    parser.add_argument("--raw-output", type=Path, default=Path("data/datasets/raw_synthetic.jsonl"))
    parser.add_argument("--filtered-output", type=Path, default=Path("data/datasets/filtered_synthetic.jsonl"))
    parser.add_argument("--rejected-output", type=Path, default=Path("data/datasets/rejected_synthetic.jsonl"))
    parser.add_argument("--gold-output", type=Path, default=Path("data/datasets/expert_verified_gold.jsonl"))
    parser.add_argument("--approved-id", action="append", default=[])
    parser.add_argument("--manifest-output", type=Path, default=Path("data/datasets/manifest.json"))
    parser.add_argument("--generator-model", default="existing-candidate-corpus")
    args = parser.parse_args()

    records = [record for path in args.input for record in _read_jsonl(path)]
    _write_jsonl(args.raw_output, records)
    accepted, rejected, decisions = filter_candidates(records, generator_model=args.generator_model)
    _write_jsonl(args.filtered_output, accepted)
    _write_jsonl(args.rejected_output, rejected)
    gold = promote_expert_verified(accepted, set(args.approved_id))
    _write_jsonl(args.gold_output, gold)
    manifest = build_manifest(
        layer="filtered_synthetic",
        source_files=[str(path) for path in args.input],
        records=records,
        accepted_count=len(accepted),
        gold_count=len(gold),
        generator_model=args.generator_model,
    )
    args.manifest_output.parent.mkdir(parents=True, exist_ok=True)
    args.manifest_output.write_text(json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "raw": len(records),
        "filtered": len(accepted),
        "rejected": len(rejected),
        "gold": len(gold),
        "decisions": [item.__dict__ for item in decisions],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
