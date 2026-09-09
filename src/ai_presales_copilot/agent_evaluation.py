"""Deterministic quality gates for the Agent + POC contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .agent import PresalesAgent
from .knowledge import KnowledgeBase
from .persistence import CheckpointStore
from .schemas import CustomerBrief, validate_solution_dict


@dataclass(frozen=True)
class AgentEvaluationSummary:
    total: int
    completed: int
    schema_pass: int
    poc_present: int
    model_strategy_present: int
    evidence_valid: int
    review_gate_pass: int
    failures: list[dict[str, str]]

    def to_dict(self) -> dict[str, Any]:
        def rate(value: int) -> float:
            return round(value / self.total, 4) if self.total else 0.0

        return {
            "total": self.total,
            "completed": self.completed,
            "completed_rate": rate(self.completed),
            "schema_pass": self.schema_pass,
            "schema_pass_rate": rate(self.schema_pass),
            "poc_present": self.poc_present,
            "poc_present_rate": rate(self.poc_present),
            "model_strategy_present": self.model_strategy_present,
            "model_strategy_present_rate": rate(self.model_strategy_present),
            "evidence_valid": self.evidence_valid,
            "evidence_valid_rate": rate(self.evidence_valid),
            "review_gate_pass": self.review_gate_pass,
            "review_gate_pass_rate": rate(self.review_gate_pass),
            "failures": self.failures,
        }


def evaluate_agent_cases(
    cases: list[CustomerBrief], knowledge_base: KnowledgeBase
) -> tuple[AgentEvaluationSummary, list[dict[str, Any]]]:
    """Run every case, approve only inside the test harness, and inspect both gates."""

    completed = schema_pass = poc_present = strategy_present = evidence_valid = 0
    review_gate_pass = 0
    failures: list[dict[str, str]] = []
    outputs: list[dict[str, Any]] = []

    for case in cases:
        with CheckpointStore(":memory:") as store:
            agent = PresalesAgent(knowledge_base, store)
            thread_id = f"eval:{case.case_id}"
            first = agent.run(case, thread_id=thread_id)
            needs_review = bool(first.risks and any(r.severity == "high" for r in first.risks)) or bool(
                case.compliance
            )
            if (first.status == "pending_review") == needs_review:
                review_gate_pass += 1
            else:
                failures.append(
                    {
                        "case_id": case.case_id,
                        "metric": "review_gate",
                        "detail": f"expected={needs_review} status={first.status}",
                    }
                )
            state = (
                agent.run(thread_id=thread_id, review_decision="approve")
                if first.status == "pending_review"
                else first
            )
            response = state.response
            if state.status == "complete":
                completed += 1
            if response is None:
                failures.append({"case_id": case.case_id, "metric": "response", "detail": "missing"})
                continue
            payload = response.to_dict()
            outputs.append(payload)
            try:
                validate_solution_dict(payload)
                schema_pass += 1
            except (TypeError, ValueError) as exc:
                failures.append({"case_id": case.case_id, "metric": "schema", "detail": str(exc)})
            if response.poc_plan:
                poc_present += 1
            else:
                failures.append({"case_id": case.case_id, "metric": "poc", "detail": "missing"})
            if response.model_strategy:
                strategy_present += 1
            else:
                failures.append(
                    {"case_id": case.case_id, "metric": "model_strategy", "detail": "missing"}
                )
            evidence_is_valid = (
                all(item.evidence_id and item.source_path for item in response.evidence)
                if response.evidence
                else "资料不足" in response.executive_summary
                and any(risk.category == "知识覆盖" for risk in response.risks)
            )
            if evidence_is_valid:
                evidence_valid += 1
            else:
                failures.append(
                    {"case_id": case.case_id, "metric": "evidence", "detail": "invalid citation"}
                )

    summary = AgentEvaluationSummary(
        total=len(cases),
        completed=completed,
        schema_pass=schema_pass,
        poc_present=poc_present,
        model_strategy_present=strategy_present,
        evidence_valid=evidence_valid,
        review_gate_pass=review_gate_pass,
        failures=failures,
    )
    return summary, outputs
