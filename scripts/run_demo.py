#!/usr/bin/env python3
"""Run one case through the offline engine or a configured Dify app."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ai_presales_copilot.dify_client import DifyClient, DifyClientError
from ai_presales_copilot.evaluation import load_cases
from ai_presales_copilot.knowledge import KnowledgeBase
from ai_presales_copilot.offline_engine import OfflineSolutionEngine

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-id", default="case-001")
    parser.add_argument("--mode", choices=("mock", "dify"), default="mock")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    cases = {case.case_id: case for case in load_cases(ROOT / "data/evaluation/cases.jsonl")}
    if args.case_id not in cases:
        print(f"unknown case_id: {args.case_id}", file=sys.stderr)
        return 2
    brief = cases[args.case_id]
    if args.mode == "mock":
        engine = OfflineSolutionEngine(KnowledgeBase(ROOT / "data/knowledge"))
        response = engine.analyze(brief)
    else:
        try:
            response = DifyClient().chat(brief)
        except DifyClientError as exc:
            print(str(exc), file=sys.stderr)
            return 3

    if args.as_json:
        print(json.dumps(response.to_dict(), ensure_ascii=False, indent=2))
        return 0
    print(f"案例：{brief.case_id} | {brief.industry} | {brief.use_case}")
    print(f"模式：{response.model_name} | 审核：{response.review_status}")
    print(f"\n摘要\n{response.executive_summary}")
    if response.recommendation:
        print("\n建议")
        print("\n".join(f"- {item}" for item in response.recommendation))
    if response.risks:
        print("\n风险")
        print(
            "\n".join(
                f"- [{item.severity}] {item.description}（{item.action}）"
                for item in response.risks
            )
        )
    if response.clarifying_questions:
        print("\n待确认")
        print("\n".join(f"- {item}" for item in response.clarifying_questions))
    if response.evidence:
        print("\n证据")
        print(
            "\n".join(
                f"- {item.evidence_id} {item.title}: {item.excerpt}" for item in response.evidence
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
