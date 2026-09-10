#!/usr/bin/env python3
"""Run a case through the formal Phase 1 API.

The public/default path is the local-model FastAPI service. ``fixture`` is
kept only for offline contract regression; it is intentionally explicit so a
rules-based response cannot be mistaken for a real model run.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from ai_presales_copilot.dify_client import DifyClient, DifyClientError
from ai_presales_copilot.evaluation import load_cases
from ai_presales_copilot.knowledge import KnowledgeBase
from ai_presales_copilot.offline_engine import OfflineSolutionEngine
from ai_presales_copilot.schemas import CustomerBriefV2

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-id", default="case-001")
    parser.add_argument(
        "--mode",
        choices=("api", "dify", "fixture"),
        default="api",
        help="api is the Phase 1 path; fixture is offline test-only compatibility",
    )
    parser.add_argument("--api-url", default=os.getenv("PRESALES_API_URL", "http://127.0.0.1:8090"))
    parser.add_argument("--token", default=os.getenv("PRESALES_API_TOKEN", "dev-token"))
    parser.add_argument("--tenant", default=os.getenv("PRESALES_TENANT_ID", "local"))
    parser.add_argument("--user", default=os.getenv("PRESALES_USER_ID", "demo-user"))
    parser.add_argument("--project", default=os.getenv("PRESALES_PROJECT_ID", "demo"))
    parser.add_argument("--roles", default=os.getenv("PRESALES_ROLES", "presales"))
    parser.add_argument(
        "--review",
        choices=("none", "approve", "reject"),
        default="none",
        help="submit a reviewer decision when the API run pauses for review",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    cases = {case.case_id: case for case in load_cases(ROOT / "data/evaluation/cases.jsonl")}
    if args.case_id not in cases:
        print(f"unknown case_id: {args.case_id}", file=sys.stderr)
        return 2
    brief = cases[args.case_id]

    try:
        if args.mode == "api":
            state = _run_api(args, brief)
        elif args.mode == "fixture":
            response = OfflineSolutionEngine(KnowledgeBase(ROOT / "data/knowledge")).analyze(brief)
            state = response.to_dict()
        else:
            state = DifyClient().chat(brief).to_dict()
    except (DifyClientError, RuntimeError, urllib.error.URLError) as exc:
        print(str(exc), file=sys.stderr)
        return 3

    if args.as_json:
        print(json.dumps(state, ensure_ascii=False, indent=2))
        return 0
    _print_result(brief, state, args.mode)
    return 0


def _run_api(args: argparse.Namespace, brief: Any) -> dict[str, Any]:
    token = str(args.token)
    base_url = str(args.api_url).rstrip("/")
    run_key = f"cli-run-{uuid.uuid4().hex}"
    state = _api_request(
        "POST",
        f"{base_url}/v1/projects/{args.project}/runs",
        {"brief": CustomerBriefV2.from_legacy(brief).model_dump(mode="json")},
        token=token,
        tenant=args.tenant,
        user=args.user,
        roles=args.roles,
        idempotency_key=run_key,
        project_id=args.project,
    )
    if args.review != "none" and state.get("status") == "waiting_for_review":
        state = _api_request(
            "POST",
            f"{base_url}/v1/runs/{state['run_id']}/reviews",
            {"decision": args.review, "reason": "CLI reviewer decision"},
            token=token,
            tenant=args.tenant,
            user=f"{args.user}-reviewer",
            roles="reviewer",
            idempotency_key=f"cli-review-{uuid.uuid4().hex}",
            project_id=args.project,
        )
    return state


def _api_request(
    method: str,
    url: str,
    payload: dict[str, Any],
    *,
    token: str,
    tenant: str,
    user: str,
    roles: str,
    idempotency_key: str,
    project_id: str | None = None,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Idempotency-Key": idempotency_key,
            "X-Tenant-ID": tenant,
            "X-User-ID": user,
            "X-Roles": roles,
            "X-Project-ID": project_id or "demo",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=float(os.getenv("PRESALES_API_TIMEOUT_S", "30"))) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1_000]
        raise RuntimeError(f"Phase 1 API HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"Phase 1 API request failed: {exc}") from exc
    if not isinstance(body, dict):
        raise TypeError("Phase 1 API returned a non-object JSON response")
    return body


def _print_result(brief: Any, state: dict[str, Any], mode: str) -> None:
    response = state.get("response") if isinstance(state.get("response"), dict) else state
    print(f"案例：{brief.case_id} | {brief.industry} | {brief.use_case}")
    print(f"模式：{mode} | 状态：{state.get('status', state.get('review_status', 'unknown'))}")
    if state.get("run_id"):
        print(f"run_id：{state['run_id']}")
    if state.get("error_code"):
        print(f"错误：{state['error_code']}")
    if response.get("executive_summary"):
        print(f"\n摘要\n{response['executive_summary']}")
    recommendations = response.get("recommendations") or response.get("recommendation") or []
    if recommendations:
        print("\n建议\n" + "\n".join(f"- {item}" for item in recommendations))
    if response.get("risks"):
        print(
            "\n风险\n"
            + "\n".join(
                f"- [{item.get('severity', 'unknown')}] {item.get('description', '')}"
                for item in response["risks"]
            )
        )
    if response.get("clarifying_questions"):
        print("\n待确认\n" + "\n".join(f"- {item}" for item in response["clarifying_questions"]))
    if response.get("evidence"):
        print(
            "\n证据\n"
            + "\n".join(
                f"- {item.get('evidence_id')} {item.get('title')}: {item.get('excerpt')}"
                for item in response["evidence"]
            )
        )


if __name__ == "__main__":
    raise SystemExit(main())
