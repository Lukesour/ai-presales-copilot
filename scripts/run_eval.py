#!/usr/bin/env python3
"""Run the offline quality gates and optionally write a JSON report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ai_presales_copilot.evaluation import evaluate_cases, load_cases
from ai_presales_copilot.knowledge import KnowledgeBase
from ai_presales_copilot.offline_engine import OfflineSolutionEngine

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    cases = load_cases(ROOT / "data/evaluation/cases.jsonl")
    engine = OfflineSolutionEngine(KnowledgeBase(ROOT / "data/knowledge"))
    summary, outputs = evaluate_cases(cases, engine.analyze)
    report = {"mode": "offline-rules", "summary": summary.to_dict(), "outputs": outputs}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary.to_dict(), ensure_ascii=False, indent=2))
    return 0 if not summary.failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
