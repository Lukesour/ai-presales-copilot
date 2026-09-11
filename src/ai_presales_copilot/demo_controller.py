"""Session and transport controller shared by the Gradio demo surface."""

from __future__ import annotations

import copy
import html
import json
import os
import urllib.error
import urllib.request
import uuid
from collections.abc import Mapping
from typing import Any

from .demo_replay import active_replay_state, load_demo_replay
from .demo_view import (
    build_claim_evidence_rows,
    build_evidence_rows,
    build_readiness_view,
    build_solution_view,
    build_timeline_rows,
    render_mode_banner,
)

OUTPUT_KEYS = (
    "banner", "readiness", "brief", "summary", "requirements", "recommendations",
    "architecture", "implementation", "poc", "model_strategy", "assumptions",
    "clarifications", "claim_evidence", "evidence", "risks", "review", "timeline",
    "metadata", "raw",
)


class APIRequestError(RuntimeError):
    """Retain a safe HTTP payload so `/readyz` 503 details can reach the UI."""

    def __init__(self, message: str, *, status_code: int | None = None, payload: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


def new_session() -> dict[str, Any]:
    return {
        "mode": "live", "scenario_id": "normal", "run_id": None, "public_state": {},
        "events": [], "replay_states": {}, "replay_snapshot": {},
        "replay_approved": False, "readiness": None, "message": None,
    }


def render_session(session: Mapping[str, Any], scenarios: Mapping[str, Any]) -> tuple[Any, ...]:
    values = build_ui_values(session, scenarios)
    return tuple(values[key] for key in OUTPUT_KEYS)


def format_solution_markdown(response: Any) -> str:
    """Keep the original helper behavior while exposing every v2 field."""

    if hasattr(response, "model_dump"):
        payload = response.model_dump(mode="json")
    elif hasattr(response, "to_dict"):
        payload = response.to_dict()
    else:
        payload = response
    view = build_solution_view(payload if isinstance(payload, Mapping) else None)
    sections = [view["summary_markdown"]]
    for title, key in (
        ("需求", "requirements_rows"), ("建议", "recommendations_markdown"),
        ("架构", "architecture_markdown"), ("实施步骤", "implementation_markdown"),
        ("POC 计划", "poc_rows"), ("模型策略", "model_strategy"),
        ("假设条件", "assumptions_markdown"), ("待确认问题", "clarifications_markdown"),
        ("风险", "risk_rows"), ("审核", "review"), ("溯源", "provenance"),
        ("质量", "quality"),
    ):
        value = view[key]
        rendered = value if isinstance(value, str) else html.escape(
            json.dumps(value, ensure_ascii=False, indent=2), quote=False
        )
        sections.append(f"### {title}\n{rendered}")
    sections.append(
        "### Claim—Evidence\n"
        + html.escape(json.dumps(build_claim_evidence_rows(payload), ensure_ascii=False, indent=2), quote=False)
    )
    sections.append(
        "### 证据详情\n"
        + html.escape(json.dumps(build_evidence_rows(payload), ensure_ascii=False, indent=2), quote=False)
    )
    return "\n\n".join(sections)


def refresh_session(session: dict[str, Any] | None, scenarios: Mapping[str, Any], api_url: str, token: str) -> dict[str, Any]:
    current = copy.deepcopy(session or new_session())
    if current["mode"] == "replay":
        current["readiness"] = {"status": "skipped", "checks": {}, "ready": False}
        current["message"] = "Replay 不依赖 `/readyz`，当前没有发起网络检查。"
    else:
        current["readiness"] = fetch_readiness(api_url, token)
        current["message"] = None
    return current


def select_mode(session: dict[str, Any] | None, selected_mode: str, scenario_id: str, scenarios: Mapping[str, Any], replay_dir: str, api_url: str, token: str) -> dict[str, Any]:
    current = copy.deepcopy(session or new_session())
    current.update({"mode": selected_mode or "live", "scenario_id": scenario_id or "normal", "message": None})
    if current["mode"] == "replay":
        load_replay_session(current, scenarios, replay_dir)
    else:
        reset_run(current)
        current["readiness"] = fetch_readiness(api_url, token)
    return current


def select_scenario(session: dict[str, Any] | None, scenario_id: str, scenarios: Mapping[str, Any], replay_dir: str) -> dict[str, Any]:
    current = copy.deepcopy(session or new_session())
    current["scenario_id"] = scenario_id or "normal"
    current["message"] = None
    if current["mode"] == "replay":
        load_replay_session(current, scenarios, replay_dir)
    else:
        reset_run(current)
    return current


def generate_session(session: dict[str, Any] | None, selected_mode: str, scenario_id: str, scenarios: Mapping[str, Any], replay_dir: str, api_url: str, token: str) -> dict[str, Any]:
    current = copy.deepcopy(session or new_session())
    current.update({"mode": selected_mode or "live", "scenario_id": scenario_id or "normal"})
    if current["mode"] == "replay":
        load_replay_session(current, scenarios, replay_dir)
    else:
        run_live(current, scenarios, api_url, token)
    return current


def decide_session(session: dict[str, Any] | None, scenario_id: str, decision: str, api_url: str, token: str) -> dict[str, Any]:
    current = copy.deepcopy(session or new_session())
    current["scenario_id"] = scenario_id or current["scenario_id"]
    if current["mode"] == "replay":
        apply_replay_decision(current, decision)
    else:
        apply_live_decision(current, decision, api_url, token)
    return current


def load_replay_session(session: dict[str, Any], scenarios: Mapping[str, Any], replay_dir: str) -> None:
    try:
        snapshot = load_demo_replay(replay_dir, session["scenario_id"], scenarios=dict(scenarios))
        session["readiness"] = {"status": "skipped", "checks": {}, "ready": False}
        session["replay_snapshot"] = snapshot.model_dump(mode="json")
        session["replay_states"] = snapshot.states.model_dump(mode="json")
        session["public_state"] = active_replay_state(snapshot)
        session["events"] = [event.model_dump(mode="json") for event in snapshot.events]
        session["run_id"] = snapshot.states.final.get("run_id")
        session["replay_approved"] = snapshot.states.pending is None
        session["message"] = "当前为静态回放，未写入真实运行状态。"
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        session["public_state"] = {"status": "replay_invalid", "error_code": "replay_invalid"}
        session["message"] = f"Replay 加载失败：{exc}"


def build_ui_values(session: Mapping[str, Any], scenarios: Mapping[str, Any]) -> dict[str, Any]:
    scenario = scenarios[session.get("scenario_id", "normal")]
    state = session.get("public_state") or {}
    response = state.get("response") if isinstance(state, Mapping) else None
    readiness = build_readiness_view(session.get("readiness"), error=session.get("readiness_error"))
    solution = build_solution_view(response, clarify=state.get("clarify") if isinstance(state, Mapping) else None)
    banner = render_mode_banner(str(session.get("mode", "live")), readiness)
    if state.get("status"):
        banner += f"\n\n**当前状态：** `{html.escape(str(state['status']))}`"
    if session.get("message"):
        banner += f"\n\n{html.escape(str(session['message']))}"
    replay = session.get("replay_snapshot") or {}
    provenance = solution["provenance"] or replay.get("provenance", {})
    return {
        "banner": banner, "readiness": readiness, "brief": scenario.brief.model_dump(mode="json"),
        "summary": solution["summary_markdown"],
        "requirements": table_rows(solution["requirements_rows"], ("name", "value", "priority", "source")),
        "recommendations": solution["recommendations_markdown"],
        "architecture": solution["architecture_markdown"],
        "implementation": solution["implementation_markdown"],
        "poc": table_rows(solution["poc_rows"], ("phase", "objective", "activities", "deliverables", "exit_criteria")),
        "model_strategy": solution["model_strategy"], "assumptions": solution["assumptions_markdown"],
        "clarifications": solution["clarifications_markdown"],
        "claim_evidence": table_rows(build_claim_evidence_rows(response), ("claim_id", "claim", "type", "support_status", "evidence_id", "source", "version", "page", "locator", "content_hash", "excerpt")),
        "evidence": table_rows(build_evidence_rows(response), ("evidence_id", "title", "version", "page", "locator", "content_hash", "excerpt")),
        "risks": table_rows(solution["risk_rows"], ("category", "severity", "description", "action")),
        "review": solution["review"],
        "timeline": table_rows(build_timeline_rows(session.get("events"), current_node=state.get("current_node"), current_status=state.get("status")), ("node", "status", "event", "node_latency_ms", "state_version", "description")),
        "metadata": {"mode": session.get("mode"), "scenario_id": scenario.scenario_id, "run_id": state.get("run_id"), "status": state.get("status"), "state_version": state.get("state_version"), "thread_id": state.get("thread_id"), "trace_id": state.get("trace_id"), "synthetic": replay.get("synthetic", False), "captured_from": replay.get("captured_from", "live_api" if session.get("mode") == "live" else None), "provenance": provenance, "quality": solution["quality"], "visible_v2_fields": solution["visible_fields"]},
        "raw": response or {},
    }


def table_rows(rows: list[Mapping[str, Any]], columns: tuple[str, ...]) -> list[list[Any]]:
    return [[row.get(column, "") for column in columns] for row in rows]


def reset_run(session: dict[str, Any]) -> None:
    session.update({"run_id": None, "public_state": {}, "events": [], "replay_states": {}, "replay_snapshot": {}, "replay_approved": False})


def run_live(session: dict[str, Any], scenarios: Mapping[str, Any], api_url: str, token: str) -> None:
    session["readiness"] = fetch_readiness(api_url, token)
    if session["readiness"].get("status") != "ready":
        session["message"] = "Live API 未就绪，已阻止创建 run；请启动 llama-server 或切换到 Replay。"
        reset_run(session)
        return
    scenario = scenarios[session["scenario_id"]]
    try:
        state = api_request("POST", f"{api_url}/v1/projects/gradio/runs", {"brief": scenario.brief.model_dump(mode="json")}, token=token, roles="presales", idempotency_key=f"gradio-run-{uuid.uuid4().hex}")
        session.update({"public_state": state, "run_id": state.get("run_id"), "events": fetch_events(api_url, token, state.get("run_id")), "message": None})
    except APIRequestError as exc:
        session["public_state"] = {"status": "api_error", "error_code": "api_error", "errors": [str(exc)]}
        session["message"] = str(exc)


def apply_live_decision(session: dict[str, Any], decision: str, api_url: str, token: str) -> None:
    run_id = session.get("run_id")
    if not run_id:
        session["message"] = "请先生成方案。"
        return
    try:
        state = api_request("POST", f"{api_url}/v1/runs/{run_id}/reviews", {"decision": decision, "reason": "Gradio reviewer decision"}, token=token, roles="reviewer", idempotency_key=f"gradio-review-{uuid.uuid4().hex}")
        session.update({"public_state": state, "events": fetch_events(api_url, token, run_id), "message": None})
    except APIRequestError as exc:
        session["message"] = f"审核失败：{exc}"


def apply_replay_decision(session: dict[str, Any], decision: str) -> None:
    states = session.get("replay_states") or {}
    pending = states.get("pending")
    if pending is None:
        session["message"] = "当前 Replay 没有待审核状态。"
        return
    if decision == "approve":
        session["public_state"] = copy.deepcopy(states["final"])
        session["replay_approved"] = True
        session["message"] = "当前为静态回放，已切换到审核通过快照，未写入真实运行状态。"
        return
    rejected = copy.deepcopy(pending)
    rejected.update({"status": "rejected", "current_node": "done", "error_code": "review_rejected"})
    rejected["review"] = {**rejected.get("review", {}), "status": "rejected", "reviewer_id": "demo-reviewer"}
    if isinstance(rejected.get("response"), dict):
        rejected["response"]["review"] = rejected["review"]
    session["public_state"] = rejected
    session["message"] = "当前为静态回放，已展示审核拒绝分支，未写入真实运行状态。"


def fetch_readiness(api_url: str, token: str) -> dict[str, Any]:
    try:
        return api_request(
            "GET",
            f"{api_url}/readyz",
            None,
            token=token,
            roles="presales",
            timeout_s=float(os.getenv("PRESALES_READINESS_TIMEOUT_S", "3")),
        )
    except APIRequestError as exc:
        if isinstance(exc.payload, dict):
            return {**exc.payload, "http_status": exc.status_code}
        return {"status": "unreachable", "checks": {}, "http_status": exc.status_code, "error": str(exc)}


def fetch_events(api_url: str, token: str, run_id: str | None) -> list[dict[str, Any]]:
    if not run_id:
        return []
    payload = api_request("GET", f"{api_url}/v1/runs/{run_id}/events", None, token=token, roles="viewer")
    return payload.get("events", []) if isinstance(payload.get("events"), list) else []


def api_request(
    method: str,
    url: str,
    payload: dict[str, Any] | None,
    *,
    token: str,
    roles: str,
    idempotency_key: str | None = None,
    timeout_s: float | None = None,
) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json", "X-Roles": roles, "X-Tenant-ID": "local", "X-User-ID": "gradio", "X-Project-ID": "gradio"}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        timeout = timeout_s if timeout_s is not None else float(os.getenv("PRESALES_API_TIMEOUT_S", "120"))
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")[:1_000]
        try:
            detail = json.loads(raw)
        except json.JSONDecodeError:
            detail = None
        raise APIRequestError(f"API HTTP {exc.code}: {raw}", status_code=exc.code, payload=detail) from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise APIRequestError(f"API request failed: {exc}") from exc
    if not isinstance(body, dict):
        raise APIRequestError("API returned a non-object JSON response")
    return body
