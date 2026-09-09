#!/usr/bin/env python3
"""Run Agent-specific quality gates over the shared cross-industry corpus."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ai_presales_copilot.agent_evaluation import evaluate_agent_cases
from ai_presales_copilot.evaluation import load_cases
from ai_presales_copilot.knowledge import KnowledgeBase

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    cases = load_cases(ROOT / "data/evaluation/cases.jsonl")
    summary, outputs = evaluate_agent_cases(cases, KnowledgeBase(ROOT / "data/knowledge"))
    report = {"mode": "presales-agent-offline", "summary": summary.to_dict(), "outputs": outputs}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary.to_dict(), ensure_ascii=False, indent=2))
    return 0 if not summary.failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
