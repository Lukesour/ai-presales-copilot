import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from ai_presales_copilot.agent import PresalesAgent
from ai_presales_copilot.api import AgentHTTPService
from ai_presales_copilot.knowledge import KnowledgeBase
from ai_presales_copilot.persistence import CheckpointStore
from ai_presales_copilot.schemas import CustomerBrief
from ai_presales_copilot.security import PolicyResult

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def knowledge_base() -> KnowledgeBase:
    return KnowledgeBase(ROOT / "data/knowledge")


def _high_risk_brief(case_id: str = "agent-high-risk") -> CustomerBrief:
    return CustomerBrief(
        case_id=case_id,
        industry="制造业",
        use_case="设备运维知识助手",
        data_types=["维修手册 PDF", "工单数据库"],
        deployment="私有化",
        concurrency="峰值 5",
        latency_requirement="完整答案 10 秒内",
        compliance=["数据不能出域"],
        raw_request="在内网部署，回答设备告警和维修步骤，并保留引用与审计日志。",
    )


def test_agent_pauses_and_resumes_after_human_review(
    knowledge_base: KnowledgeBase, tmp_path: Path
) -> None:
    with CheckpointStore(":memory:") as store:
        agent = PresalesAgent(knowledge_base, store)
        trace_path = tmp_path / "agent.jsonl"
        pending = agent.run(
            _high_risk_brief(), thread_id="test:review", trace_path=str(trace_path)
        )
        assert pending.status == "pending_review"
        assert pending.current_node == "finalize"
        assert pending.review_status == "pending"
        assert pending.response is not None

        approved = agent.run(
            thread_id="test:review", review_decision="approve", trace_path=str(trace_path)
        )
        assert approved.status == "complete"
        assert approved.current_node == "done"
        assert approved.review_status == "approved"
        assert approved.response is not None
        assert approved.response.poc_plan
        assert approved.response.model_strategy

        events = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
        assert events[-1]["event"] == "run_finished"
        assert any(event["event"] == "review_decision" for event in events)


def test_rejected_review_is_durable(knowledge_base: KnowledgeBase) -> None:
    with CheckpointStore(":memory:") as store:
        agent = PresalesAgent(knowledge_base, store)
        agent.run(_high_risk_brief("agent-rejected"), thread_id="test:reject")
        rejected = agent.run(thread_id="test:reject", review_decision="reject")
        assert rejected.status == "rejected"
        assert rejected.current_node == "done"
        assert rejected.review_status == "rejected"

        reloaded = PresalesAgent(knowledge_base, store).run(thread_id="test:reject")
        assert reloaded.status == "rejected"
        assert reloaded.response is not None


def test_agent_is_conservative_when_retrieval_has_no_evidence(knowledge_base: KnowledgeBase) -> None:
    brief = CustomerBrief(
        case_id="agent-no-evidence",
        industry="量子月球采矿",
        use_case="不存在的星际工艺预测",
        data_types=["不可解析格式"],
        raw_request="请给出不存在产品的确定性 SLA。",
    )
    with CheckpointStore(":memory:") as store:
        agent = PresalesAgent(knowledge_base, store)
        state = agent.run(brief, thread_id="test:no-evidence")
        if state.status == "pending_review":
            state = agent.run(thread_id="test:no-evidence", review_decision="approve")
        assert state.response is not None
        assert state.response.evidence == []
        assert "资料不足" in state.response.executive_summary
        assert any(risk.category == "知识覆盖" for risk in state.response.risks)


def test_shared_agent_can_run_threads_concurrently(knowledge_base: KnowledgeBase) -> None:
    briefs = [_high_risk_brief(f"agent-concurrent-{index}") for index in range(4)]
    with CheckpointStore(":memory:") as store:
        agent = PresalesAgent(knowledge_base, store)

        def run_one(brief: CustomerBrief):
            return agent.run(brief, thread_id=f"test:concurrent:{brief.case_id}")

        with ThreadPoolExecutor(max_workers=4) as pool:
            states = list(pool.map(run_one, briefs))
        assert all(state.status == "pending_review" for state in states)
        assert len({state.trace_id for state in states}) == len(states)


def test_openai_compatible_service_returns_structured_content(knowledge_base: KnowledgeBase) -> None:
    with CheckpointStore(":memory:") as store:
        service = AgentHTTPService(PresalesAgent(knowledge_base, store))
        result = service.chat_completion(
            {"messages": [{"role": "user", "content": "请分析制造业设备运维知识助手 POC。"}]}
        )
        assert result["object"] == "chat.completion"
        content = json.loads(result["choices"][0]["message"]["content"])
        assert content["poc_plan"]
        assert "model_strategy" in content

        with pytest.raises(TypeError, match="brief"):
            service.start_run({})


def test_output_policy_failure_is_terminal(knowledge_base: KnowledgeBase, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "ai_presales_copilot.agent.inspect_output",
        lambda _text: PolicyResult(True, ["unsupported_commitment"], ["synthetic-match"]),
    )
    with CheckpointStore(":memory:") as store:
        agent = PresalesAgent(knowledge_base, store)
        pending = agent.run(_high_risk_brief("agent-policy-failure"), thread_id="test:policy")
        assert pending.status == "pending_review"
        failed = agent.run(thread_id="test:policy", review_decision="approve")
        assert failed.status == "failed"
        assert failed.current_node == "done"
        assert "output policy" in failed.errors[-1]
