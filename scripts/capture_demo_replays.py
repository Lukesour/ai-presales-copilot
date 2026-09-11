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
    state = api_request(
        "POST",
        f"{api_url}/v1/projects/gradio/runs",
        {"brief": scenario.brief.model_dump(mode="json")},
        token=token,
        roles="presales",
        idempotency_key=f"replay-capture-{scenario.scenario_id}-{uuid4().hex}",
    )
    pending = (
        _sanitize_public_state(state, scenario.scenario_id, "pending")
        if state.get("status") == "waiting_for_review"
        else None
    )
    if pending is not None:
        state = api_request(
            "POST",
            f"{api_url}/v1/runs/{state['run_id']}/reviews",
            {"decision": "approve", "reason": "Capture synthetic demo replay after review"},
            token=token,
            roles="reviewer",
            idempotency_key=f"replay-capture-review-{uuid4().hex}",
        )
    final = _sanitize_public_state(state, scenario.scenario_id, "final")
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
        events=events,
        states=ReplayStates(pending=pending, final=final),
    )
    return snapshot


def _sanitize_public_state(state: dict[str, Any], scenario_id: str, phase: str) -> dict[str, Any]:
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


def _git_revision() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True, timeout=2
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


if __name__ == "__main__":
    raise SystemExit(main())
