#!/usr/bin/env python3
"""Run deterministic quality gates over the registered v2 Replay corpus."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ai_presales_copilot.evaluation import evaluate_replays, load_replays, write_evaluation_report

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay-dir", type=Path, default=ROOT / "data/demo/replays")
    parser.add_argument("--scenario-file", type=Path, default=ROOT / "data/demo/scenarios.json")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    replays = load_replays(args.replay_dir, args.scenario_file)
    summary, outputs = evaluate_replays(replays)
    if args.output:
        write_evaluation_report(args.output, summary, outputs)
    print(json.dumps(summary.to_dict(), ensure_ascii=False, indent=2))
    return 0 if not summary.failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
