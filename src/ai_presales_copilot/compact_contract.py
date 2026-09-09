"""A small model-facing contract for the presales Agent.

The public ``SolutionResponse`` is intentionally rich: it contains the full
POC plan, model strategy, evidence objects and runtime-facing review fields.
That is a good application contract, but it is too large for a 0.5B model to
reliably regenerate from a few dozen examples.  This module defines the
smaller contract used by the second QLoRA experiment.

The model only proposes a short decision object.  The deterministic Agent
retains ownership of requirements, retrieved evidence, the POC plan and
model strategy, then merges the model proposal under the same strict output
and risk gates.  This keeps mutable facts in RAG and avoids treating a model
completion as an authoritative business record.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .schemas import validate_solution_dict

COMPACT_REQUIRED_FIELDS = (
    "case_id",
    "executive_summary",
    "recommendation",
    "risk_flags",
    "clarifying_questions",
    "evidence_ids",
    "review_status",
)

COMPACT_SYSTEM_PROMPT = (
    "你是企业 AI 解决方案售前顾问。只输出一个合法 JSON 对象，不要输出 Markdown、"
    "代码围栏或解释。JSON 必须且只能包含字段：case_id、executive_summary、"
    "recommendation、risk_flags、clarifying_questions、evidence_ids、review_status。"
    "recommendation、risk_flags、clarifying_questions、evidence_ids 必须是字符串数组。"
    "review_status 只能是 not_required、pending、approved 或 rejected。"
    "只能使用客户输入和 retrieved_evidence；没有证据时保持保守，不编造价格、SLA、"
    "准确率、认证或容量。"
)


def validate_compact_solution_dict(payload: dict[str, Any]) -> None:
    """Validate the deliberately small model-facing response contract."""

    if not isinstance(payload, dict):
        raise TypeError("compact solution response must be an object")
    missing = [field for field in COMPACT_REQUIRED_FIELDS if field not in payload]
    if missing:
        raise ValueError("missing required compact response fields: " + ", ".join(missing))

    for field_name in ("case_id", "executive_summary"):
        value = payload.get(field_name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} must be a non-empty string")

    for field_name in (
        "recommendation",
        "risk_flags",
        "clarifying_questions",
        "evidence_ids",
    ):
        value = payload.get(field_name)
        if not isinstance(value, list):
            raise TypeError(f"{field_name} must be an array")
        if any(not isinstance(item, str) for item in value):
            raise TypeError(f"{field_name} items must be strings")

    status = payload.get("review_status")
    if status not in {"not_required", "pending", "approved", "rejected"}:
        raise ValueError(f"unsupported review_status: {status}")


def compact_target_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Project a full Agent response into the compact supervised target."""

    risks = []
    for item in payload.get("risks", []):
        if isinstance(item, dict):
            category = str(item.get("category", "风险"))
            description = str(item.get("description", ""))
            action = str(item.get("action", ""))
            text = f"{category}：{description}"
            if action:
                text += f"；行动：{action}"
            risks.append(text)
        elif isinstance(item, str):
            risks.append(item)

    target = {
        "case_id": payload.get("case_id", ""),
        "executive_summary": payload.get("executive_summary", ""),
        "recommendation": list(payload.get("recommendation", []))[:4],
        "risk_flags": risks[:4],
        "clarifying_questions": list(payload.get("clarifying_questions", []))[:4],
        "evidence_ids": [
            item.get("evidence_id")
            for item in payload.get("evidence", [])[:4]
            if isinstance(item, dict) and item.get("evidence_id")
        ],
        "review_status": payload.get("review_status", "pending"),
    }
    validate_compact_solution_dict(target)
    return target


def merge_compact_solution(
    base_payload: dict[str, Any], compact_payload: dict[str, Any]
) -> dict[str, Any]:
    """Merge a model proposal into a deterministic, evidence-aware response.

    The base payload remains authoritative for requirements, architecture,
    POC, model strategy and evidence content.  The model can select evidence
    IDs that already exist in the base payload, but cannot invent evidence
    objects or downgrade a pending human-review decision.
    """

    validate_compact_solution_dict(compact_payload)
    merged = deepcopy(base_payload)
    if merged.get("case_id") != compact_payload["case_id"]:
        raise ValueError(
            "compact response case_id does not match the deterministic Agent response"
        )

    merged["executive_summary"] = compact_payload["executive_summary"]
    merged["recommendation"] = list(compact_payload["recommendation"])
    merged["clarifying_questions"] = list(compact_payload["clarifying_questions"])

    existing_risks = list(merged.get("risks", []))
    for risk_text in compact_payload["risk_flags"]:
        if not any(
            isinstance(item, dict) and item.get("description") == risk_text
            for item in existing_risks
        ):
            existing_risks.append(
                {
                    "category": "model_flag",
                    "description": risk_text,
                    "severity": "medium",
                    "action": "人工复核",
                }
            )
    merged["risks"] = existing_risks

    evidence_by_id = {
        item.get("evidence_id"): item
        for item in merged.get("evidence", [])
        if isinstance(item, dict) and item.get("evidence_id")
    }
    unknown_ids = [
        evidence_id
        for evidence_id in compact_payload["evidence_ids"]
        if evidence_id not in evidence_by_id
    ]
    if unknown_ids:
        merged["risks"].append(
            {
                "category": "evidence_binding",
                "description": "模型引用了当前检索结果中不存在的 evidence_id："
                + ", ".join(unknown_ids),
                "severity": "high",
                "action": "丢弃未知引用并人工复核",
            }
        )
    else:
        merged["evidence"] = [
            evidence_by_id[evidence_id]
            for evidence_id in compact_payload["evidence_ids"]
        ]

    base_status = merged.get("review_status", "pending")
    compact_status = compact_payload["review_status"]
    if base_status == "pending" or compact_status == "pending":
        merged["review_status"] = "pending"
    else:
        merged["review_status"] = compact_status

    validate_solution_dict(merged, require_all_fields=True)
    return merged
