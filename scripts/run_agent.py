#!/usr/bin/env python3
"""Run or resume the evidence-aware presales Agent."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ai_presales_copilot.agent import PresalesAgent
from ai_presales_copilot.evaluation import load_cases
from ai_presales_copilot.knowledge import KnowledgeBase
from ai_presales_copilot.persistence import CheckpointStore

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-id", default="case-001")
    parser.add_argument("--thread-id", default=None)
    parser.add_argument("--approve", action="store_true", help="Resume a pending high-risk run")
    parser.add_argument("--reject", action="store_true", help="Reject a pending high-risk run")
    parser.add_argument("--db", type=Path, default=ROOT / ".runtime/agent/checkpoints.db")
    parser.add_argument("--trace", type=Path, default=None)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    if args.approve and args.reject:
        parser.error("--approve and --reject are mutually exclusive")

    cases = {case.case_id: case for case in load_cases(ROOT / "data/evaluation/cases.jsonl")}
    if args.case_id not in cases:
        print(f"unknown case_id: {args.case_id}", file=sys.stderr)
        return 2
    thread_id = args.thread_id or f"demo:{args.case_id}"
    decision = "approve" if args.approve else "reject" if args.reject else None

    with CheckpointStore(args.db) as store:
        agent = PresalesAgent(KnowledgeBase(ROOT / "data/knowledge"), store)
        try:
            state = agent.run(
                None if decision else cases[args.case_id],
                thread_id=thread_id,
                review_decision=decision,
                trace_path=str(args.trace) if args.trace else None,
            )
        except (ValueError, RuntimeError) as exc:
            print(str(exc), file=sys.stderr)
            return 3

    payload = state.to_dict()
    if args.as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if state.status not in {"failed", "rejected"} else 1

    response = state.response
    print(f"案例：{state.brief.case_id} | 线程：{state.thread_id}")
    print(f"状态：{state.status} | 审核：{state.review_status} | 节点：{state.current_node}")
    if response:
        print(f"\n摘要\n{response.executive_summary}")
        print(f"\nPOC 阶段：{len(response.poc_plan)} | 证据：{len(response.evidence)}")
    if state.status == "pending_review":
        print("\n该方案包含高风险约束，请人工查看 JSON/trace 后使用 --approve 或 --reject 恢复。")
    if state.risks:
        print("\n风险")
        for risk in state.risks:
            print(f"- [{risk.severity}] {risk.category}: {risk.description}（{risk.action}）")
    if state.clarifying_questions:
        print("\n待确认")
        for question in state.clarifying_questions:
            print(f"- {question}")
    return 0 if state.status not in {"failed", "rejected"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
