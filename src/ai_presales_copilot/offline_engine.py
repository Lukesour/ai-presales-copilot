"""Deterministic solution engine for smoke tests, demos without keys, and CI."""

from __future__ import annotations

from .knowledge import KnowledgeBase
from .model_advisor import recommend_model_strategy
from .poc import build_poc_plan
from .schemas import CustomerBrief, Evidence, Requirement, RiskFlag, SolutionResponse


class OfflineSolutionEngine:
    """Turn a brief into a conservative, evidence-aware portfolio response."""

    def __init__(self, knowledge_base: KnowledgeBase):
        self.knowledge_base = knowledge_base

    def analyze(self, brief: CustomerBrief) -> SolutionResponse:
        query = " ".join(
            [
                brief.industry,
                brief.use_case,
                " ".join(brief.data_types),
                brief.deployment,
                brief.concurrency,
                brief.latency_requirement,
                " ".join(brief.compliance),
            ]
        )
        evidence = self.knowledge_base.search(query, top_k=3)
        requirements = self._requirements(brief)
        risks = self._risks(brief, evidence)
        questions = self._questions(brief, evidence)
        model_strategy = recommend_model_strategy(brief)
        poc_plan = build_poc_plan(brief, evidence, model_strategy)
        assumptions = [
            "本次离线分析使用合成客户案例和版本化知识资料。",
            "容量、价格、SLA、准确率和合规结论都需要在客户侧复核。",
        ]
        if not evidence:
            return SolutionResponse(
                case_id=brief.case_id,
                executive_summary="资料不足：当前资料库没有足够证据支持具体产品承诺，建议先补充资料和澄清需求。",
                requirements=requirements,
                risks=risks,
                clarifying_questions=questions or ["请补充目标并发量、部署边界和可接受响应时间。"],
                evidence=[],
                poc_plan=poc_plan,
                model_strategy=model_strategy,
                assumptions=assumptions,
                review_status="pending" if risks else "not_required",
                model_name="offline-rules",
            )

        recommendation = [
            "优先采用知识库检索结合大模型生成，所有产品能力结论绑定证据。",
            "先以 PoC 验证核心问答和方案输出，再根据并发量决定 API 或私有化部署。",
        ]
        if brief.deployment in {"私有化", "本地", "内网"}:
            recommendation.append("私有化场景优先评估本地推理服务、数据隔离和运维成本。")
        architecture = [
            "客户需求表单/接口",
            "需求结构化与约束校验",
            "产品知识库检索与证据召回",
            "方案生成与引用校验",
            "风险审核、追问和结果输出",
        ]
        steps = [
            "整理产品资料并建立版本化知识库",
            "用黄金问题集验证召回和答案依据",
            "接入 API 或本地模型并记录延迟、Token 和错误率",
            "根据真实反馈迭代资料、提示词和审核规则",
        ]
        return SolutionResponse(
            case_id=brief.case_id,
            executive_summary=f"针对{brief.industry}{brief.use_case}，建议先以证据驱动的 RAG 方案完成可控 PoC，再根据部署和性能约束确定模型服务形态。",
            requirements=requirements,
            recommendation=recommendation,
            architecture=architecture,
            implementation_steps=steps,
            risks=risks,
            clarifying_questions=questions,
            evidence=evidence,
            poc_plan=poc_plan,
            model_strategy=model_strategy,
            assumptions=assumptions,
            review_status="pending" if any(r.severity == "high" for r in risks) else "not_required",
            model_name="offline-rules",
        )

    @staticmethod
    def _requirements(brief: CustomerBrief) -> list[Requirement]:
        requirements = [
            Requirement("行业", brief.industry, "must"),
            Requirement("业务场景", brief.use_case, "must"),
            Requirement(
                "部署方式", brief.deployment, "must" if brief.deployment != "未说明" else "should"
            ),
            Requirement("并发量", brief.concurrency),
            Requirement("时延要求", brief.latency_requirement),
        ]
        if brief.data_types:
            requirements.append(Requirement("数据类型", "、".join(brief.data_types), "must"))
        if brief.compliance:
            requirements.append(Requirement("合规要求", "、".join(brief.compliance), "must"))
        return requirements

    @staticmethod
    def _risks(brief: CustomerBrief, evidence: list[Evidence]) -> list[RiskFlag]:
        risks: list[RiskFlag] = []
        if brief.deployment == "未说明":
            risks.append(
                RiskFlag(
                    "部署边界", "尚未确认公有云、私有化或内网部署", "high", "确认数据是否允许出域"
                )
            )
        if brief.concurrency == "未说明":
            risks.append(
                RiskFlag(
                    "性能容量", "缺少并发量，无法承诺吞吐和容量", "medium", "补充峰值并发和日请求量"
                )
            )
        if brief.compliance:
            risks.append(
                RiskFlag(
                    "合规",
                    "合规要求需要结合实际部署、日志和权限方案核验",
                    "high",
                    "由安全/法务确认承诺边界",
                )
            )
        if not evidence:
            risks.append(
                RiskFlag(
                    "知识覆盖", "资料库未召回相关证据", "high", "补充产品资料或拒绝给出具体结论"
                )
            )
        return risks

    @staticmethod
    def _questions(brief: CustomerBrief, evidence: list[Evidence]) -> list[str]:
        questions: list[str] = []
        if brief.deployment == "未说明":
            questions.append("数据是否允许发送到公有云 API？是否必须部署在客户内网？")
        if brief.concurrency == "未说明":
            questions.append("峰值并发、日请求量和上下文长度分别是多少？")
        if brief.latency_requirement == "未说明":
            questions.append("客户关注首 Token 延迟还是完整答案延迟？目标指标是多少？")
        if not evidence:
            questions.append("是否有现有产品白皮书、接口文档或安全规范可纳入知识库？")
        return questions
