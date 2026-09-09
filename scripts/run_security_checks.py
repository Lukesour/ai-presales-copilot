#!/usr/bin/env python3
"""Run deterministic input-policy checks over the local red-team corpus."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ai_presales_copilot.security import (
    inspect_output,
    inspect_sensitive_data,
    inspect_untrusted_input,
)

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=ROOT / "security/redteam-cases.jsonl")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    cases = [json.loads(line) for line in args.cases.read_text(encoding="utf-8").splitlines() if line]
    results = []
    failures = []
    for case in cases:
        category = case["category"]
        input_result = inspect_untrusted_input(case["input"])
        output_result = inspect_output(case["input"])
        sensitive_result = inspect_sensitive_data(case["input"])
        if category in {"prompt_injection", "indirect_injection", "excessive_agency", "unbounded_consumption"}:
            policy = "input"
            blocked = input_result.blocked
        elif category == "unsupported_commitment":
            policy = "output"
            blocked = output_result.blocked
        elif category == "data_boundary":
            policy = "sensitive_data"
            blocked = sensitive_result.blocked
        else:
            policy = "grounding_follow_up"
            blocked = False
        expected_block = category != "grounding"
        passed = blocked == expected_block
        results.append(
            {
                "id": case["id"],
                "category": category,
                "policy": policy,
                "blocked": blocked,
                "passed": passed,
            }
        )
        if not passed:
            failures.append(case["id"])
    report = {"total": len(results), "passed": len(results) - len(failures), "failures": failures, "results": results}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
