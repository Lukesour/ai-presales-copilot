#!/usr/bin/env python3
"""Optional Gradio UI for the Dify or offline presales assistant."""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from ai_presales_copilot.agent import PresalesAgent
from ai_presales_copilot.dify_client import DifyClient, DifyClientError
from ai_presales_copilot.evaluation import load_cases
from ai_presales_copilot.knowledge import KnowledgeBase
from ai_presales_copilot.offline_engine import OfflineSolutionEngine
from ai_presales_copilot.persistence import CheckpointStore
from ai_presales_copilot.schemas import CustomerBriefV2

ROOT = Path(__file__).resolve().parents[1]


def _format_markdown(response) -> str:
    if isinstance(response, dict) and response.get("schema_version") == "2.0":
        lines = [
            f"### 方案摘要\n{response.get('executive_summary', '暂无方案输出')}",
            f"\n**审核状态：** `{response.get('review', {}).get('status', 'unknown')}`",
        ]
        if response.get("recommendations"):
            lines.append("\n### 建议\n" + "\n".join(f"- {item}" for item in response["recommendations"]))
        if response.get("risks"):
            lines.append(
                "\n### 风险\n"
                + "\n".join(
                    f"- **{item.get('severity')}** {item.get('description')}（{item.get('action')}）"
                    for item in response["risks"]
                )
            )
        if response.get("clarifying_questions"):
            lines.append("\n### 待确认问题\n" + "\n".join(f"- {item}" for item in response["clarifying_questions"]))
        if response.get("evidence"):
            lines.append(
                "\n### 证据\n"
                + "\n".join(
                    f"- `{item.get('evidence_id')}` {item.get('title')}：{item.get('excerpt')}"
                    for item in response["evidence"]
                )
            )
        return "\n".join(lines)
    lines = [
        f"### 方案摘要\n{response.executive_summary}",
        f"\n**模型模式：** `{response.model_name}`",
        f"\n**审核状态：** `{response.review_status}`",
    ]
    if response.recommendation:
        lines.append("\n### 建议\n" + "\n".join(f"- {item}" for item in response.recommendation))
    if response.risks:
        lines.append(
            "\n### 风险\n"
            + "\n".join(
                f"- **{item.severity}** {item.description}（{item.action}）"
                for item in response.risks
            )
        )
    if response.clarifying_questions:
        lines.append(
            "\n### 待确认问题\n" + "\n".join(f"- {item}" for item in response.clarifying_questions)
        )
    if response.evidence:
        lines.append(
            "\n### 证据\n"
            + "\n".join(
                f"- `{item.evidence_id}` {item.title}：{item.excerpt}" for item in response.evidence
            )
        )
    if response.poc_plan:
        lines.append(
            "\n### POC 计划\n"
            + "\n".join(
                f"- **{item['phase']}**：{item['objective']}；退出标准：{item['exit_criteria']}"
                for item in response.poc_plan
            )
        )
    if response.model_strategy:
        strategy = response.model_strategy
        lines.append(
            "\n### 模型策略\n"
            f"- 首选服务路径：`{strategy.get('primary_serving_path', '待验证')}`\n"
            f"- RAG：{strategy.get('retrieval_strategy', '待验证')}\n"
            f"- 微调：{strategy.get('fine_tuning_strategy', '待验证')}"
        )
    return "\n".join(lines)


def build_app(mode: str):
    try:
        import gradio as gr
    except ImportError as exc:
        raise SystemExit(
            "Install the optional UI dependency with: python3 -m pip install -e '.[demo]'"
        ) from exc

    cases = {case.case_id: case for case in load_cases(ROOT / "data/evaluation/cases.jsonl")}
    engine = OfflineSolutionEngine(KnowledgeBase(ROOT / "data/knowledge"))
    dify = DifyClient()
    agent_store = CheckpointStore(ROOT / ".runtime/agent/gradio-checkpoints.db") if mode == "agent" else None
    agent = PresalesAgent(KnowledgeBase(ROOT / "data/knowledge"), agent_store) if mode == "agent" else None
    api_url = os.getenv("PRESALES_API_URL", "http://127.0.0.1:8090").rstrip("/")
    api_token = os.getenv("PRESALES_API_TOKEN", os.getenv("PRESALES_DEV_TOKEN", "dev-token"))
    api_runs: dict[str, str] = {}

    def analyze(case_id: str):
        brief = cases[case_id]
        try:
            if mode == "agent":
                state = agent.run(brief, thread_id=f"gradio:{case_id}")  # type: ignore[union-attr]
                if state.response is None:
                    return f"### Agent 状态\n`{state.status}`", state.to_dict()
                return _format_markdown(state.response), state.to_dict()
            if mode == "api":
                state = _api_request(
                    "POST",
                    f"{api_url}/v1/projects/gradio/runs",
                    {"brief": CustomerBriefV2.from_legacy(brief).model_dump(mode="json")},
                    token=api_token,
                    roles="presales",
                    idempotency_key=f"gradio-{uuid.uuid4().hex}",
                )
                api_runs[case_id] = state["run_id"]
                return _format_markdown(state.get("response") or state), state
            response = engine.analyze(brief) if mode == "mock" else dify.chat(brief)
            return _format_markdown(response), response.to_dict()
        except DifyClientError as exc:
            return f"### 调用失败\n`{exc}`", {"error": str(exc)}

    def review(case_id: str, decision: str):
        if mode == "api":
            run_id = api_runs.get(case_id)
            if not run_id:
                return "### 审核\n请先生成方案。", {"status": "not_found"}
            try:
                state = _api_request(
                    "POST",
                    f"{api_url}/v1/runs/{run_id}/reviews",
                    {"decision": decision, "reason": "Gradio reviewer decision"},
                    token=api_token,
                    roles="reviewer",
                    idempotency_key=f"gradio-review-{uuid.uuid4().hex}",
                )
                return _format_markdown(state.get("response") or state), state
            except RuntimeError as exc:
                return f"### 审核失败\n`{exc}`", {"error": str(exc)}
        if mode != "agent":
            return "### 审核\n只有 `api` 或旧 `agent` 模式启用人工审核恢复。", {"status": "not_applicable"}
        try:
            state = agent.run(  # type: ignore[union-attr]
                thread_id=f"gradio:{case_id}", review_decision=decision
            )
            if state.response is None:
                return f"### Agent 状态\n`{state.status}`", state.to_dict()
            return _format_markdown(state.response), state.to_dict()
        except (ValueError, RuntimeError) as exc:
            return f"### 审核失败\n`{exc}`", {"error": str(exc)}

    with gr.Blocks(title="AI Presales Copilot") as app:
        gr.Markdown("# AI Presales Copilot\n把客户需求转成可审计的技术方案、POC 和模型部署建议。")
        case_id = gr.Dropdown(choices=list(cases), value="case-001", label="客户案例")
        run = gr.Button("生成方案", variant="primary")
        with gr.Row():
            approve = gr.Button("人工审核通过")
            reject = gr.Button("人工审核拒绝")
        markdown = gr.Markdown()
        raw = gr.JSON(label="结构化响应")
        run.click(analyze, inputs=case_id, outputs=[markdown, raw])
        approve.click(lambda selected: review(selected, "approve"), inputs=case_id, outputs=[markdown, raw])
        reject.click(lambda selected: review(selected, "reject"), inputs=case_id, outputs=[markdown, raw])
    return app


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("api",),
        default="api",
        help="正式演示只通过 Phase 1 FastAPI；旧 mock/Dify/agent 路径仅供测试代码调用。",
    )
    parser.add_argument(
        "--share", action="store_true", help="Ask Gradio to create a temporary share link"
    )
    args = parser.parse_args()
    build_app(args.mode).launch(share=args.share)
    return 0


def _api_request(
    method: str,
    url: str,
    payload: dict,
    *,
    token: str,
    roles: str,
    idempotency_key: str,
) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Idempotency-Key": idempotency_key,
            "X-Roles": roles,
            "X-Tenant-ID": "local",
            "X-User-ID": "gradio",
            "X-Project-ID": "gradio",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"API HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"API request failed: {exc}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
