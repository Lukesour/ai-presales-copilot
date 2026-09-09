"""Generate an actionable, bounded proof-of-concept plan from a customer brief."""

from __future__ import annotations

from typing import Any

from .schemas import CustomerBrief, Evidence


def build_poc_plan(
    brief: CustomerBrief,
    evidence: list[Evidence],
    model_strategy: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build a four-phase POC plan with measurable exit criteria."""

    evidence_note = (
        f"使用已召回的 {len(evidence)} 个证据片段，并保留文档版本和来源位置。"
        if evidence
        else "当前没有可用证据；先补齐资料，不进入产品能力承诺。"
    )
    return [
        {
            "phase": "1-需求与数据准备",
            "objective": "确认业务目标、数据边界和可验收的黄金问题集",
            "activities": [
                f"围绕 {brief.use_case} 收集脱敏样本和代表性问题",
                "确认数据驻留、权限、日志、平均/峰值并发和首 Token/完整答案时延",
                evidence_note,
            ],
            "deliverables": ["需求基线", "数据清单", "黄金问题集 v1", "风险与假设清单"],
            "exit_criteria": "关键需求字段有明确值或被标记为待确认；测试集可复现。",
        },
        {
            "phase": "2-RAG 与 Agent 基线",
            "objective": "证明系统能检索正确资料、生成可审计方案并在高风险处停下来",
            "activities": [
                "建立带标题、版本、页码和权限标签的知识库",
                "运行需求结构化、检索、方案生成、证据校验和人工审核工作流",
                "记录每次 LLM、检索、工具调用和最终输出的 trace",
            ],
            "deliverables": ["可运行 POC", "引用证据", "Agent 运行轨迹", "基线评测报告"],
            "exit_criteria": "结构化输出可解析；高风险需求能够触发审核；无证据不产生确定性承诺。",
        },
        {
            "phase": "3-模型策略实验",
            "objective": "用数据判断 Prompt、RAG、LoRA/QLoRA 和部署形态的投入顺序",
            "activities": [
                model_strategy.get("fine_tuning_strategy", "先建立 Prompt + RAG 基线"),
                "对比 base 与 adapter 的需求抽取、风险分类、JSON 和工具参数质量",
                "按目标硬件测量 TTFT、完整答案延迟、p95、吞吐、显存/RSS 和错误率",
            ],
            "deliverables": ["训练 manifest", "adapter", "base/adapter 对比报告", "部署选型矩阵"],
            "exit_criteria": "adapter 在保留集上有可解释收益，且没有不可接受的泛化或安全回归。",
        },
        {
            "phase": "4-验收与生产建议",
            "objective": "把 POC 证据转化为客户可决策的交付路线",
            "activities": [
                "按黄金集、对抗集和峰值流量执行回归",
                "复核权限、审计、脱敏、失败恢复、人工接管和运维责任边界",
                "输出 PoC 结论、未决问题、生产化工作包和下一阶段报价输入",
            ],
            "deliverables": ["验收报告", "生产化路线图", "容量与 TCO 假设", "风险签字项"],
            "exit_criteria": "每个结论都有证据、假设或待验证动作；不把演示数据描述为生产 SLA。",
        },
    ]
