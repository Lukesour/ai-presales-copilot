#!/usr/bin/env python3
"""Requirements-first Gradio interview workbench."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from ai_presales_copilot.demo_controller import (
    confirm_requirements_session,
    decide_session,
    generate_session,
    new_session,
    refresh_session,
    render_session,
    select_mode,
    submit_clarification_session,
)
from ai_presales_copilot.demo_replay import load_demo_scenarios
from ai_presales_copilot.demo_view import build_control_state

ROOT = Path(__file__).resolve().parents[1]
SCENARIO_PATH = ROOT / "data/demo/scenarios.json"
REPLAY_DIR = ROOT / "data/demo/replays"

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

    replay_case = os.environ.get("PRESALES_REPLAY_CASE", "normal")
    if replay_case not in scenarios:
        replay_case = "normal"
    initial_session = select_mode(new_session(), "replay", replay_case, scenarios, str(REPLAY_DIR), api_url, token)

    def control_updates(session):
        controls = build_control_state(session)
        return (
            gr.update(interactive=controls["clarification_interactive"]),
            gr.update(interactive=controls["confirmation_interactive"]),
            gr.update(interactive=controls["review_interactive"]),
            gr.update(interactive=controls["review_interactive"]),
            gr.update(interactive=controls["replay_case_interactive"]),
        )

    def update(session):
        return (session, *render_session(session, scenarios), *control_updates(session))

    def on_refresh(session):
        return update(refresh_session(session, scenarios, api_url, token))

    def on_mode(selected, raw_request, session):
        current = session or new_session()
        current["raw_request"] = raw_request or current.get("raw_request", "")
        return update(select_mode(current, selected, current.get("scenario_id", replay_case), scenarios, str(REPLAY_DIR), api_url, token))

    def on_replay_case(selected_case, raw_request, session):
        current = session or new_session()
        current["raw_request"] = raw_request or current.get("raw_request", "")
        case_id = selected_case if selected_case in scenarios else replay_case
        return update(select_mode(current, "replay", case_id, scenarios, str(REPLAY_DIR), api_url, token))

    def on_analyze(selected_mode, raw_request, session):
        current = session or new_session()
        current["raw_request"] = raw_request or ""
        return update(generate_session(current, selected_mode, current.get("scenario_id", replay_case), scenarios, str(REPLAY_DIR), api_url, token))

    def on_clarify(message, session):
        return update(
            submit_clarification_session(
                session, message, scenarios, str(REPLAY_DIR), api_url, token
            )
        )

    def on_confirm(session):
        return update(
            confirm_requirements_session(
                session, scenarios, str(REPLAY_DIR), api_url, token
            )
        )

    def on_decide(decision, session):
        return update(decide_session(session, None, decision, api_url, token))

    with gr.Blocks(title="AI Presales Copilot · 需求优先工作台") as app:
        gr.Markdown(
            "# AI Presales Copilot · 需求优先工作台\n"
            "先判断客户需求是否具备做方案的条件，再进入检索、方案、POC、证据和审核。"
        )
        with gr.Row():
            mode_picker = gr.Radio(
                [("Demo Replay（默认离线）", "replay"), ("Live API", "live")],
                value="replay",
                label="运行模式",
            )
            replay_case_picker = gr.Dropdown(
                choices=list(scenarios),
                value=replay_case,
                label="Replay 场景（仅 Replay）",
                info="选择 missing_then_clarified 可演示‘提交补充信息’分支。",
            )
        raw_input = gr.Textbox(
            value=initial_session.get("raw_request", ""),
            lines=8,
            label="1. 粘贴客户原始需求 / 会议纪要",
            placeholder="例如：客户希望把维修手册和历史工单做成设备运维知识助手，回答必须可引用……",
        )
        with gr.Row():
            analyze_button = gr.Button("分析需求", variant="primary")
            refresh_button = gr.Button("刷新 readiness")
        banner = gr.Markdown()
        readiness = gr.JSON(label="/readyz 检查")
        session_state = gr.State(initial_session)

        with gr.Tab("需求优先流程"):
            gr.Markdown("### 2. 需求解析与缺口分析")
            brief = gr.JSON(label="当前需求 brief（缺失字段为 null，不使用‘未说明’判断）")
            requirement_facts = gr.Dataframe(
                headers=["字段", "名称", "提取值", "状态", "置信度", "原文引用"],
                label="字段事实与溯源",
            )
            requirement_analysis = gr.JSON(label="阻断字段 / 警告字段 / 澄清问题")
            clarifications = gr.Markdown(label="澄清问题")
            clarification_input = gr.Textbox(
                lines=5,
                label="补充信息（仅在需要澄清时使用）",
                placeholder="回答上方问题；每个 run 最多 3 个澄清回合。",
            )
            with gr.Row():
                clarify_button = gr.Button("提交补充信息", variant="primary")
                confirm_button = gr.Button("确认需求并生成方案", variant="primary")

        with gr.Tab("方案交付"):
            summary = gr.Markdown()
            requirements = gr.Dataframe(headers=["名称", "值", "优先级", "来源"], label="方案需求")
            recommendations = gr.Markdown(label="推荐建议")
            architecture = gr.Markdown(label="方案架构")
            implementation = gr.Markdown(label="实施步骤")
            poc = gr.Dataframe(headers=["阶段", "目标", "活动", "交付物", "退出标准"], label="POC 计划")
            model_strategy = gr.JSON(label="模型策略（技术附录）")
            assumptions = gr.Markdown(label="假设条件")

        with gr.Tab("Agent 时间线"):
            timeline = gr.Dataframe(
                headers=["阶段", "节点", "状态", "事件", "耗时(ms)", "state_version", "说明"],
                label="需求门与方案节点时间线",
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
            with gr.Accordion("原始 v2 状态（技术细节）", open=False):
                raw = gr.JSON(label="状态快照")

        outputs = [
            session_state, banner, readiness, raw_input, brief, requirement_facts,
            requirement_analysis, summary, requirements, recommendations, architecture,
            implementation, poc, model_strategy, assumptions, clarifications,
            claim_evidence, evidence, risks, review, timeline, metadata, raw,
            clarify_button, confirm_button, approve, reject,
            replay_case_picker,
        ]
        analyze_button.click(on_analyze, [mode_picker, raw_input, session_state], outputs)
        refresh_button.click(on_refresh, [session_state], outputs)
        mode_picker.change(on_mode, [mode_picker, raw_input, session_state], outputs)
        replay_case_picker.change(on_replay_case, [replay_case_picker, raw_input, session_state], outputs)
        clarify_button.click(on_clarify, [clarification_input, session_state], outputs)
        confirm_button.click(on_confirm, [session_state], outputs)
        approve.click(lambda session: on_decide("approve", session), [session_state], outputs)
        reject.click(lambda session: on_decide("reject", session), [session_state], outputs)
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
