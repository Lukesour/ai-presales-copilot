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
from ai_presales_copilot.knowledge import KnowledgeBase


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in records) + "\n", encoding="utf-8")


def _read_evidence_ids(chunks_path: Path) -> set[str]:
    evidence_ids: set[str] = set()
    for line in chunks_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if payload.get("evidence_id"):
            evidence_ids.add(str(payload["evidence_id"]))
    return evidence_ids


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
    parser.add_argument(
        "--knowledge-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "data/knowledge",
        help="repository Markdown corpus used to validate KB evidence IDs",
    )
    parser.add_argument(
        "--chunks",
        type=Path,
        action="append",
        default=[],
        help="ingested chunks JSONL; can be repeated to add versioned evidence IDs",
    )
    parser.add_argument(
        "--evidence-id",
        action="append",
        default=[],
        help="additional allowed evidence ID; can be repeated",
    )
    args = parser.parse_args()

    records = [record for path in args.input for record in _read_jsonl(path)]
    evidence_ids = {
        item.evidence_id for item in KnowledgeBase(args.knowledge_dir).documents
    }
    for chunks_path in args.chunks:
        evidence_ids.update(_read_evidence_ids(chunks_path))
    evidence_ids.update(args.evidence_id)
    _write_jsonl(args.raw_output, records)
    accepted, rejected, decisions = filter_candidates(
        records,
        evidence_ids=evidence_ids,
        generator_model=args.generator_model,
    )
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
        "evidence_ids": len(evidence_ids),
        "decisions": [item.__dict__ for item in decisions],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
