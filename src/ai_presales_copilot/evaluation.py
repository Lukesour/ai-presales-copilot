"""Offline quality gates for the current requirements-first replay corpus."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .demo_replay import ReplaySnapshot, load_demo_replay, load_demo_scenarios
from .schemas import SolutionResponseV2


@dataclass(frozen=True)
class EvaluationSummary:
    total: int
    schema_pass: int
    evidence_present: int
    requirement_gate_pass: int
    no_evidence_guard: int
    high_risk_review: int
    failures: list[dict[str, str]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "schema_pass": self.schema_pass,
            "schema_pass_rate": round(self.schema_pass / self.total, 4) if self.total else 0.0,
            "evidence_present": self.evidence_present,
            "requirement_gate_pass": self.requirement_gate_pass,
            "no_evidence_guard": self.no_evidence_guard,
            "high_risk_review": self.high_risk_review,
            "failures": self.failures,
        }


def load_replays(replay_dir: str | Path, scenario_path: str | Path) -> list[ReplaySnapshot]:
    """Load only registered, validated v2 replay snapshots."""

    scenarios = load_demo_scenarios(scenario_path)
    return [
        load_demo_replay(replay_dir, scenario_id, scenarios=scenarios)
        for scenario_id in scenarios
    ]


def evaluate_replays(replays: list[ReplaySnapshot]) -> tuple[EvaluationSummary, list[dict[str, Any]]]:
    schema_pass = 0
    evidence_present = 0
    requirement_gate_pass = 0
    no_evidence_guard = 0
    high_risk_review = 0
    failures: list[dict[str, str]] = []
    outputs: list[dict[str, Any]] = []

    for replay in replays:
        final = replay.states.final
        response = final.get("response")
        try:
            parsed = SolutionResponseV2.model_validate(response)
            schema_pass += 1
        except (TypeError, ValueError) as exc:
            failures.append({"case_id": replay.case_id, "metric": "schema", "detail": str(exc)})
            parsed = None
        if parsed is not None:
            if parsed.evidence:
                evidence_present += 1
            if not parsed.evidence and parsed.clarifying_questions:
                no_evidence_guard += 1
            if replay.scenario_id == "high_risk" and parsed.review.status in {"approved", "pending"}:
                high_risk_review += 1
        initial = replay.states.initial
        if initial is not None and initial.get("response") is None:
            requirement_gate_pass += 1
        elif replay.scenario_id not in {"normal", "high_risk"}:
            failures.append(
                {
                    "case_id": replay.case_id,
                    "metric": "requirements_gate",
                    "detail": "initial state contains a solution response",
                }
            )
        if replay.scenario_id == "high_risk" and replay.states.pending is None:
            failures.append(
                {
                    "case_id": replay.case_id,
                    "metric": "high_risk_review",
                    "detail": "high-risk replay has no pending review state",
                }
            )
        outputs.append(
            {
                "scenario_id": replay.scenario_id,
                "case_id": replay.case_id,
                "status": final.get("status"),
                "response": response,
            }
        )

    summary = EvaluationSummary(
        total=len(replays),
        schema_pass=schema_pass,
        evidence_present=evidence_present,
        requirement_gate_pass=requirement_gate_pass,
        no_evidence_guard=no_evidence_guard,
        high_risk_review=high_risk_review,
        failures=failures,
    )
    return summary, outputs


def write_evaluation_report(path: str | Path, summary: EvaluationSummary, outputs: list[dict[str, Any]]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({"mode": "v2-replay", "summary": summary.to_dict(), "outputs": outputs}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
