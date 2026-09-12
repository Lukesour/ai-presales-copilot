"""Small model-facing JSON Schemas for llama.cpp constrained decoding.

Pydantic schemas remain the authoritative application contracts.  These
schemas deliberately avoid ``$defs``/``$ref``, large ``maxItems`` values and
deeply repeated constraints because llama.cpp converts JSON Schema to a GBNF
grammar before generation.  The generated JSON is always validated again by
the host with the full Pydantic models.
"""

from __future__ import annotations

from typing import Any


def _nullable(kind: str) -> dict[str, Any]:
    return {"type": [kind, "null"]}


def _string_list(max_items: int = 8) -> dict[str, Any]:
    return {"type": "array", "items": {"type": "string"}, "maxItems": max_items}


def _nullable_integer() -> dict[str, Any]:
    return _nullable("integer")


def _nullable_number() -> dict[str, Any]:
    return _nullable("number")


def _requirements_brief_schema() -> dict[str, Any]:
    properties: dict[str, Any] = {
        "schema_version": {"type": "string", "enum": ["2.0"]},
        "case_id": {"type": "string"},
        "industry": _nullable("string"),
        "business_goal": _nullable("string"),
        "use_case": _nullable("string"),
        "target_users": _string_list(),
        "current_process": _nullable("string"),
        "data_types": _string_list(),
        "deployment": _nullable("string"),
        "capacity": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "peak_concurrency": _nullable_integer(),
                "daily_requests": _nullable_integer(),
                "ttft_target_ms": _nullable_integer(),
                "full_answer_target_ms": _nullable_integer(),
            },
            "required": [
                "peak_concurrency",
                "daily_requests",
                "ttft_target_ms",
                "full_answer_target_ms",
            ],
        },
        "governance": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "residency": _nullable("string"),
                "egress_allowed": {"type": ["boolean", "null"]},
                "audit_required": {"type": ["boolean", "null"]},
            },
            "required": ["residency", "egress_allowed", "audit_required"],
        },
        "budget": _nullable("string"),
        "timeline": _nullable("string"),
        "integrations": _string_list(),
        "acceptance_criteria": _string_list(),
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": list(properties),
    }


def requirements_extraction_schema() -> dict[str, Any]:
    """Return the bounded schema used only during raw-requirement extraction."""

    fact_paths = [
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
    ]
    fact_properties = {
        "field_path": {"type": "string", "enum": fact_paths},
        "display_name": {"type": "string"},
        "value_text": _nullable("string"),
        "status": {
            "type": "string",
            "enum": ["stated", "confirmed", "inferred", "missing", "ambiguous", "conflicting"],
        },
        "importance": {"type": "string", "enum": ["blocking", "warning"]},
        "confidence": _nullable_number(),
        "source_turn_id": _nullable("string"),
        "source_quote": _nullable("string"),
        "start_char": _nullable_integer(),
        "end_char": _nullable_integer(),
    }
    conflict_properties = {
        "field_path": {"type": "string"},
        "description": {"type": "string"},
        "source_turn_ids": _string_list(4),
        "resolution_question": {"type": "string"},
    }
    return {
        "title": "RequirementExtractionModelOutput",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "schema_version": {"type": "string", "enum": ["2.0"]},
            "brief": _requirements_brief_schema(),
            "facts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": fact_properties,
                    "required": list(fact_properties),
                },
                "maxItems": 16,
            },
            "conflicts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": conflict_properties,
                    "required": list(conflict_properties),
                },
                "maxItems": 8,
            },
            "assumptions": _string_list(8),
        },
        "required": ["schema_version", "brief", "facts", "conflicts", "assumptions"],
    }


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
