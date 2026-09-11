#!/usr/bin/env python3
"""Validate repository-owned demo scenarios and replay snapshots offline."""

from __future__ import annotations

import argparse
from pathlib import Path

from ai_presales_copilot.demo_replay import DEMO_SCENARIO_IDS, load_demo_replay, load_demo_scenarios
from ai_presales_copilot.llm_agent import _missing_brief_fields

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_MISSING = [
    "deployment",
    "capacity.peak_concurrency",
    "capacity.latency_target",
    "governance.residency",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenarios", default=str(ROOT / "data/demo/scenarios.json"))
    parser.add_argument("--replay-dir", default=str(ROOT / "data/demo/replays"))
    args = parser.parse_args()

    scenarios = load_demo_scenarios(args.scenarios)
    if tuple(scenarios) != DEMO_SCENARIO_IDS:
        raise ValueError("demo scenarios must be registered in normal, missing, high_risk order")
    if _missing_brief_fields(scenarios["missing"].brief) != EXPECTED_MISSING:
        raise ValueError("missing scenario does not exercise the four required clarification fields")
    for scenario_id in DEMO_SCENARIO_IDS:
        snapshot = load_demo_replay(args.replay_dir, scenario_id, scenarios=scenarios)
        if snapshot.states.final.get("response", {}).get("schema_version") != "2.0":
            raise ValueError(f"{scenario_id}: final response is not v2")
        print(f"ok {scenario_id}: {len(snapshot.events)} events")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
