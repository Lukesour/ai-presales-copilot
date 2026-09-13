"""Small model-facing JSON Schemas for llama.cpp constrained decoding.

Pydantic schemas remain the authoritative application contracts.  These
schemas deliberately avoid ``$defs``/``$ref``, large ``maxItems`` values and
deeply repeated constraints because llama.cpp converts JSON Schema to a GBNF
grammar before generation.  The generated JSON is always validated again by
the host with the full Pydantic models.
"""

from __future__ import annotations

from typing import Any

REQUIREMENT_FACT_PATHS = (
    "business_goal",
    "use_case",
    "target_users",
    "data_types",
    "deployment",
    "governance.residency",
    "acceptance_criteria",
    "industry",
    "capacity.peak_concurrency",
    "capacity.latency_target",
    "integrations",
    "budget",
    "timeline",
    "governance.audit_required",
    "governance.egress_allowed",
)


def _nullable(kind: str) -> dict[str, Any]:
    return {"type": [kind, "null"]}


def _string_list(max_items: int = 8) -> dict[str, Any]:
    return {"type": "array", "items": {"type": "string"}, "maxItems": max_items}


def _nullable_integer() -> dict[str, Any]:
    return _nullable("integer")


def _nullable_number() -> dict[str, Any]:
    return _nullable("number")


def _requirement_fact_entry_schema() -> dict[str, Any]:
    fact_value_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "value": {"type": "string"},
            "quote": {"type": "string"},
        },
        "required": ["value", "quote"],
    }
    return fact_value_schema


def requirements_group_schema(field_paths: tuple[str, ...]) -> dict[str, Any]:
    """Return a small schema for one model extraction group.

    llama.cpp turns JSON Schema into a grammar.  Keeping each request to a
    small, flat object avoids the semantic field drift and grammar expansion
    seen with one large repeated fact schema while retaining hard JSON shape
    constraints at the model boundary.
    """

    unknown = set(field_paths) - set(REQUIREMENT_FACT_PATHS)
    if unknown:
        raise ValueError(f"unsupported requirement fields: {', '.join(sorted(unknown))}")
    fact_value_schema = _requirement_fact_entry_schema()
    return {
        "title": "RequirementExtractionGroupModelOutput",
        "type": "object",
        "additionalProperties": False,
        "properties": {path: fact_value_schema for path in field_paths},
        "required": list(field_paths),
    }


def requirements_extraction_schema() -> dict[str, Any]:
    """Return the complete flat schema used by schema export checks."""

    schema = requirements_group_schema(REQUIREMENT_FACT_PATHS)
    schema["title"] = "RequirementExtractionModelOutput"
    return schema


def solution_draft_schema() -> dict[str, Any]:
    """Return the bounded model-facing schema for draft and repair nodes."""

    requirement = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "name": {"type": "string"},
            "value": {"type": "string"},
            "priority": {"type": "string", "enum": ["must", "should", "nice_to_have"]},
            "source": {
                "type": "string",
                "enum": ["customer", "customer_brief", "inferred", "system", "reviewer"],
            },
        },
        "required": ["name", "value", "priority", "source"],
    }
    claim = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "claim_id": {"type": "string"},
            "text": {"type": "string"},
            "claim_type": {"type": "string", "enum": ["fact", "recommendation", "assumption", "unknown"]},
            "support_status": {"type": "string", "enum": ["supported", "unsupported", "needs_review"]},
            "evidence_ids": _string_list(8),
            "confidence": _nullable_number(),
        },
        "required": ["claim_id", "text", "claim_type", "support_status", "evidence_ids", "confidence"],
    }
    risk = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "category": {"type": "string"},
            "description": {"type": "string"},
            "severity": {"type": "string", "enum": ["low", "medium", "high"]},
            "action": {"type": "string"},
        },
        "required": ["category", "description", "severity", "action"],
    }
    poc_phase = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "phase": {"type": "string"},
            "objective": {"type": "string"},
            "activities": _string_list(),
            "deliverables": _string_list(),
            "exit_criteria": {"type": "string"},
        },
        "required": ["phase", "objective", "activities", "deliverables", "exit_criteria"],
    }
    review = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "required": {"type": "boolean"},
            "status": {"type": "string", "enum": ["not_required", "pending", "approved", "rejected"]},
        },
        "required": ["required", "status"],
    }
    properties = {
        "schema_version": {"type": "string", "enum": ["2.0"]},
        "case_id": {"type": "string"},
        "executive_summary": {"type": "string"},
        "requirements": {"type": "array", "items": requirement, "maxItems": 16},
        "claims": {"type": "array", "items": claim, "maxItems": 16},
        "recommendations": _string_list(16),
        "architecture": _string_list(16),
        "implementation_steps": _string_list(16),
        "risks": {"type": "array", "items": risk, "maxItems": 16},
        "clarifying_questions": _string_list(8),
        "selected_evidence_ids": _string_list(8),
        "poc_plan": {"type": "array", "items": poc_phase, "maxItems": 8},
        "model_strategy": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "primary_serving_path": {"type": "string"},
                "fallback_serving_path": {"type": "string"},
                "serving_reason": {"type": "string"},
            },
            "required": [],
        },
        "assumptions": _string_list(16),
        "review": review,
    }
    return {
        "title": "SolutionDraftModelOutput",
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": list(properties),
    }
