#!/usr/bin/env python3
"""Run a registered v2 case through the Live API or Dify comparison adapter."""

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

from ai_presales_copilot.demo_replay import load_demo_scenarios
from ai_presales_copilot.dify_client import DifyClient, DifyClientError
from ai_presales_copilot.schemas import CustomerInputV2

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-id", default="demo-normal-001")
    parser.add_argument("--mode", choices=("api", "dify"), default="api")
    parser.add_argument("--api-url", default=os.getenv("PRESALES_API_URL", "http://127.0.0.1:8090"))
    parser.add_argument("--token", default=os.getenv("PRESALES_API_TOKEN", "dev-token"))
    parser.add_argument("--tenant", default=os.getenv("PRESALES_TENANT_ID", "local"))
    parser.add_argument("--user", default=os.getenv("PRESALES_USER_ID", "demo-user"))
    parser.add_argument("--project", default=os.getenv("PRESALES_PROJECT_ID", "demo"))
    parser.add_argument("--roles", default=os.getenv("PRESALES_ROLES", "presales"))
    parser.add_argument("--review", choices=("none", "approve", "reject"), default="none")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    scenarios = load_demo_scenarios(ROOT / "data/demo/scenarios.json")
    scenario = next((item for item in scenarios.values() if item.brief.case_id == args.case_id), None)
    if scenario is None:
        print(f"unknown registered case_id: {args.case_id}", file=sys.stderr)
        return 2
    customer_input = CustomerInputV2(raw_request=scenario.brief.raw_request, source="other")

    try:
        if args.mode == "api":
            state = _run_api(args, customer_input)
        elif args.mode == "dify":
            state = DifyClient().chat(customer_input).model_dump(mode="json")
    except (DifyClientError, RuntimeError, urllib.error.URLError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 3

    if args.as_json:
        print(json.dumps(state, ensure_ascii=False, indent=2))
        return 0
    _print_result(customer_input, state, args.mode)
    return 0


def _run_api(args: argparse.Namespace, customer_input: CustomerInputV2) -> dict[str, Any]:
    base_url = str(args.api_url).rstrip("/")
    project_id = str(args.project)
    state = _api_request(
        "POST",
        f"{base_url}/v2/projects/{project_id}/runs",
        {"input": customer_input.model_dump(mode="json")},
        token=str(args.token),
        tenant=str(args.tenant),
        user=str(args.user),
        roles=str(args.roles),
        idempotency_key=f"cli-run-{uuid.uuid4().hex}",
        project_id=project_id,
    )
    if args.review != "none" and state.get("status") == "waiting_for_review":
        state = _api_request(
            "POST",
            f"{base_url}/v2/runs/{state['run_id']}/reviews",
            {"decision": args.review, "reason": "CLI reviewer decision", "state_version": state["state_version"]},
            token=str(args.token),
            tenant=str(args.tenant),
            user=f"{args.user}-reviewer",
            roles="reviewer",
            idempotency_key=f"cli-review-{uuid.uuid4().hex}",
            project_id=project_id,
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
    project_id: str,
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
            "X-Project-ID": project_id,
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=float(os.getenv("PRESALES_API_TIMEOUT_S", "30"))) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1_000]
        raise RuntimeError(f"v2 API HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"v2 API request failed: {exc}") from exc
    if not isinstance(body, dict):
        raise TypeError("v2 API returned a non-object JSON response")
    return body


def _print_result(customer_input: CustomerInputV2, state: dict[str, Any], mode: str) -> None:
    response = state.get("response") if isinstance(state.get("response"), dict) else state
    print(f"输入：{customer_input.raw_request[:120]}")
    print(f"模式：{mode} | 状态：{state.get('status', 'response')}")
    if state.get("run_id"):
        print(f"run_id：{state['run_id']}")
    if state.get("error_code"):
        print(f"错误：{state['error_code']}")
    if response.get("executive_summary"):
        print(f"\n摘要\n{response['executive_summary']}")
    recommendations = response.get("recommendations", [])
    if recommendations:
        print("\n建议\n" + "\n".join(f"- {item}" for item in recommendations))
    risks = response.get("risks", [])
    if risks:
        print("\n风险\n" + "\n".join(f"- [{item.get('severity', 'unknown')}] {item.get('description', '')}" for item in risks))
    if response.get("clarifying_questions"):
        print("\n待确认\n" + "\n".join(f"- {item}" for item in response["clarifying_questions"]))
    if response.get("evidence"):
        print("\n证据\n" + "\n".join(f"- {item.get('evidence_id')} {item.get('title')}: {item.get('excerpt')}" for item in response["evidence"]))


if __name__ == "__main__":
    raise SystemExit(main())
