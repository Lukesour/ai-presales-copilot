"""Stable, dependency-free data contracts shared by the two demos."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Priority = Literal["must", "should", "nice_to_have"]
ReviewStatus = Literal["not_required", "pending", "approved", "rejected"]
REQUIRED_RESPONSE_FIELDS = (
    "case_id",
    "executive_summary",
    "requirements",
    "recommendation",
    "architecture",
    "implementation_steps",
    "risks",
    "clarifying_questions",
    "evidence",
    "poc_plan",
    "model_strategy",
    "assumptions",
    "review_status",
)


@dataclass(frozen=True)
class CustomerBrief:
    """A normalized customer brief used by the demo and evaluation harness."""

    case_id: str
    industry: str
    use_case: str
    data_types: list[str] = field(default_factory=list)
    deployment: str = "未说明"
    concurrency: str = "未说明"
    latency_requirement: str = "未说明"
    compliance: list[str] = field(default_factory=list)
    budget: str = "未说明"
    raw_request: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Requirement:
    """One explicit or inferred customer constraint."""

    name: str
    value: str
    priority: Priority = "should"
    source: str = "customer_brief"


@dataclass(frozen=True)
class Evidence:
    """A claim-supporting excerpt or a deliberate no-evidence marker."""

    evidence_id: str
    title: str
    excerpt: str
    source_path: str
    relevance: float = 0.0


@dataclass(frozen=True)
class RiskFlag:
    """A risk that should be disclosed instead of hidden in a sales answer."""

    category: str
    description: str
    severity: Literal["low", "medium", "high"] = "medium"
    action: str = "补充确认"


@dataclass
class SolutionResponse:
    """The response contract expected from Dify or the local deterministic demo."""

    case_id: str
    executive_summary: str
    requirements: list[Requirement] = field(default_factory=list)
    recommendation: list[str] = field(default_factory=list)
    architecture: list[str] = field(default_factory=list)
    implementation_steps: list[str] = field(default_factory=list)
    risks: list[RiskFlag] = field(default_factory=list)
    clarifying_questions: list[str] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    poc_plan: list[dict[str, Any]] = field(default_factory=list)
    model_strategy: dict[str, Any] = field(default_factory=dict)
    assumptions: list[str] = field(default_factory=list)
    review_status: ReviewStatus = "not_required"
    model_name: str = "mock"
    latency_ms: float | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    run_id: str | None = None
    trace_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _require_string(value: Any, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


def validate_solution_dict(
    payload: dict[str, Any], *, require_all_fields: bool = False
) -> None:
    """Validate the response shape without requiring Pydantic.

    The default remains backward-compatible for partial Dify error payloads.
    Model quality gates and training targets should set ``require_all_fields``
    so a syntactically valid but incomplete object cannot pass the schema gate.
    """

    if not isinstance(payload, dict):
        raise TypeError("solution response must be an object")
    if require_all_fields:
        missing = [field for field in REQUIRED_RESPONSE_FIELDS if field not in payload]
        if missing:
            raise ValueError("missing required response fields: " + ", ".join(missing))
    for field_name in ("case_id", "executive_summary"):
        _require_string(payload.get(field_name), field_name)
    for list_field in (
        "requirements",
        "recommendation",
        "architecture",
        "implementation_steps",
        "risks",
        "clarifying_questions",
        "evidence",
    ):
        if not isinstance(payload.get(list_field, []), list):
            raise TypeError(f"{list_field} must be an array")
    status = payload.get("review_status", "not_required")
    if status not in {"not_required", "pending", "approved", "rejected"}:
        raise ValueError(f"unsupported review_status: {status}")
    for item in payload.get("evidence", []):
        if not isinstance(item, dict):
            raise TypeError("each evidence item must be an object")
        for field_name in ("evidence_id", "title", "excerpt", "source_path"):
            _require_string(item.get(field_name), f"evidence.{field_name}")
    for field_name in ("poc_plan", "assumptions"):
        if field_name in payload and not isinstance(payload[field_name], list):
            raise TypeError(f"{field_name} must be an array")
    for item in payload.get("poc_plan", []):
        if not isinstance(item, dict):
            raise TypeError("each poc_plan item must be an object")
        for field_name in ("phase", "objective", "exit_criteria"):
            _require_string(item.get(field_name), f"poc_plan.{field_name}")
    if "model_strategy" in payload and not isinstance(payload["model_strategy"], dict):
        raise TypeError("model_strategy must be an object")
    if "assumptions" in payload and any(not isinstance(item, str) for item in payload["assumptions"]):
        raise TypeError("assumptions items must be strings")
