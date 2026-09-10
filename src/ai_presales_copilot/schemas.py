"""Stable, dependency-free data contracts shared by the two demos."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
    source_id: str | None = None
    source_url: str | None = None
    version: str | None = None
    license: str | None = None
    page: int | None = None
    locator: str | None = None
    content_hash: str | None = None
    fetched_at: str | None = None
    effective_from: str | None = None
    effective_to: str | None = None
    tenant_id: str = "public"
    acl: list[str] = field(default_factory=list)


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
        if "relevance" in item and (
            not isinstance(item["relevance"], (int, float))
            or not 0 <= float(item["relevance"]) <= 1
        ):
            raise ValueError("evidence.relevance must be between 0 and 1")
    for item in payload.get("requirements", []):
        if not isinstance(item, dict):
            raise TypeError("each requirement must be an object")
        for field_name in ("name", "value", "priority", "source"):
            _require_string(item.get(field_name), f"requirements.{field_name}")
        if item["priority"] not in {"must", "should", "nice_to_have"}:
            raise ValueError(f"unsupported requirement priority: {item['priority']}")
    for item in payload.get("risks", []):
        if not isinstance(item, dict):
            raise TypeError("each risk must be an object")
        for field_name in ("category", "description", "severity", "action"):
            _require_string(item.get(field_name), f"risks.{field_name}")
        if item["severity"] not in {"low", "medium", "high"}:
            raise ValueError(f"unsupported risk severity: {item['severity']}")
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


# ---------------------------------------------------------------------------
# Versioned, strict v2 contracts used by the local-model runtime.
#
# The original dataclasses remain available for backwards-compatible fixtures
# and the deterministic test harness.  New API and LLM code should use these
# models so that the JSON Schema, runtime validation, and persisted payloads
# share one source of truth.
# ---------------------------------------------------------------------------


class StrictModel(BaseModel):
    """Pydantic model with the boundary defaults required by the API."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        str_strip_whitespace=True,
        validate_assignment=True,
        use_enum_values=True,
    )


class CapacityRequirements(StrictModel):
    average_concurrency: float | None = Field(default=None, ge=0)
    peak_concurrency: int | None = Field(default=None, ge=0)
    daily_requests: int | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    context_tokens: int | None = Field(default=None, ge=0)
    ttft_target_ms: int | None = Field(default=None, ge=0)
    full_answer_target_ms: int | None = Field(default=None, ge=0)
    availability_target: str | None = None
    rto_minutes: int | None = Field(default=None, ge=0)
    rpo_minutes: int | None = Field(default=None, ge=0)


class DataGovernanceRequirements(StrictModel):
    data_classification: str | None = None
    residency: str | None = None
    egress_allowed: bool | None = None
    retention_days: int | None = Field(default=None, ge=0)
    audit_required: bool = False
    allowed_roles: list[str] = Field(default_factory=list)


class CustomerBriefV2(StrictModel):
    schema_version: Literal["2.0"] = "2.0"
    case_id: str = Field(min_length=1, max_length=128)
    industry: str = Field(min_length=1, max_length=256)
    use_case: str = Field(min_length=1, max_length=512)
    data_types: list[str] = Field(default_factory=list, max_length=64)
    deployment: str = Field(default="未说明", max_length=128)
    capacity: CapacityRequirements = Field(default_factory=CapacityRequirements)
    governance: DataGovernanceRequirements = Field(default_factory=DataGovernanceRequirements)
    budget: str = Field(default="未说明", max_length=256)
    integrations: list[str] = Field(default_factory=list, max_length=64)
    acceptance_criteria: list[str] = Field(default_factory=list, max_length=64)
    raw_request: str = Field(default="", max_length=20_000)

    @classmethod
    def from_legacy(cls, brief: CustomerBrief) -> CustomerBriefV2:
        return cls(
            case_id=brief.case_id,
            industry=brief.industry,
            use_case=brief.use_case,
            data_types=brief.data_types,
            deployment=brief.deployment,
            capacity=CapacityRequirements(
                peak_concurrency=_extract_int(brief.concurrency),
                full_answer_target_ms=_extract_int(brief.latency_requirement),
            ),
            governance=DataGovernanceRequirements(
                residency=";".join(brief.compliance) if brief.compliance else None,
                egress_allowed=False if "数据不能出域" in brief.compliance else None,
                audit_required=any("审计" in item for item in brief.compliance),
            ),
            budget=brief.budget,
            raw_request=brief.raw_request,
        )

    def to_legacy(self) -> CustomerBrief:
        concurrency = (
            f"峰值 {self.capacity.peak_concurrency}"
            if self.capacity.peak_concurrency is not None
            else "未说明"
        )
        latency = (
            f"完整答案 {self.capacity.full_answer_target_ms} 毫秒"
            if self.capacity.full_answer_target_ms is not None
            else "未说明"
        )
        compliance: list[str] = []
        if self.governance.residency:
            compliance.append(self.governance.residency)
        if self.governance.egress_allowed is False:
            compliance.append("数据不能出域")
        if self.governance.audit_required:
            compliance.append("审计日志")
        return CustomerBrief(
            case_id=self.case_id,
            industry=self.industry,
            use_case=self.use_case,
            data_types=list(self.data_types),
            deployment=self.deployment,
            concurrency=concurrency,
            latency_requirement=latency,
            compliance=compliance,
            budget=self.budget,
            raw_request=self.raw_request,
        )


class RequirementV2(StrictModel):
    name: str = Field(min_length=1, max_length=128)
    value: str = Field(min_length=1, max_length=2_000)
    priority: Priority = "should"
    source: Literal["customer", "customer_brief", "inferred", "system", "reviewer"] = "customer"


class EvidenceChunkV2(StrictModel):
    evidence_id: str = Field(min_length=1, max_length=256)
    source_id: str = Field(min_length=1, max_length=256)
    source_url: str | None = None
    source_path: str | None = None
    title: str = Field(min_length=1, max_length=512)
    version: str | None = None
    license: str | None = None
    excerpt: str = Field(min_length=1, max_length=10_000)
    page: int | None = Field(default=None, ge=1)
    locator: str | None = None
    content_hash: str = Field(min_length=1, max_length=128)
    fetched_at: str | None = None
    effective_from: str | None = None
    effective_to: str | None = None
    tenant_id: str = Field(default="public", min_length=1, max_length=128)
    acl: list[str] = Field(default_factory=list, max_length=128)
    retrieval_only: bool = True
    training_allowed: bool = False
    relevance: float = Field(default=0, ge=0, le=1)


class ClaimV2(StrictModel):
    claim_id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=4_000)
    claim_type: Literal["fact", "recommendation", "assumption", "unknown"]
    support_status: Literal["supported", "unsupported", "needs_review"]
    evidence_ids: list[str] = Field(default_factory=list, max_length=32)
    confidence: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def facts_need_support(self) -> ClaimV2:
        if self.claim_type == "fact" and not self.evidence_ids:
            raise ValueError("fact claims must reference at least one evidence_id")
        return self


class RiskV2(StrictModel):
    category: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=4_000)
    severity: Literal["low", "medium", "high"] = "medium"
    action: str = Field(min_length=1, max_length=2_000)


class PocPhaseV2(StrictModel):
    phase: str = Field(min_length=1, max_length=256)
    objective: str = Field(min_length=1, max_length=2_000)
    activities: list[str] = Field(default_factory=list, max_length=64)
    deliverables: list[str] = Field(default_factory=list, max_length=64)
    exit_criteria: str = Field(min_length=1, max_length=2_000)


class ReviewV2(StrictModel):
    required: bool = False
    status: ReviewStatus = "not_required"
    reviewer_id: str | None = None
    reviewer_role: str | None = None
    reason: str | None = None
    requested_at: str | None = None
    decided_at: str | None = None
    state_version: int = Field(default=0, ge=0)
    idempotency_key: str | None = None


class RunProvenanceV2(StrictModel):
    run_id: str = Field(min_length=1, max_length=128)
    trace_id: str = Field(min_length=1, max_length=128)
    thread_id: str = Field(min_length=1, max_length=256)
    model_name: str = Field(min_length=1, max_length=256)
    model_hash: str | None = None
    prompt_version: str = Field(min_length=1, max_length=128)
    schema_version: str = "2.0"
    knowledge_snapshot_id: str | None = None
    model_quantization: str | None = None
    context_length: int | None = Field(default=None, ge=1)
    llama_cpp_commit: str | None = None
    sampling_params: dict[str, Any] = Field(default_factory=dict)
    generated_at: str


class QualityV2(StrictModel):
    parse_pass: bool = False
    schema_pass: bool = False
    evidence_coverage: float = Field(default=0, ge=0, le=1)
    citation_precision: float | None = Field(default=None, ge=0, le=1)
    repair_attempts: int = Field(default=0, ge=0, le=2)
    structured_retries: int = Field(default=0, ge=0, le=1)
    citation_recall: float | None = Field(default=None, ge=0, le=1)
    latency_ms: float | None = Field(default=None, ge=0)
    ttft_ms: float | None = Field(default=None, ge=0)
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


class SolutionResponseV2(StrictModel):
    schema_version: Literal["2.0"] = "2.0"
    case_id: str = Field(min_length=1, max_length=128)
    executive_summary: str = Field(min_length=1, max_length=8_000)
    requirements: list[RequirementV2] = Field(default_factory=list, max_length=128)
    claims: list[ClaimV2] = Field(default_factory=list, max_length=256)
    recommendations: list[str] = Field(default_factory=list, max_length=128)
    architecture: list[str] = Field(default_factory=list, max_length=128)
    implementation_steps: list[str] = Field(default_factory=list, max_length=128)
    risks: list[RiskV2] = Field(default_factory=list, max_length=128)
    clarifying_questions: list[str] = Field(default_factory=list, max_length=128)
    evidence: list[EvidenceChunkV2] = Field(default_factory=list, max_length=256)
    poc_plan: list[PocPhaseV2] = Field(default_factory=list, max_length=16)
    model_strategy: dict[str, Any] = Field(default_factory=dict)
    assumptions: list[str] = Field(default_factory=list, max_length=128)
    review: ReviewV2 = Field(default_factory=ReviewV2)
    provenance: RunProvenanceV2
    quality: QualityV2 = Field(default_factory=QualityV2)

    @model_validator(mode="after")
    def validate_claim_references(self) -> SolutionResponseV2:
        evidence_ids = {item.evidence_id for item in self.evidence}
        unknown = {
            evidence_id
            for claim in self.claims
            for evidence_id in claim.evidence_ids
            if evidence_id not in evidence_ids
        }
        if unknown:
            raise ValueError("claims reference unknown evidence_ids: " + ", ".join(sorted(unknown)))
        return self


class SolutionDraftV2(StrictModel):
    """Model-facing response; retrieved evidence content stays host-owned."""

    schema_version: Literal["2.0"] = "2.0"
    case_id: str = Field(min_length=1, max_length=128)
    executive_summary: str = Field(min_length=1, max_length=8_000)
    requirements: list[RequirementV2] = Field(default_factory=list, max_length=128)
    claims: list[ClaimV2] = Field(default_factory=list, max_length=256)
    recommendations: list[str] = Field(default_factory=list, max_length=128)
    architecture: list[str] = Field(default_factory=list, max_length=128)
    implementation_steps: list[str] = Field(default_factory=list, max_length=128)
    risks: list[RiskV2] = Field(default_factory=list, max_length=128)
    clarifying_questions: list[str] = Field(default_factory=list, max_length=128)
    selected_evidence_ids: list[str] = Field(default_factory=list, max_length=256)
    poc_plan: list[PocPhaseV2] = Field(default_factory=list, max_length=16)
    model_strategy: dict[str, Any] = Field(default_factory=dict)
    assumptions: list[str] = Field(default_factory=list, max_length=128)
    review: ReviewV2 = Field(default_factory=ReviewV2)


def _extract_int(value: str) -> int | None:
    import re

    match = re.search(r"(\d+)", value or "")
    return int(match.group(1)) if match else None
