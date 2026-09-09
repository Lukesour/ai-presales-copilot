"""Evaluation helpers for quality gates that do not call an LLM judge."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .schemas import CustomerBrief, SolutionResponse, validate_solution_dict


@dataclass(frozen=True)
class EvaluationSummary:
    total: int
    schema_pass: int
    evidence_present: int
    requirement_coverage: float
    no_evidence_guard: int
    high_risk_review: int
    failures: list[dict[str, str]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "schema_pass": self.schema_pass,
            "schema_pass_rate": round(self.schema_pass / self.total, 4) if self.total else 0.0,
            "evidence_present": self.evidence_present,
            "evidence_present_rate": round(self.evidence_present / self.total, 4)
            if self.total
            else 0.0,
            "requirement_coverage": round(self.requirement_coverage, 4),
            "no_evidence_guard": self.no_evidence_guard,
            "high_risk_review": self.high_risk_review,
            "failures": self.failures,
        }


def load_cases(path: str | Path) -> list[CustomerBrief]:
    cases: list[CustomerBrief] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            cases.append(CustomerBrief(**json.loads(line)))
    return cases


def evaluate_cases(
    cases: list[CustomerBrief],
    analyze: Callable[[CustomerBrief], SolutionResponse],
) -> tuple[EvaluationSummary, list[dict[str, Any]]]:
    schema_pass = 0
    evidence_present = 0
    coverage_scores: list[float] = []
    no_evidence_guard = 0
    high_risk_review = 0
    failures: list[dict[str, str]] = []
    outputs: list[dict[str, Any]] = []

    for case in cases:
        response = analyze(case)
        output = response.to_dict()
        output["case_id"] = case.case_id
        outputs.append(output)
        try:
            validate_solution_dict(output)
            schema_pass += 1
        except ValueError as exc:
            failures.append({"case_id": case.case_id, "metric": "schema", "detail": str(exc)})

        if response.evidence:
            evidence_present += 1
        requested_fields = [
            case.industry,
            case.use_case,
            case.deployment,
            case.concurrency,
            case.latency_requirement,
        ]
        matched = sum(
            any(value in requirement.value for requirement in response.requirements)
            for value in requested_fields
            if value != "未说明"
        )
        expected = sum(value != "未说明" for value in requested_fields)
        coverage_scores.append(matched / expected if expected else 1.0)

        if not response.evidence and any(
            word in response.executive_summary for word in ("资料不足", "不确定", "证据")
        ):
            no_evidence_guard += 1
        elif not response.evidence:
            failures.append(
                {
                    "case_id": case.case_id,
                    "metric": "no_evidence_guard",
                    "detail": "missing conservative fallback",
                }
            )

        high_risk = bool(case.compliance) or case.deployment in {"私有化", "内网", "本地"}
        if not high_risk or response.review_status in {"pending", "approved", "rejected"}:
            high_risk_review += 1
        else:
            failures.append(
                {
                    "case_id": case.case_id,
                    "metric": "high_risk_review",
                    "detail": "review gate not triggered",
                }
            )

    summary = EvaluationSummary(
        total=len(cases),
        schema_pass=schema_pass,
        evidence_present=evidence_present,
        requirement_coverage=sum(coverage_scores) / len(coverage_scores)
        if coverage_scores
        else 0.0,
        no_evidence_guard=no_evidence_guard,
        high_risk_review=high_risk_review,
        failures=failures,
    )
    return summary, outputs
