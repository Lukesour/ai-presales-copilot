"""A resumable, evidence-aware presales Agent with a deterministic fallback.

The graph is intentionally explicit so an interviewer can inspect every node,
tool boundary, gate, and output.  An optional LangGraph adapter can wrap the
same node functions when the extra dependency is installed.
"""

from __future__ import annotations

import json
import uuid
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from .agent_tools import PresalesTools
from .knowledge import KnowledgeBase
from .model_advisor import recommend_model_strategy
from .observability import TraceRecorder
from .offline_engine import OfflineSolutionEngine
from .persistence import CheckpointStore
from .poc import build_poc_plan
from .schemas import (
    CustomerBrief,
    Evidence,
    Requirement,
    RiskFlag,
    SolutionResponse,
    validate_solution_dict,
)
from .security import inspect_output, inspect_sensitive_data, inspect_untrusted_input

AgentStatus = Literal["running", "pending_review", "complete", "rejected", "failed"]
_ACTIVE_TRACE: ContextVar[TraceRecorder | None] = ContextVar("active_presales_trace", default=None)


@dataclass
class AgentState:
    run_id: str
    trace_id: str
    thread_id: str
    brief: CustomerBrief
    status: AgentStatus = "running"
    current_node: str = "intake"
    requirements: list[Requirement] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    recommendation: list[str] = field(default_factory=list)
    architecture: list[str] = field(default_factory=list)
    poc_plan: list[dict[str, Any]] = field(default_factory=list)
    model_strategy: dict[str, Any] = field(default_factory=dict)
    risks: list[RiskFlag] = field(default_factory=list)
    clarifying_questions: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    review_status: str = "not_required"
    approval_reason: str = ""
    response: SolutionResponse | None = None
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> AgentState:
        response_payload = payload.get("response")
        response = _response_from_dict(response_payload) if response_payload else None
        return cls(
            run_id=payload["run_id"],
            trace_id=payload["trace_id"],
            thread_id=payload["thread_id"],
            brief=CustomerBrief(**payload["brief"]),
            status=payload.get("status", "running"),
            current_node=payload.get("current_node", "intake"),
            requirements=[Requirement(**item) for item in payload.get("requirements", [])],
            evidence=[Evidence(**item) for item in payload.get("evidence", [])],
            recommendation=payload.get("recommendation", []),
            architecture=payload.get("architecture", []),
            poc_plan=payload.get("poc_plan", []),
            model_strategy=payload.get("model_strategy", {}),
            risks=[RiskFlag(**item) for item in payload.get("risks", [])],
            clarifying_questions=payload.get("clarifying_questions", []),
            assumptions=payload.get("assumptions", []),
            review_status=payload.get("review_status", "not_required"),
            approval_reason=payload.get("approval_reason", ""),
            response=response,
            errors=payload.get("errors", []),
            metadata=payload.get("metadata", {}),
        )


class PresalesAgent:
    """Run the portfolio's explicit Agent graph and persist its checkpoints."""

    NODES = ("intake", "retrieve", "architect", "poc", "model_strategy", "risk_gate", "finalize")

    def __init__(
        self,
        knowledge_base: KnowledgeBase,
        checkpoint_store: CheckpointStore | None = None,
    ):
        self.tools = PresalesTools(knowledge_base)
        self.offline_engine = OfflineSolutionEngine(knowledge_base)
        self.checkpoints = checkpoint_store

    def run(
        self,
        brief: CustomerBrief | None = None,
        *,
        thread_id: str | None = None,
        review_decision: str | None = None,
        trace_path: str | None = None,
    ) -> AgentState:
        """Start a run or resume a checkpoint after human review."""

        resolved_thread = thread_id or (f"case:{brief.case_id}" if brief else None)
        if not resolved_thread:
            raise ValueError("brief or thread_id is required")
        state = self._load(resolved_thread)
        if state is None:
            if brief is None:
                raise ValueError(f"no checkpoint exists for thread_id={resolved_thread}")
            state = AgentState(
                run_id=str(uuid.uuid4()),
                trace_id=str(uuid.uuid4()),
                thread_id=resolved_thread,
                brief=brief,
            )
        elif brief is not None and brief.case_id != state.brief.case_id:
            raise ValueError("brief.case_id does not match the existing thread checkpoint")

        trace = TraceRecorder(state.run_id, state.trace_id)
        trace_token = _ACTIVE_TRACE.set(trace)
        try:
            trace.record("run_started", "presales_agent", data={"status": state.status})

            if state.status in {"complete", "rejected", "failed"} and review_decision is None:
                return state
            if state.status == "pending_review":
                if review_decision is None:
                    return state
                self._apply_review(state, review_decision)
                self._save(state)

            while state.current_node != "done":
                node = state.current_node
                if node not in self.NODES:
                    raise ValueError(f"unknown Agent node: {node}")
                trace.record("node_started", node, data={"thread_id": state.thread_id})
                try:
                    should_pause = getattr(self, f"_node_{node}")(state)
                except Exception as exc:  # pragma: no cover - defensive runtime boundary
                    state.status = "failed"
                    state.current_node = "done"
                    state.errors.append(f"{node}: {exc}")
                    trace.record("node_finished", node, status="error", error=str(exc))
                    self._save(state)
                    raise
                trace.record(
                    "node_finished",
                    node,
                    data={"next_node": state.current_node, "paused": bool(should_pause)},
                )
                self._save(state)
                if should_pause:
                    break
        finally:
            self._finish_trace(state, trace_path, trace)
            _ACTIVE_TRACE.reset(trace_token)
        return state

    def _node_intake(self, state: AgentState) -> bool:
        baseline = self.offline_engine.analyze(state.brief)
        state.requirements = baseline.requirements
        state.risks = baseline.risks
        state.clarifying_questions = baseline.clarifying_questions
        state.assumptions = [
            "本次分析使用合成客户案例和公开/合成知识资料。",
            "任何容量、准确率、SLA、价格和合规结论都需要客户侧复核。",
        ]
        input_policy = inspect_untrusted_input(state.brief.raw_request)
        state.metadata["input_policy"] = {
            "blocked": input_policy.blocked,
            "categories": input_policy.categories,
        }
        if input_policy.blocked:
            state.risks.append(
                RiskFlag(
                    "输入安全",
                    "客户资料触发输入安全策略（"
                    + ", ".join(input_policy.categories)
                    + "）；该内容只能作为不可信业务数据处理。",
                    "high",
                    "人工确认后再交给模型或工具",
                )
            )
            state.clarifying_questions.append("请确认输入中的指令性文本是否只是客户资料，而非系统控制指令。")
        state.current_node = "retrieve"
        return False

    def _node_retrieve(self, state: AgentState) -> bool:
        query = " ".join(
            [
                state.brief.industry,
                state.brief.use_case,
                " ".join(state.brief.data_types),
                state.brief.deployment,
                state.brief.concurrency,
                " ".join(state.brief.compliance),
            ]
        )
        state.evidence = self.tools.search_knowledge(query, top_k=4)
        evidence_validation = self.tools.validate_evidence(state.evidence)
        capacity = self.tools.estimate_capacity(state.brief)
        state.metadata["evidence_validation"] = evidence_validation
        state.metadata["capacity"] = capacity
        trace = _ACTIVE_TRACE.get()
        if trace is not None:
            trace.record(
                "tool_called",
                "search_knowledge",
                data={"top_k": 4, "evidence_count": len(state.evidence)},
            )
            trace.record("tool_called", "validate_evidence", data=evidence_validation)
            trace.record("tool_called", "estimate_capacity", data=capacity)
        state.current_node = "architect"
        return False

    def _node_architect(self, state: AgentState) -> bool:
        state.architecture = [
            "客户需求输入与身份/项目上下文",
            "需求结构化与缺失字段检测",
            "混合检索、元数据过滤与证据绑定",
            "方案架构 Agent 与 POC 计划 Agent",
            "事实/引用/安全校验与人工审核门",
            "结构化 API、审计日志和可观测性",
        ]
        state.recommendation = [
            "RAG 优先承载持续变化的产品事实；微调只承载稳定的行为和格式。",
            "Agent 使用显式状态节点和有限工具，不允许模型自由执行高风险动作。",
            "先完成可回归的 POC，再根据目标硬件和峰值流量选择云端、本地或 vLLM。",
        ]
        state.metadata["deployment_options"] = self.tools.compare_deployment_options(state.brief)
        trace = _ACTIVE_TRACE.get()
        if trace is not None:
            trace.record(
                "tool_called",
                "compare_deployment_options",
                data={"option_count": len(state.metadata["deployment_options"])},
            )
        state.current_node = "poc"
        return False

    def _node_poc(self, state: AgentState) -> bool:
        state.poc_plan = build_poc_plan(state.brief, state.evidence, state.model_strategy)
        state.current_node = "model_strategy"
        return False

    def _node_model_strategy(self, state: AgentState) -> bool:
        state.model_strategy = recommend_model_strategy(state.brief)
        state.poc_plan = build_poc_plan(state.brief, state.evidence, state.model_strategy)
        state.current_node = "risk_gate"
        return False

    def _node_risk_gate(self, state: AgentState) -> bool:
        state.risks = _deduplicate_risks(state.risks)
        if not state.evidence and not any(r.category == "知识覆盖" for r in state.risks):
            state.risks.append(
                RiskFlag("知识覆盖", "没有召回可引用资料，不能支持具体产品能力结论", "high", "补充资料后重跑")
            )
            if "请补充产品白皮书、接口文档或安全规范。" not in state.clarifying_questions:
                state.clarifying_questions.append("请补充产品白皮书、接口文档或安全规范。")
        high_risk = any(item.severity == "high" for item in state.risks) or bool(state.brief.compliance)
        if high_risk:
            state.review_status = "pending"
            state.status = "pending_review"
            state.current_node = "finalize"
            state.response = self._build_response(state, "pending")
            trace = _ACTIVE_TRACE.get()
            if trace is not None:
                trace.record(
                    "review_requested",
                    "risk_gate",
                    status="pending",
                    data={"risk_count": len(state.risks)},
                )
            return True
        state.current_node = "finalize"
        return False

    def _node_finalize(self, state: AgentState) -> bool:
        review_status = state.review_status if state.review_status != "not_required" else "not_required"
        state.response = self._build_response(state, review_status)
        output_text = json.dumps(state.response.to_dict(), ensure_ascii=False)
        output_policy = inspect_output(output_text)
        sensitive_policy = inspect_sensitive_data(output_text)
        state.metadata["output_policy"] = {
            "blocked": output_policy.blocked,
            "categories": output_policy.categories,
        }
        state.metadata["sensitive_data_policy"] = {
            "detected": sensitive_policy.blocked,
            "categories": sensitive_policy.categories,
        }
        if output_policy.blocked or sensitive_policy.blocked:
            state.status = "failed"
            state.current_node = "done"
            state.errors.append("output policy rejected unsupported commitment or sensitive data")
            return False
        validate_solution_dict(state.response.to_dict())
        state.status = "complete" if review_status != "rejected" else "rejected"
        state.current_node = "done"
        return False

    def _apply_review(self, state: AgentState, decision: str) -> None:
        normalized = decision.lower().strip()
        if normalized == "approve":
            state.review_status = "approved"
            state.approval_reason = "人工审核通过高风险方案继续输出。"
            state.status = "running"
            trace = _ACTIVE_TRACE.get()
            if trace is not None:
                trace.record("review_decision", "human_review", data={"decision": "approve"})
        elif normalized == "reject":
            state.review_status = "rejected"
            state.approval_reason = "人工审核拒绝，停止方案输出。"
            state.status = "rejected"
            state.current_node = "done"
            state.response = self._build_response(state, "rejected")
            trace = _ACTIVE_TRACE.get()
            if trace is not None:
                trace.record("review_decision", "human_review", status="rejected")
        else:
            raise ValueError("review_decision must be approve or reject")

    def _build_response(self, state: AgentState, review_status: str) -> SolutionResponse:
        if state.evidence:
            summary = (
                f"针对{state.brief.industry}{state.brief.use_case}，建议以证据驱动的 Agent + RAG POC 起步，"
                "先验证业务价值，再根据数据边界和性能实测决定模型服务与微调路径。"
            )
        else:
            summary = (
                f"资料不足：当前资料库没有足够证据支持{state.brief.industry}{state.brief.use_case}的具体产品承诺。"
                "建议先补充产品资料和客户约束，再进入可验收的 POC。"
            )
        return SolutionResponse(
            case_id=state.brief.case_id,
            executive_summary=summary,
            requirements=state.requirements,
            recommendation=state.recommendation,
            architecture=state.architecture,
            implementation_steps=[item["phase"] for item in state.poc_plan],
            risks=state.risks,
            clarifying_questions=state.clarifying_questions,
            evidence=state.evidence,
            poc_plan=state.poc_plan,
            model_strategy=state.model_strategy,
            assumptions=state.assumptions,
            review_status=review_status,
            model_name="presales-agent-offline",
            run_id=state.run_id,
            trace_id=state.trace_id,
        )

    def _load(self, thread_id: str) -> AgentState | None:
        if self.checkpoints is None:
            return None
        payload = self.checkpoints.load(thread_id)
        return AgentState.from_dict(payload) if payload else None

    def _save(self, state: AgentState) -> None:
        if self.checkpoints is not None:
            self.checkpoints.save(state.thread_id, state.to_dict())

    def _finish_trace(
        self, state: AgentState, trace_path: str | None, trace: TraceRecorder
    ) -> None:
        trace.record("run_finished", "presales_agent", data={"status": state.status})
        if trace_path:
            trace.write_jsonl(trace_path)


def _deduplicate_risks(risks: list[RiskFlag]) -> list[RiskFlag]:
    seen: set[tuple[str, str]] = set()
    result: list[RiskFlag] = []
    for risk in risks:
        key = (risk.category, risk.description)
        if key not in seen:
            result.append(risk)
            seen.add(key)
    return result


def _response_from_dict(payload: dict[str, Any]) -> SolutionResponse:
    return SolutionResponse(
        case_id=payload["case_id"],
        executive_summary=payload["executive_summary"],
        requirements=[Requirement(**item) for item in payload.get("requirements", [])],
        recommendation=payload.get("recommendation", []),
        architecture=payload.get("architecture", []),
        implementation_steps=payload.get("implementation_steps", []),
        risks=[RiskFlag(**item) for item in payload.get("risks", [])],
        clarifying_questions=payload.get("clarifying_questions", []),
        evidence=[Evidence(**item) for item in payload.get("evidence", [])],
        poc_plan=payload.get("poc_plan", []),
        model_strategy=payload.get("model_strategy", {}),
        assumptions=payload.get("assumptions", []),
        review_status=payload.get("review_status", "not_required"),
        model_name=payload.get("model_name", "presales-agent-offline"),
        latency_ms=payload.get("latency_ms"),
        usage=payload.get("usage", {}),
        run_id=payload.get("run_id"),
        trace_id=payload.get("trace_id"),
    )
