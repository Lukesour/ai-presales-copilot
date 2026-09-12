#!/usr/bin/env python3
"""Capture redacted replay snapshots from the formal FastAPI service."""

from __future__ import annotations

import argparse
import copy
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from ai_presales_copilot.demo_controller import api_request, fetch_events
from ai_presales_copilot.demo_replay import (
    ReplayProvenance,
    ReplaySnapshot,
    ReplayStates,
    load_demo_scenarios,
    normalize_live_events,
    registered_replay_path,
)

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default=os.getenv("PRESALES_API_URL", "http://127.0.0.1:8090"))
    parser.add_argument("--token", default=os.getenv("PRESALES_API_TOKEN", "dev-token"))
    parser.add_argument("--scenarios", default=str(ROOT / "data/demo/scenarios.json"))
    parser.add_argument("--output-dir", default=str(ROOT / "data/demo/replays"))
    parser.add_argument("--git-revision", default=os.getenv("GIT_COMMIT", ""))
    parser.add_argument("--force", action="store_true", help="overwrite registered snapshots")
    args = parser.parse_args()

    api_url = str(args.api_url).rstrip("/")
    scenarios = load_demo_scenarios(args.scenarios)
    ready = api_request("GET", f"{api_url}/readyz", None, token=args.token, roles="presales")
    if ready.get("status") != "ready":
        raise RuntimeError(f"API is not ready: {json.dumps(ready, ensure_ascii=False)}")
    for scenario_id, scenario in scenarios.items():
        snapshot = _capture_scenario(api_url, args.token, scenario, args)
        path = registered_replay_path(args.output_dir, scenario_id)
        if path.exists() and not args.force:
            raise FileExistsError(f"{path} exists; pass --force to recapture")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(snapshot.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"captured {scenario_id}: {path}")
    return 0


def _capture_scenario(api_url: str, token: str, scenario: Any, args: argparse.Namespace) -> ReplaySnapshot:
    input_payload = {
        "input": {"raw_request": scenario.brief.raw_request, "source": "meeting_notes"},
        "source": "meeting_notes",
    }
    state = api_request(
        "POST",
        f"{api_url}/v2/projects/gradio/runs",
        input_payload,
        token=token,
        roles="presales",
        idempotency_key=f"replay-capture-{scenario.scenario_id}-{uuid4().hex}",
    )
    initial = _sanitize_public_state(state, scenario.scenario_id, "initial", scenario.brief.case_id)
    clarified = None
    confirmed = None
    if state.get("status") == "needs_clarification":
        answer = _clarification_answer(scenario.scenario_id)
        state = api_request(
            "POST",
            f"{api_url}/v2/runs/{state['run_id']}/clarifications",
            {"message": answer, "expected_state_version": state.get("state_version")},
            token=token,
            roles="presales",
            idempotency_key=f"replay-capture-clarification-{uuid4().hex}",
        )
        clarified = _sanitize_public_state(state, scenario.scenario_id, "clarified", scenario.brief.case_id)
    if state.get("status") == "ready_for_confirmation":
        state = api_request(
            "POST",
            f"{api_url}/v2/runs/{state['run_id']}/requirements/confirm",
            {
                "decision": "confirm",
                "acknowledged_warnings": (state.get("requirement_analysis") or {}).get("warning_fields", []),
                "expected_state_version": state.get("state_version"),
            },
            token=token,
            roles="presales",
            idempotency_key=f"replay-capture-confirm-{uuid4().hex}",
        )
        confirmed = _sanitize_public_state(state, scenario.scenario_id, "confirmed", scenario.brief.case_id)
    pending = (
        _sanitize_public_state(state, scenario.scenario_id, "pending", scenario.brief.case_id)
        if state.get("status") == "waiting_for_review"
        else None
    )
    if pending is not None:
        state = api_request(
            "POST",
            f"{api_url}/v2/runs/{state['run_id']}/reviews",
            {"decision": "approve", "reason": "Capture synthetic demo replay after review", "state_version": state.get("state_version")},
            token=token,
            roles="reviewer",
            idempotency_key=f"replay-capture-review-{uuid4().hex}",
        )
    final = _sanitize_public_state(state, scenario.scenario_id, "final", scenario.brief.case_id)
    if final.get("response") is None:
        final["response"] = _blocked_response(scenario.brief.case_id, final)
    events = normalize_live_events(fetch_events(api_url, token, state.get("run_id")))
    response = final.get("response") or {}
    provenance = response.get("provenance") or {}
    snapshot = ReplaySnapshot(
        scenario_id=scenario.scenario_id,
        label=scenario.label,
        case_id=scenario.brief.case_id,
        captured_at=datetime.now(UTC).isoformat(),
        provenance=ReplayProvenance(
            git_revision=str(args.git_revision or _git_revision()),
            model_name=str(provenance.get("model_name") or "unknown"),
            model_hash=provenance.get("model_hash"),
            prompt_version=str(provenance.get("prompt_version") or "unknown"),
            knowledge_snapshot_id=str(provenance.get("knowledge_snapshot_id") or "unknown"),
        ),
        initial_input=initial.get("input"),
        input_turns=initial.get("input_turns", []),
        events=events,
        states=ReplayStates(initial=initial, clarified=clarified, confirmed=confirmed, pending=pending, final=final),
    )
    return snapshot


def _sanitize_public_state(
    state: dict[str, Any], scenario_id: str, phase: str, scenario_case_id: str
) -> dict[str, Any]:
    """Replace runtime identities before a public demo artifact is written."""

    sanitized = copy.deepcopy(state)
    run_id = f"replay-{scenario_id}-run"
    trace_id = f"replay-{scenario_id}-trace"
    sanitized.update(
        {
            "run_id": run_id,
            "trace_id": trace_id,
            "thread_id": f"replay:{scenario_id}",
            "tenant_id": "demo",
            "project_id": "demo",
        }
    )
    for key in ("brief", "intake_brief"):
        if isinstance(sanitized.get(key), dict):
            sanitized[key]["case_id"] = scenario_case_id
    if isinstance(sanitized.get("response"), dict):
        sanitized["response"]["case_id"] = scenario_case_id
    review = sanitized.get("review")
    if isinstance(review, dict):
        review["reviewer_id"] = "demo-reviewer" if review.get("reviewer_id") else None
        review["idempotency_key"] = "demo-replay-review" if review.get("idempotency_key") else None
    response = sanitized.get("response")
    if isinstance(response, dict):
        response_review = response.get("review")
        if isinstance(response_review, dict):
            response_review["reviewer_id"] = "demo-reviewer" if response_review.get("reviewer_id") else None
            response_review["idempotency_key"] = "demo-replay-review" if response_review.get("idempotency_key") else None
        provenance = response.get("provenance")
        if isinstance(provenance, dict):
            provenance.update({"run_id": run_id, "trace_id": trace_id, "thread_id": f"replay:{scenario_id}"})
    if phase == "pending" and isinstance(sanitized.get("review"), dict):
        sanitized["review"]["reviewer_id"] = None
        sanitized["review"]["idempotency_key"] = None
    return sanitized


def _clarification_answer(scenario_id: str) -> str:
    answers = {
        "normal": "资料是维修手册和历史工单，目标用户是维修工程师；部署使用公有云 API，峰值并发5，完整答案10秒内，数据驻留中国境内并允许出域，验收要求关键问题可引用来源。",
        "missing_then_clarified": "资料是维修手册和历史工单，目标用户是维修工程师；部署在企业内网，峰值并发20，完整答案5秒内，数据驻留中国境内且不能出域，答案必须可引用，目标是减少维修人员查找资料时间。",
        "high_risk": "资料是维修手册和历史工单，目标用户是维修工程师；部署在私有化内网，峰值并发5，完整答案10秒内，数据不能出域并要求保留访问和审核审计，验收以数据边界和审计记录为准。",
    }
    return answers.get(scenario_id, "请补充部署、数据边界、容量和可测量的验收标准。")


def _blocked_response(case_id: str, state: dict[str, Any]) -> dict[str, Any]:
    """Give a blocked Replay a safe, schema-valid explanation instead of a solution."""

    return {
        "schema_version": "2.0",
        "case_id": case_id,
        "executive_summary": "输入被安全策略阻断，未进入检索或方案生成。",
        "requirements": [], "claims": [], "recommendations": [], "architecture": [],
        "implementation_steps": [],
        "risks": [{"category": "输入安全", "description": "提示注入或冲突边界不能作为方案事实。", "severity": "high", "action": "人工核验并脱敏后重新提交"}],
        "clarifying_questions": ["请提供不含提示注入且边界一致的客户需求。"],
        "evidence": [], "poc_plan": [], "model_strategy": {}, "assumptions": [],
        "review": {"required": False, "status": "not_required"},
        "provenance": {
            "run_id": state.get("run_id", "replay-blocked-run"),
            "trace_id": state.get("trace_id", "replay-blocked-trace"),
            "thread_id": state.get("thread_id", "replay:blocked"),
            "model_name": "requirements-first-policy",
            "prompt_version": "v2-requirements-first-replay",
            "knowledge_snapshot_id": "repository-knowledge-v1",
            "generated_at": datetime.now(UTC).isoformat(),
        },
        "quality": {"parse_pass": True, "schema_pass": True, "evidence_coverage": 0.0},
    }


def _git_revision() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True, timeout=2
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


if __name__ == "__main__":
    raise SystemExit(main())
