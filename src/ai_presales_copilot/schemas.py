"""Stable, dependency-free data contracts shared by the two demos."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Priority = Literal["must", "should", "nice_to_have"]
ReviewStatus = Literal["not_required", "pending", "approved", "rejected"]
# ---------------------------------------------------------------------------
# Versioned, strict v2 contracts used by the local-model runtime.
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
    # ``None`` means the customer has not answered the audit question yet;
    # ``False`` is an explicit answer and must not be collapsed into missing.
    audit_required: bool | None = None
    allowed_roles: list[str] = Field(default_factory=list)


class CustomerBriefV2(StrictModel):
    schema_version: Literal["2.0"] = "2.0"
    case_id: str = Field(min_length=1, max_length=128)
    industry: str = Field(min_length=1, max_length=256)
    business_goal: str | None = Field(default=None, max_length=2_000)
    use_case: str = Field(min_length=1, max_length=512)
    target_users: list[str] = Field(default_factory=list, max_length=64)
    current_process: str | None = Field(default=None, max_length=2_000)
    data_types: list[str] = Field(default_factory=list, max_length=64)
    deployment: str = Field(default="未说明", max_length=128)
    capacity: CapacityRequirements = Field(default_factory=CapacityRequirements)
    governance: DataGovernanceRequirements = Field(default_factory=DataGovernanceRequirements)
    budget: str = Field(default="未说明", max_length=256)
    timeline: str | None = Field(default=None, max_length=256)
    integrations: list[str] = Field(default_factory=list, max_length=64)
    acceptance_criteria: list[str] = Field(default_factory=list, max_length=64)
    raw_request: str = Field(default="", max_length=20_000)

class IntakeBriefV2(StrictModel):
    """Nullable brief produced from an unstructured customer request.

    Intake must be able to represent an unknown value without using the
    ``未说明`` sentinel, so the requirements-first workflow uses this model
    until the customer confirms the brief.
    """

    schema_version: Literal["2.0"] = "2.0"
    case_id: str = Field(min_length=1, max_length=128)
    industry: str | None = Field(default=None, max_length=256)
    business_goal: str | None = Field(default=None, max_length=2_000)
    use_case: str | None = Field(default=None, max_length=512)
    target_users: list[str] = Field(default_factory=list, max_length=64)
    current_process: str | None = Field(default=None, max_length=2_000)
    data_types: list[str] = Field(default_factory=list, max_length=64)
    deployment: str | None = Field(default=None, max_length=128)
    capacity: CapacityRequirements = Field(default_factory=CapacityRequirements)
    governance: DataGovernanceRequirements = Field(default_factory=DataGovernanceRequirements)
    budget: str | None = Field(default=None, max_length=256)
    timeline: str | None = Field(default=None, max_length=256)
    integrations: list[str] = Field(default_factory=list, max_length=64)
    acceptance_criteria: list[str] = Field(default_factory=list, max_length=64)
    raw_request: str = Field(default="", max_length=20_000)


RequirementFactStatus = Literal[
    "stated", "confirmed", "inferred", "missing", "ambiguous", "conflicting"
]
RequirementImportance = Literal["blocking", "warning"]


class CustomerInputV2(StrictModel):
    """The only formal input required to start a requirements-first run."""

    raw_request: str = Field(min_length=1, max_length=20_000)
    source: Literal["meeting_notes", "email", "chat", "form", "other"] = "chat"
    locale: str = Field(default="zh-CN", min_length=2, max_length=32)
    received_at: str | None = None

class InputTurnV2(StrictModel):
    """One immutable customer or clarification message."""

    turn_id: str = Field(min_length=1, max_length=128)
    role: Literal["customer", "presales"] = "customer"
    content: str = Field(min_length=1, max_length=20_000)
    source: Literal["initial", "clarification", "form_edit"] = "initial"
    created_at: str


class RequirementFactV2(StrictModel):
    """A field-level extraction with an auditable source attribution."""

    field_path: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=128)
    value_text: str | None = Field(default=None, max_length=2_000)
    status: RequirementFactStatus
    importance: RequirementImportance
    confidence: float | None = Field(default=None, ge=0, le=1)
    source_turn_id: str | None = Field(default=None, max_length=128)
    source_quote: str | None = Field(default=None, max_length=2_000)
    start_char: int | None = Field(default=None, ge=0)
    end_char: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_attribution(self) -> RequirementFactV2:
        if self.status in {"stated", "confirmed"} and (
            not self.source_turn_id or not self.source_quote
        ):
            raise ValueError("stated or confirmed facts require source_turn_id and source_quote")
        if (self.start_char is None) != (self.end_char is None):
            raise ValueError("start_char and end_char must be provided together")
        if (
            self.start_char is not None
            and self.end_char is not None
            and self.end_char < self.start_char
        ):
            raise ValueError("end_char must be greater than or equal to start_char")
        return self


class RequirementConflictV2(StrictModel):
    field_path: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=2_000)
    source_turn_ids: list[str] = Field(default_factory=list, max_length=16)
    resolution_question: str = Field(min_length=1, max_length=1_000)


class RequirementExtractionV2(StrictModel):
    """Model-facing extraction result; readiness is computed by host code."""

    schema_version: Literal["2.0"] = "2.0"
    brief: IntakeBriefV2
    facts: list[RequirementFactV2] = Field(default_factory=list, max_length=128)
    conflicts: list[RequirementConflictV2] = Field(default_factory=list, max_length=32)
    assumptions: list[str] = Field(default_factory=list, max_length=64)


class ClarificationQuestionV2(StrictModel):
    question_id: str = Field(min_length=1, max_length=128)
    field_path: str = Field(min_length=1, max_length=128)
    question: str = Field(min_length=1, max_length=1_000)
    why_it_matters: str = Field(min_length=1, max_length=1_000)
    importance: RequirementImportance
    answer_type: Literal["text", "choice", "number", "boolean", "list"] = "text"
    choices: list[str] = Field(default_factory=list, max_length=32)


class RequirementAssessmentV2(StrictModel):
    """Deterministic completeness projection shown to the user."""

    ready_for_confirmation: bool = False
    blocking_fields: list[str] = Field(default_factory=list, max_length=32)
    warning_fields: list[str] = Field(default_factory=list, max_length=64)
    conflicts: list[RequirementConflictV2] = Field(default_factory=list, max_length=32)
    questions: list[ClarificationQuestionV2] = Field(default_factory=list, max_length=16)
    clarification_turns: int = Field(default=0, ge=0, le=3)
    max_clarification_turns: int = Field(default=3, ge=1, le=3)


class RequirementOverrideV2(StrictModel):
    field_path: str = Field(min_length=1, max_length=128)
    value_text: str = Field(min_length=1, max_length=2_000)


class RunInputRequestV2(StrictModel):
    input: CustomerInputV2
    source: Literal["meeting_notes", "email", "chat", "form", "other"] | None = None


class ClarificationRequestV2(StrictModel):
    message: str = Field(min_length=1, max_length=20_000)
    overrides: list[RequirementOverrideV2] = Field(default_factory=list, max_length=32)
    expected_state_version: int | None = Field(default=None, ge=0)
    state_version: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def normalize_state_version(self) -> ClarificationRequestV2:
        if (
            self.expected_state_version is not None
            and self.state_version is not None
            and self.expected_state_version != self.state_version
        ):
            raise ValueError("expected_state_version and state_version must match")
        return self


class RequirementConfirmRequestV2(StrictModel):
    decision: Literal["confirm"] = "confirm"
    acknowledged_warnings: list[str] = Field(default_factory=list, max_length=64)
    expected_state_version: int | None = Field(default=None, ge=0)
    state_version: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def normalize_state_version(self) -> RequirementConfirmRequestV2:
        if (
            self.expected_state_version is not None
            and self.state_version is not None
            and self.expected_state_version != self.state_version
        ):
            raise ValueError("expected_state_version and state_version must match")
        return self


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
