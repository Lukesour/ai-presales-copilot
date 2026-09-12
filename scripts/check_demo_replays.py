#!/usr/bin/env python3
"""Validate repository-owned demo scenarios and replay snapshots offline."""

from __future__ import annotations

import argparse
from pathlib import Path

from ai_presales_copilot.demo_replay import DEMO_SCENARIO_IDS, load_demo_replay, load_demo_scenarios

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_INITIAL_BLOCKING = [
    "business_goal",
    "target_users",
    "deployment",
    "governance.residency",
    "acceptance_criteria",
]
REQUIREMENTS_FIRST_IDS = {"normal", "missing_then_clarified", "high_risk", "conflict_or_injection"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenarios", default=str(ROOT / "data/demo/scenarios.json"))
    parser.add_argument("--replay-dir", default=str(ROOT / "data/demo/replays"))
    args = parser.parse_args()

    scenarios = load_demo_scenarios(args.scenarios)
    if tuple(scenarios) != DEMO_SCENARIO_IDS:
        raise ValueError("demo scenarios must contain the registered requirements-first branches")
    for scenario_id in DEMO_SCENARIO_IDS:
        snapshot = load_demo_replay(args.replay_dir, scenario_id, scenarios=scenarios)
        if snapshot.states.final.get("response", {}).get("schema_version") != "2.0":
            raise ValueError(f"{scenario_id}: final response is not v2")
        if scenario_id in REQUIREMENTS_FIRST_IDS:
            if snapshot.initial_input is None or not snapshot.input_turns:
                raise ValueError(f"{scenario_id}: initial synthetic input and turns are required")
            initial = snapshot.states.initial
            if initial is None or initial.get("response") is not None:
                raise ValueError(f"{scenario_id}: initial state must stop before solution generation")
            if scenario_id == "missing_then_clarified" and initial.get("requirement_analysis", {}).get(
                "blocking_fields"
            ) != EXPECTED_INITIAL_BLOCKING:
                raise ValueError("missing_then_clarified does not exercise the blocking requirement fields")
            events = snapshot.events
            solution_nodes = {"query_rewrite", "retrieve", "draft", "ground_claims", "critic", "repair", "risk_gate", "finalize"}
            first_solution = next((event.seq for event in events if event.node in solution_nodes), None)
            if scenario_id == "conflict_or_injection":
                if snapshot.states.final.get("status") != "rejected":
                    raise ValueError("conflict_or_injection must finish rejected")
                if first_solution is not None:
                    raise ValueError("blocked input must not reach solution nodes")
            elif first_solution is None:
                raise ValueError(f"{scenario_id}: solution branch is missing")
            else:
                confirmation = next((event.seq for event in events if event.event_type == "requirements_confirmed"), None)
                if confirmation is None or confirmation > first_solution:
                    raise ValueError(f"{scenario_id}: solution nodes precede requirements confirmation")
        print(f"ok {scenario_id}: {len(snapshot.events)} events")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
