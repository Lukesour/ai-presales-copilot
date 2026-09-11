"""Pure presentation projections shared by Live API and Demo Replay."""

from __future__ import annotations

import html
from collections.abc import Mapping
from typing import Any

SOLUTION_V2_FIELDS = (
    "schema_version",
    "case_id",
    "executive_summary",
    "requirements",
    "claims",
    "recommendations",
    "architecture",
    "implementation_steps",
    "risks",
    "clarifying_questions",
    "evidence",
    "poc_plan",
    "model_strategy",
    "assumptions",
    "review",
    "provenance",
    "quality",
)
WORKFLOW_NODES = (
    "intake",
    "clarify",
    "query_rewrite",
    "retrieve",
    "draft",
    "ground_claims",
    "critic",
    "repair",
    "risk_gate",
    "human_review",
    "finalize",
)
_STATUS_LABELS = {
    "complete": "已完成",
    "running": "运行中",
    "waiting_for_review": "等待审核",
    "rejected": "已拒绝",
    "model_unavailable": "模型不可用",
    "failed": "失败",
}


def build_solution_view(
    response: Mapping[str, Any] | None,
    *,
    clarify: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build all UI projections without importing Gradio or performing I/O."""

    payload = dict(response or {})
    merged_questions = list(payload.get("clarifying_questions") or [])
    if clarify:
        merged_questions.extend(str(item) for item in clarify.get("questions") or [])
    payload["clarifying_questions"] = list(dict.fromkeys(merged_questions))
    if "recommendations" not in payload and "recommendation" in payload:
        payload["recommendations"] = payload.get("recommendation") or []
    if "review" not in payload and "review_status" in payload:
        payload["review"] = {"status": payload.get("review_status")}
    requirements = payload.get("requirements") or []
    risks = payload.get("risks") or []
    poc_plan = payload.get("poc_plan") or []
    return {
        "summary_markdown": _summary_markdown(payload),
        "requirements_rows": [
            {
                "name": _safe(item.get("name")),
                "value": _safe(item.get("value")),
                "priority": _safe(item.get("priority")),
                "source": _safe(item.get("source")),
            }
            for item in requirements
            if isinstance(item, Mapping)
        ],
        "recommendations_markdown": _bullets(payload.get("recommendations")),
        "architecture_markdown": _bullets(payload.get("architecture")),
        "implementation_markdown": _bullets(payload.get("implementation_steps")),
        "poc_rows": [
            {
                "phase": _safe(item.get("phase")),
                "objective": _safe(item.get("objective")),
                "activities": _join(item.get("activities")),
                "deliverables": _join(item.get("deliverables")),
                "exit_criteria": _safe(item.get("exit_criteria")),
            }
            for item in poc_plan
            if isinstance(item, Mapping)
        ],
        "model_strategy": payload.get("model_strategy") or {},
        "assumptions_markdown": _bullets(payload.get("assumptions")),
        "clarifications_markdown": _bullets(payload["clarifying_questions"]),
        "risk_rows": [
            {
                "category": _safe(item.get("category")),
                "severity": _safe(item.get("severity")),
                "description": _safe(item.get("description")),
                "action": _safe(item.get("action")),
            }
            for item in risks
            if isinstance(item, Mapping)
        ],
        "review": payload.get("review") or {},
        "provenance": payload.get("provenance") or {},
        "quality": payload.get("quality") or {},
        "claims": payload.get("claims") or [],
        "evidence": payload.get("evidence") or [],
        "raw_response": payload,
        "visible_fields": {field: field in payload for field in SOLUTION_V2_FIELDS},
    }


def build_claim_evidence_rows(response: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Flatten one-to-many claim references while retaining source metadata."""

    payload = response or {}
    evidence_by_id = {
        item.get("evidence_id"): item
        for item in payload.get("evidence") or []
        if isinstance(item, Mapping) and item.get("evidence_id")
    }
    rows: list[dict[str, Any]] = []
    for claim in payload.get("claims") or []:
        if not isinstance(claim, Mapping):
            continue
        references = list(claim.get("evidence_ids") or []) or [None]
        for evidence_id in references:
            evidence = evidence_by_id.get(evidence_id) if evidence_id else None
            rows.append(
                {
                    "claim_id": _safe(claim.get("claim_id")),
                    "claim": _safe(claim.get("text")),
                    "type": _safe(claim.get("claim_type")),
                    "support_status": _safe(claim.get("support_status")),
                    "evidence_id": _safe(evidence_id) if evidence_id else "—",
                    "source": _safe((evidence or {}).get("title")) if evidence else "—",
                    "version": _safe((evidence or {}).get("version")) if evidence else "—",
                    "page": (evidence or {}).get("page") if evidence else "—",
                    "locator": _safe((evidence or {}).get("locator")) if evidence else "—",
                    "content_hash": _safe((evidence or {}).get("content_hash")) if evidence else "—",
                    "excerpt": _safe((evidence or {}).get("excerpt")) if evidence else "—",
                }
            )
    return rows


def build_evidence_rows(response: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Project evidence metadata for an expandable, non-HTML table."""

    return [
        {
            "evidence_id": _safe(item.get("evidence_id")),
            "title": _safe(item.get("title")),
            "version": _safe(item.get("version")),
            "page": item.get("page") or "—",
            "locator": _safe(item.get("locator")) or "—",
            "content_hash": _safe(item.get("content_hash")),
            "excerpt": _safe(item.get("excerpt")),
        }
        for item in (response or {}).get("evidence") or []
        if isinstance(item, Mapping)
    ]


def build_timeline_rows(
    events: list[Mapping[str, Any]] | None,
    *,
    current_node: str | None = None,
    current_status: str | None = None,
) -> list[dict[str, Any]]:
    """Combine persistent start/finish events into a fixed eleven-node timeline."""

    rows = {
        node: {
            "node": node,
            "status": "未执行",
            "event": "—",
            "node_latency_ms": "—",
            "state_version": "—",
            "description": "",
        }
        for node in WORKFLOW_NODES
    }
    for event in events or []:
        node = event.get("node")
        event_type = str(event.get("event_type", ""))
        if node not in rows and event_type.startswith("review_"):
            node = "human_review"
        if node not in rows:
            continue
        row = rows[node]
        row["event"] = _event_label(event_type)
        status = event.get("status")
        if event_type == "review_requested":
            row["status"] = "等待审核"
        elif event_type == "review_approved":
            row["status"] = "已通过"
        elif event_type == "review_rejected":
            row["status"] = "已拒绝"
        elif event_type in {"node_finished", "run_finished"}:
            row["status"] = "已完成"
        elif status in _STATUS_LABELS:
            row["status"] = _STATUS_LABELS[status]
        elif event_type == "node_started":
            row["status"] = "运行中"
        if event.get("node_latency_ms") is not None:
            row["node_latency_ms"] = event["node_latency_ms"]
        if event.get("state_version") is not None:
            row["state_version"] = event["state_version"]
        details = event.get("details")
        if isinstance(details, Mapping):
            row["description"] = _safe(", ".join(f"{key}={value}" for key, value in details.items()))
    if current_node in rows and current_status:
        rows[current_node]["status"] = _STATUS_LABELS.get(current_status, current_status)
    return [rows[node] for node in WORKFLOW_NODES]


def build_readiness_view(payload: Mapping[str, Any] | None, *, error: str | None = None) -> dict[str, Any]:
    """Normalize 200/503/network-failure readiness results for the UI."""

    data = dict(payload or {})
    status = data.get("status", "unreachable" if error else "unknown")
    checks = data.get("checks") if isinstance(data.get("checks"), Mapping) else {}
    return {
        "status": status,
        "ready": status == "ready",
        "label": "Live API 就绪" if status == "ready" else "Live API 未就绪",
        "checks": dict(checks),
        "checks_rows": [{"check": key, "status": "通过" if value is True else "失败"} for key, value in checks.items()],
        "error": error,
    }


def render_mode_banner(mode: str, readiness: Mapping[str, Any] | None = None) -> str:
    if mode == "replay":
        return "### Demo Replay · 静态快照 · 非实时模型调用\n不访问 API、数据库或模型服务。"
    if readiness and not readiness.get("ready"):
        return "### Live API 未就绪\n请先启动依赖服务，或切换到 Demo Replay。"
    return "### Live API · 实时 Agent 执行\n生成前会再次校验 `/readyz`。"


def _summary_markdown(payload: Mapping[str, Any]) -> str:
    review = payload.get("review") or {}
    return (
        f"### {html.escape(str(payload.get('case_id', '方案')))}\n"
        f"**schema_version：** `{html.escape(str(payload.get('schema_version', 'unknown')))}`\n\n"
        f"{_safe(payload.get('executive_summary')) or '暂无方案输出'}\n\n"
        f"**审核状态：** `{html.escape(str(review.get('status', 'unknown')) )}`"
    )


def _bullets(values: Any) -> str:
    if not values:
        return "—"
    return "\n".join(f"- {_safe(value)}" for value in values)


def _join(values: Any) -> str:
    return "；".join(_safe(value) for value in values or []) or "—"


def _safe(value: Any) -> str:
    if value is None:
        return ""
    return html.escape(str(value), quote=False).replace("`", "\\`")


def _event_label(event_type: str) -> str:
    return {
        "node_started": "开始",
        "node_finished": "完成",
        "run_created": "创建",
        "run_finished": "完成",
        "review_requested": "请求审核",
        "review_approved": "审核通过",
        "review_rejected": "审核拒绝",
    }.get(event_type, event_type or "事件")
