#!/usr/bin/env python3
"""Gradio interview workbench for Live API and deterministic Demo Replay."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from ai_presales_copilot.demo_controller import (
    decide_session,
    format_solution_markdown,
    generate_session,
    new_session,
    refresh_session,
    render_session,
    select_mode,
    select_scenario,
)
from ai_presales_copilot.demo_replay import load_demo_scenarios

ROOT = Path(__file__).resolve().parents[1]
SCENARIO_PATH = ROOT / "data/demo/scenarios.json"
REPLAY_DIR = ROOT / "data/demo/replays"

# Compatibility export for callers that imported the original helper.
_format_markdown = format_solution_markdown


def build_app(mode: str = "api"):
    try:
        import gradio as gr
    except ImportError as exc:
        raise SystemExit("Install the optional UI dependency with: python3 -m pip install -e '.[demo]'") from exc
    if mode != "api":
        raise ValueError("the Gradio workbench only supports the formal API boundary")

    scenarios = load_demo_scenarios(SCENARIO_PATH)
    api_url = os.environ.get("PRESALES_API_URL", "http://127.0.0.1:8090").rstrip("/")
    token = os.environ.get("PRESALES_API_TOKEN", os.environ.get("PRESALES_DEV_TOKEN", "dev-token"))

    def update(session):
        return (session, *render_session(session, scenarios))

    def on_refresh(session):
        return update(refresh_session(session, scenarios, api_url, token))

    def on_mode(selected, scenario_id, session):
        return update(select_mode(session, selected, scenario_id, scenarios, str(REPLAY_DIR), api_url, token))

    def on_scenario(scenario_id, session):
        return update(select_scenario(session, scenario_id, scenarios, str(REPLAY_DIR)))

    def on_generate(selected, scenario_id, session):
        return update(generate_session(session, selected, scenario_id, scenarios, str(REPLAY_DIR), api_url, token))

    def on_decide(scenario_id, decision, session):
        return update(decide_session(session, scenario_id, decision, api_url, token))

    with gr.Blocks(title="AI Presales Copilot") as app:
        gr.Markdown("# AI Presales Copilot\n把客户需求转成可审计的技术方案、POC 和模型部署建议。")
        with gr.Row():
            mode_picker = gr.Radio(
                [("Live API", "live"), ("Demo Replay", "replay")],
                value="live",
                label="运行模式",
            )
            scenario_picker = gr.Dropdown(
                choices=[
                    (f"{item.label} · {item.scenario_id}", item.scenario_id)
                    for item in scenarios.values()
                ],
                value="normal",
                label="演示案例",
            )
        with gr.Row():
            run_button = gr.Button("生成方案", variant="primary")
            replay_button = gr.Button("加载 Replay")
            refresh_button = gr.Button("刷新 readiness")
        banner = gr.Markdown()
        readiness = gr.JSON(label="/readyz 检查")
        session_state = gr.State(new_session())

        with gr.Tabs():
            with gr.Tab("方案总览"):
                brief = gr.JSON(label="CustomerBriefV2 完整需求")
                summary = gr.Markdown()
                requirements = gr.Dataframe(headers=["名称", "值", "优先级", "来源"], label="结构化需求")
                recommendations = gr.Markdown(label="推荐建议")
                architecture = gr.Markdown(label="方案架构")
                implementation = gr.Markdown(label="实施步骤")
                poc = gr.Dataframe(headers=["阶段", "目标", "活动", "交付物", "退出标准"], label="POC 计划")
                model_strategy = gr.JSON(label="模型策略（保留全部字段）")
                assumptions = gr.Markdown(label="假设条件")
                clarifications = gr.Markdown(label="待确认问题")
            with gr.Tab("Agent 时间线"):
                timeline = gr.Dataframe(
                    headers=["节点", "状态", "事件", "耗时(ms)", "state_version", "说明"],
                    label="固定 11 节点时间线",
                )
            with gr.Tab("证据追溯"):
                claim_evidence = gr.Dataframe(
                    headers=["claim_id", "Claim", "类型", "支持状态", "evidence_id", "来源", "版本", "页码", "locator", "hash", "摘要"],
                    label="Claim — Evidence 关联",
                )
                evidence = gr.Dataframe(
                    headers=["evidence_id", "标题", "版本", "页码", "locator", "content_hash", "摘要"],
                    label="证据详情",
                )
            with gr.Tab("风险审核"):
                risks = gr.Dataframe(headers=["分类", "等级", "原因", "处理动作"], label="风险")
                review = gr.JSON(label="审核状态")
                with gr.Row():
                    approve = gr.Button("人工审核通过")
                    reject = gr.Button("人工审核拒绝")
            with gr.Tab("运行元数据"):
                metadata = gr.JSON(label="运行元数据与 Replay 边界")
                with gr.Accordion("原始 v2 响应（技术细节）", open=False):
                    raw = gr.JSON(label="结构化响应")

        outputs = [
            session_state, banner, readiness, brief, summary, requirements,
            recommendations, architecture, implementation, poc, model_strategy,
            assumptions, clarifications, claim_evidence, evidence, risks, review,
            timeline, metadata, raw,
        ]
        run_button.click(on_generate, [mode_picker, scenario_picker, session_state], outputs)
        replay_button.click(lambda scenario, session: on_mode("replay", scenario, session), [scenario_picker, session_state], outputs)
        refresh_button.click(on_refresh, [session_state], outputs)
        mode_picker.change(on_mode, [mode_picker, scenario_picker, session_state], outputs)
        scenario_picker.change(on_scenario, [scenario_picker, session_state], outputs)
        approve.click(lambda scenario, session: on_decide(scenario, "approve", session), [scenario_picker, session_state], outputs)
        reject.click(lambda scenario, session: on_decide(scenario, "reject", session), [scenario_picker, session_state], outputs)
        app.load(on_refresh, [session_state], outputs)
    return app.queue()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("api",), default="api")
    parser.add_argument("--share", action="store_true", help="Ask Gradio to create a temporary share link")
    args = parser.parse_args()
    build_app(args.mode).launch(share=args.share)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
