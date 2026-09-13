import json
import re

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver

from ai_presales_copilot.api_v2 import LocalTokenAuth, create_fastapi_app
from ai_presales_copilot.knowledge import KnowledgeBase
from ai_presales_copilot.llama_client import GenerationResult, LlamaClientError
from ai_presales_copilot.llm_agent import LocalModelWorkflow
from ai_presales_copilot.model_schemas import (
    REQUIREMENT_FACT_PATHS,
    requirements_extraction_schema,
    requirements_group_schema,
    solution_draft_schema,
)
from ai_presales_copilot.persistence import CheckpointConflictError, CheckpointStore
from ai_presales_copilot.requirements import (
    assess_requirements,
    merge_fact_lists,
    validate_fact_sources,
)
from ai_presales_copilot.schemas import (
    CustomerInputV2,
    InputTurnV2,
    IntakeBriefV2,
    RequirementFactV2,
)

RAW_COMPLETE = "制造业客户希望减少停机损失。设备运维知识助手服务维修工程师，使用维修手册，部署在企业内网，数据驻留中国境内，数据可以出域。验收要求答案必须可引用。"
RAW_INCOMPLETE = "客户希望把维修手册做成设备运维知识助手，先分析需求。"


class RequirementsFirstModel:
    model = "fake-requirements-first"
    model_hash = "sha256:test"
    quantization = "Q4_K_M"
    context_length = 8192
    llama_cpp_commit = "test"

    def __init__(self, *, complete: bool = False):
        self.complete = complete
        self.extraction_calls = 0

    def health(self):
        return {"status": 200}

    def chat(self, messages, **kwargs):
        properties = (kwargs.get("response_schema") or {}).get("properties", {})
        prompt = "\n".join(item.get("content", "") for item in messages)
        if "customer_data=" in prompt:
            self.extraction_calls += 1
            complete = self.complete or "补充" in prompt
            source_turn_id = "turn-2" if complete and "补充" in prompt else "turn-1"
            facts = {
                item["field_path"]: item
                for item in self._extraction("case-test", complete, source_turn_id)["facts"]
            }
            paths = list(properties)
            payload = {
                path: {
                    "value": facts[path]["value_text"],
                    "quote": facts[path]["source_quote"],
                }
                if path in facts
                else {"value": "", "quote": ""}
                for path in paths
            }
        elif "queries" in properties:
            payload = {"queries": ["制造业 设备运维 企业内网 知识助手"]}
        elif "pass" in properties:
            payload = {"pass": True, "issues": []}
        else:
            case_id = re.search(r'"case_id": "([^"]+)"', prompt).group(1)
            payload = {
                "schema_version": "2.0",
                "case_id": case_id,
                "executive_summary": "基于证据的待验证方案。",
                "requirements": [],
                "claims": [],
                "recommendations": ["先执行 POC"],
                "architecture": ["内网 RAG"],
                "implementation_steps": ["准备脱敏资料"],
                "risks": [],
                "clarifying_questions": [],
                "selected_evidence_ids": [],
                "poc_plan": [],
                "model_strategy": {"primary_serving_path": "llama_cpp"},
                "assumptions": [],
                "review": {"required": False, "status": "not_required"},
            }
        return GenerationResult(json.dumps(payload, ensure_ascii=False), self.model, 1, 1, 2, 1.0, 0.5)

    @staticmethod
    def _extraction(case_id: str, complete: bool, source_turn_id: str) -> dict:
        brief = {
            "schema_version": "2.0",
            "case_id": case_id,
            "industry": "制造业" if complete else None,
            "business_goal": "减少停机损失" if complete else None,
            "use_case": "设备运维知识助手",
            "target_users": ["维修工程师"] if complete else [],
            "data_types": ["维修手册"],
            "deployment": "企业内网" if complete else None,
            "governance": {
                "residency": "中国境内" if complete else None,
                "egress_allowed": True if complete else None,
            },
            "acceptance_criteria": ["答案必须可引用"] if complete else [],
        }
        facts = [
            {
                "field_path": "use_case",
                "display_name": "业务场景",
                "value_text": "设备运维知识助手",
                "status": "stated",
                "importance": "blocking",
                "confidence": 0.95,
                "source_turn_id": "turn-1",
                "source_quote": "设备运维知识助手",
            },
        ]
        if complete:
            facts.extend(
                [
                    {"field_path": "industry", "display_name": "行业", "value_text": "制造业", "status": "stated", "importance": "warning", "confidence": 0.95, "source_turn_id": source_turn_id, "source_quote": "制造业"},
                    {"field_path": "business_goal", "display_name": "业务目标", "value_text": "减少停机损失", "status": "stated", "importance": "blocking", "confidence": 0.95, "source_turn_id": source_turn_id, "source_quote": "减少停机损失"},
                    {"field_path": "target_users", "display_name": "目标用户", "value_text": "维修工程师", "status": "stated", "importance": "blocking", "confidence": 0.95, "source_turn_id": source_turn_id, "source_quote": "维修工程师"},
                    {"field_path": "data_types", "display_name": "数据来源", "value_text": "维修手册", "status": "stated", "importance": "blocking", "confidence": 0.95, "source_turn_id": "turn-1", "source_quote": "维修手册"},
                    {"field_path": "deployment", "display_name": "部署方式", "value_text": "企业内网", "status": "stated", "importance": "blocking", "confidence": 0.95, "source_turn_id": source_turn_id, "source_quote": "企业内网"},
                    {"field_path": "governance.residency", "display_name": "数据驻留/出域", "value_text": "中国境内", "status": "stated", "importance": "blocking", "confidence": 0.95, "source_turn_id": source_turn_id, "source_quote": "中国境内"},
                    {"field_path": "acceptance_criteria", "display_name": "验收标准", "value_text": "答案必须可引用", "status": "stated", "importance": "blocking", "confidence": 0.95, "source_turn_id": source_turn_id, "source_quote": "答案必须可引用"},
                ]
            )
        return {"schema_version": "2.0", "brief": brief, "facts": facts, "conflicts": [], "assumptions": []}


class RequirementsFirstHighRiskModel(RequirementsFirstModel):
    def chat(self, messages, **kwargs):
        result = super().chat(messages, **kwargs)
        if "governance.egress_allowed" not in result.text:
            return result
        payload = json.loads(result.text)
        payload["governance.egress_allowed"] = {"value": "false", "quote": "数据不能出域"}
        payload["governance.audit_required"] = {
            "value": "true",
            "quote": "审计要求必须保留访问和审核日志",
        }
        return GenerationResult(
            json.dumps(payload, ensure_ascii=False),
            result.model,
            result.prompt_tokens,
            result.completion_tokens,
            result.total_tokens,
            result.latency_ms,
            result.time_to_first_token_ms,
        )


class UnavailableRequirementsModel:
    model = "unavailable-requirements-model"

    def health(self):
        return {"status": 503}

    def chat(self, _messages, **_kwargs):
        raise LlamaClientError("failed to parse grammar")


def _workflow(model):
    store = CheckpointStore(":memory:")
    return store, LocalModelWorkflow(model, KnowledgeBase("data/knowledge"), store)


def test_raw_input_stops_before_retrieval_when_blocking_fields_are_missing():
    store, workflow = _workflow(RequirementsFirstModel())
    try:
        state = workflow.start_input(
            CustomerInputV2(raw_request=RAW_INCOMPLETE, source="meeting_notes"),
            thread_id="requirements:missing",
            project_id="p",
            user_id="u",
            roles=["presales"],
            idempotency_key="run-1",
        )
        assert state["status"] == "needs_clarification"
        assert "business_goal" in state["requirement_analysis"]["blocking_fields"]
        assert not {event["node"] for event in store.events("requirements:missing")} & {"retrieve", "draft", "finalize"}
    finally:
        store.close()


def test_invalid_requirement_model_fails_closed_without_rule_fallback():
    store, workflow = _workflow(UnavailableRequirementsModel())
    try:
        state = workflow.start_input(
            CustomerInputV2(raw_request=RAW_COMPLETE, source="meeting_notes"),
            thread_id="requirements:fallback",
            project_id="p",
            user_id="u",
            roles=["presales"],
            idempotency_key="run-1",
        )
        assert state["status"] == "model_unavailable"
        assert state["extraction_mode"] == "model"
        assert not {event.get("node") for event in store.events("requirements:fallback")} & {
            "retrieve",
            "draft",
            "finalize",
        }
        assert not any("fallback" in event["event_type"] for event in store.events("requirements:fallback"))
    finally:
        store.close()


def test_model_unavailable_does_not_accept_clarification_or_synthesize_facts():
    store, workflow = _workflow(UnavailableRequirementsModel())
    try:
        state = workflow.start_input(
            CustomerInputV2(raw_request=RAW_INCOMPLETE),
            thread_id="requirements:fallback-clarification",
            project_id="p",
            user_id="u",
            roles=["presales"],
            idempotency_key="run-1",
        )
        assert state["status"] == "model_unavailable"
        with pytest.raises(CheckpointConflictError, match="not accepting"):
            workflow.add_clarification(
                thread_id=state["thread_id"],
                message="补充：业务目标是减少停机损失。",
                expected_state_version=state["state_version"],
                idempotency_key="clarify-1",
                project_id="p",
                user_id="u",
                roles=["presales"],
            )
    finally:
        store.close()


def test_customer_input_rejects_retired_language_alias():
    with pytest.raises(ValueError, match="language"):
        CustomerInputV2.model_validate(
            {"raw_request": "客户需求", "source": "meeting_notes", "language": "zh-CN"}
        )


def test_model_facing_schemas_are_compact_and_pydantic_remains_the_gate():
    extraction = requirements_extraction_schema()
    group = requirements_group_schema(("integrations", "budget"))
    draft = solution_draft_schema()
    serialized = json.dumps([extraction, draft], ensure_ascii=False)
    assert "$defs" not in serialized
    assert "$ref" not in serialized
    assert extraction["required"] == list(REQUIREMENT_FACT_PATHS)
    for field_path in REQUIREMENT_FACT_PATHS:
        assert extraction["properties"][field_path]["required"] == ["value", "quote"]
    assert list(group["properties"]) == ["integrations", "budget"]
    assert group["required"] == ["integrations", "budget"]
    assert draft["properties"]["claims"]["maxItems"] <= 16


def test_invalid_model_attribution_is_isolated_and_valid_model_facts_are_kept():
    content = "制造业客户补充：目标用户是维修工程师，部署在企业内网。"
    turns = [InputTurnV2(turn_id="turn-2", content=content, created_at="now")]
    payload = {
        "facts": [
            {
                "field_path": "integrations",
                "display_name": "集成系统",
                "value_text": content,
                "status": "stated",
                "importance": "warning",
                "source_turn_id": "turn-2",
                "source_quote": content,
            }
        ]
    }
    LocalModelWorkflow._sanitize_model_facts(payload, turns)
    assert payload["facts"][0]["status"] == "ambiguous"
    assert payload["facts"][0]["value_text"] is None

    valid_facts = [
        RequirementFactV2(
            field_path="target_users",
            display_name="目标用户/业务流程",
            value_text="维修工程师",
            status="stated",
            importance="blocking",
            source_turn_id="turn-2",
            source_quote="维修工程师",
        ),
        RequirementFactV2(
            field_path="deployment",
            display_name="部署方式",
            value_text="企业内网",
            status="stated",
            importance="blocking",
            source_turn_id="turn-2",
            source_quote="部署在企业内网",
        ),
    ]
    brief = LocalModelWorkflow._materialize_requirement_brief(
        case_id="case-test", raw_request=content, facts=valid_facts
    )
    assert brief.target_users == ["维修工程师"]
    assert brief.deployment == "企业内网"


def test_fact_source_quote_must_be_present_in_the_turn():
    turn = InputTurnV2(turn_id="turn-1", content="客户需要内网部署", created_at="now")
    fact = RequirementFactV2(
        field_path="deployment",
        display_name="部署方式",
        value_text="企业内网",
        status="stated",
        importance="blocking",
        source_turn_id="turn-1",
        source_quote="公有云",
    )
    with pytest.raises(ValueError, match="source_quote"):
        validate_fact_sources([fact], [turn])


def test_conflicting_customer_facts_block_solution_generation():
    turns = [
        InputTurnV2(turn_id="turn-1", content="要求部署在企业内网", created_at="now"),
        InputTurnV2(turn_id="turn-2", content="后来改为公有云部署", created_at="now"),
    ]
    facts = [
        RequirementFactV2(
            field_path="deployment",
            display_name="部署方式",
            value_text="企业内网",
            status="stated",
            importance="blocking",
            confidence=0.9,
            source_turn_id="turn-1",
            source_quote="企业内网",
        ),
        RequirementFactV2(
            field_path="deployment",
            display_name="部署方式",
            value_text="公有云",
            status="stated",
            importance="blocking",
            confidence=0.9,
            source_turn_id="turn-2",
            source_quote="公有云",
        ),
    ]
    validate_fact_sources(facts, turns)
    assessment = assess_requirements(
        IntakeBriefV2(case_id="conflict", deployment="企业内网"), facts, []
    )
    assert assessment.ready_for_confirmation is False
    assert "deployment" in assessment.blocking_fields
    assert assessment.conflicts[0].source_turn_ids == ["turn-1", "turn-2"]


def test_later_missing_materialization_does_not_erase_stated_fact():
    stated = RequirementFactV2(
        field_path="deployment",
        display_name="部署方式",
        value_text="企业内网",
        status="stated",
        importance="blocking",
        source_turn_id="turn-1",
        source_quote="企业内网",
    )
    missing = RequirementFactV2(
        field_path="deployment",
        display_name="部署方式",
        value_text=None,
        status="missing",
        importance="blocking",
    )
    merged = merge_fact_lists([stated], [missing])
    assert merged == [stated]


def test_clarification_is_idempotent_and_stale_versions_are_rejected():
    store, workflow = _workflow(RequirementsFirstModel())
    try:
        state = workflow.start_input(
            CustomerInputV2(raw_request=RAW_INCOMPLETE),
            thread_id="requirements:clarify",
            project_id="p",
            user_id="u",
            roles=["presales"],
            idempotency_key="run-1",
        )
        updated = workflow.add_clarification(
            thread_id=state["thread_id"],
                message="制造业客户补充：部署在企业内网，数据驻留中国境内，目标用户是维修工程师，数据来自维修手册，验收要求答案必须可引用，业务目标是减少停机损失。",
            expected_state_version=state["state_version"],
            idempotency_key="clarify-1",
            project_id="p",
            user_id="u",
            roles=["presales"],
        )
        assert updated["status"] == "ready_for_confirmation"
        replay = workflow.add_clarification(
            thread_id=state["thread_id"],
            message="同一个命令不会重复追加",
            expected_state_version=0,
            idempotency_key="clarify-1",
            project_id="p",
            user_id="u",
            roles=["presales"],
        )
        assert replay["state_version"] == updated["state_version"]
        with pytest.raises(CheckpointConflictError):
            workflow.add_clarification(
                thread_id=state["thread_id"],
                message="过期版本",
                expected_state_version=state["state_version"],
                idempotency_key="clarify-2",
                project_id="p",
                user_id="u",
                roles=["presales"],
            )
    finally:
        store.close()


def test_confirmation_is_the_only_path_to_retrieval_and_solution():
    store, workflow = _workflow(RequirementsFirstModel(complete=True))
    try:
        state = workflow.start_input(
            CustomerInputV2(raw_request=RAW_COMPLETE, source="meeting_notes"),
            thread_id="requirements:complete",
            project_id="p",
            user_id="u",
            roles=["presales"],
            idempotency_key="run-1",
        )
        assert state["status"] == "ready_for_confirmation"
        assert not any(event["node"] == "retrieve" for event in store.events(state["thread_id"]))
        state = workflow.confirm_requirements(
            thread_id=state["thread_id"],
            acknowledged_warnings=state["requirement_analysis"]["warning_fields"],
            expected_state_version=state["state_version"],
            idempotency_key="confirm-1",
            project_id="p",
            user_id="u",
            roles=["presales"],
        )
        assert state["status"] == "complete"
        events = store.events(state["thread_id"])
        assert any(event["node"] == "retrieve" for event in events)
        assert any(event["event_type"] == "requirements_confirmed" for event in events)
        assert events.index(next(event for event in events if event["event_type"] == "requirements_confirmed")) < events.index(next(event for event in events if event["node"] == "retrieve"))
    finally:
        store.close()


def test_requirements_first_high_risk_run_waits_for_review_after_confirmation():
    store, workflow = _workflow(RequirementsFirstHighRiskModel(complete=True))
    try:
        raw = (
            "制造业客户目标是减少停机损失。设备运维知识助手服务维修工程师，使用维修手册，"
            "部署在企业内网，数据驻留中国境内，数据不能出域，审计要求必须保留访问和审核日志，"
            "验收要求答案必须可引用。"
        )
        state = workflow.start_input(
            CustomerInputV2(raw_request=raw, source="meeting_notes"),
            thread_id="requirements:high-risk",
            project_id="p",
            user_id="u",
            roles=["presales"],
            idempotency_key="run-1",
        )
        assert state["status"] == "ready_for_confirmation"
        state = workflow.confirm_requirements(
            thread_id=state["thread_id"],
            acknowledged_warnings=state["requirement_analysis"]["warning_fields"],
            expected_state_version=state["state_version"],
            idempotency_key="confirm-1",
            project_id="p",
            user_id="u",
            roles=["presales"],
        )
        assert state["status"] == "waiting_for_review"
        events = store.events(state["thread_id"])
        confirmed = next(event for event in events if event["event_type"] == "requirements_confirmed")
        retrieved = next(
            event
            for event in events
            if event.get("event_type") == "node_finished" and event.get("node") == "retrieve"
        )
        assert confirmed["state_version"] < retrieved["state_version"]
    finally:
        store.close()


def test_native_requirements_interrupts_resume_on_same_thread():
    with CheckpointStore(":memory:") as store:
        workflow = LocalModelWorkflow(
            RequirementsFirstModel(),
            KnowledgeBase("data/knowledge"),
            store,
            graph_checkpointer=MemorySaver(),
        )
        state = workflow.start_input(
            CustomerInputV2(raw_request=RAW_INCOMPLETE),
            thread_id="requirements:native",
            project_id="p",
            user_id="u",
            roles=["presales"],
            idempotency_key="run-1",
        )
        assert state["status"] == "needs_clarification"
        state = workflow.add_clarification(
            thread_id=state["thread_id"],
                message="制造业客户补充：部署在企业内网，数据驻留中国境内，目标用户是维修工程师，数据来自维修手册，验收要求答案必须可引用，业务目标是减少停机损失。",
            expected_state_version=state["state_version"],
            idempotency_key="clarify-1",
            project_id="p",
            user_id="u",
            roles=["presales"],
        )
        assert state["status"] == "ready_for_confirmation"
        state = workflow.confirm_requirements(
            thread_id=state["thread_id"],
            acknowledged_warnings=state["requirement_analysis"]["warning_fields"],
            expected_state_version=state["state_version"],
            idempotency_key="confirm-1",
            project_id="p",
            user_id="u",
            roles=["presales"],
        )
        assert state["status"] == "complete"
        assert state["requirements_confirmed"] is True
        events = store.events(state["thread_id"])
        assert any(item["event_type"] == "requirements_confirmed" for item in events)
        assert any(item.get("node") == "retrieve" for item in events)


def test_native_ready_requirements_accept_supplemental_turn_before_confirmation():
    with CheckpointStore(":memory:") as store:
        workflow = LocalModelWorkflow(
            RequirementsFirstModel(complete=True),
            KnowledgeBase("data/knowledge"),
            store,
            graph_checkpointer=MemorySaver(),
        )
        state = workflow.start_input(
            CustomerInputV2(raw_request=RAW_COMPLETE),
            thread_id="requirements:native-ready-supplement",
            project_id="p",
            user_id="u",
            roles=["presales"],
            idempotency_key="run-1",
        )
        assert state["status"] == "ready_for_confirmation"
        updated = workflow.add_clarification(
            thread_id=state["thread_id"],
            message=RAW_COMPLETE + "补充预算为 15-30 万元。",
            expected_state_version=state["state_version"],
            idempotency_key="supplement-1",
            project_id="p",
            user_id="u",
            roles=["presales"],
        )
        assert updated["status"] == "ready_for_confirmation"
        assert updated["clarification_turns"] == 1
        assert len(updated["input_turns"]) == 2


def test_native_requirements_review_rejects_on_same_thread():
    with CheckpointStore(":memory:") as store:
        workflow = LocalModelWorkflow(
            RequirementsFirstHighRiskModel(complete=True),
            KnowledgeBase("data/knowledge"),
            store,
            graph_checkpointer=MemorySaver(),
        )
        raw = (
            "制造业客户目标是减少停机损失。设备运维知识助手服务维修工程师，使用维修手册，"
            "部署在企业内网，数据驻留中国境内，数据不能出域，审计要求必须保留访问和审核日志，"
            "验收要求答案必须可引用。"
        )
        state = workflow.start_input(
            CustomerInputV2(raw_request=raw, source="meeting_notes"),
            thread_id="requirements:native-reject",
            project_id="p",
            user_id="u",
            roles=["presales"],
            idempotency_key="run-1",
        )
        state = workflow.confirm_requirements(
            thread_id=state["thread_id"],
            acknowledged_warnings=state["requirement_analysis"]["warning_fields"],
            expected_state_version=state["state_version"],
            idempotency_key="confirm-1",
            project_id="p",
            user_id="u",
            roles=["presales"],
        )
        assert state["status"] == "waiting_for_review"
        state = workflow.run(
            None,
            thread_id=state["thread_id"],
            project_id="p",
            user_id="reviewer",
            roles=["reviewer"],
            review_decision="reject",
            reviewer_id="reviewer",
            reviewer_role="reviewer",
            review_reason="需要重新核对审计边界。",
            idempotency_key="review-1",
        )
        assert state["status"] == "rejected"
        assert state["review"]["status"] == "rejected"


def test_v2_api_exposes_the_same_requirements_first_state_machine():
    store, workflow = _workflow(RequirementsFirstModel())
    try:
        app = create_fastapi_app(
            workflow,
            store,
            workflow.knowledge_base,
            auth=LocalTokenAuth(token="test-token", allow_dev=True),
        )
        client = TestClient(app)
        headers = {
            "Authorization": "Bearer test-token",
            "X-Tenant-ID": "tenant-a",
            "X-User-ID": "user-a",
            "X-Roles": "presales",
            "X-Project-ID": "project-a",
            "Idempotency-Key": "run-raw-1",
        }
        first = client.post(
            "/v2/projects/project-a/runs",
            headers=headers,
            json={"input": {"raw_request": RAW_INCOMPLETE, "source": "meeting_notes"}},
        )
        assert first.status_code == 200
        state = first.json()
        assert state["status"] == "needs_clarification"
        run_id = state["run_id"]
        assert not any(item["node"] == "retrieve" for item in store.events(state["thread_id"]))
        replay = client.post(
            "/v2/projects/project-a/runs",
            headers=headers,
            json={"input": {"raw_request": "不能替换同一个幂等键"}},
        )
        assert replay.status_code == 409
        clarify_headers = {**headers, "Idempotency-Key": "clarify-api-1"}
        clarified = client.post(
            f"/v2/runs/{run_id}/clarifications",
            headers=clarify_headers,
            json={
                    "message": "制造业客户补充：部署在企业内网，数据驻留中国境内，目标用户是维修工程师，数据来自维修手册，验收要求答案必须可引用，业务目标是减少停机损失。",
                "expected_state_version": state["state_version"],
            },
        )
        assert clarified.status_code == 200
        ready = clarified.json()
        assert ready["status"] == "ready_for_confirmation"
        supplemented = client.post(
            f"/v2/runs/{run_id}/clarifications",
            headers={**headers, "Idempotency-Key": "supplement-api-1"},
            json={
                "message": "补充信息：PoC 预算为 15-30 万元。",
                "expected_state_version": ready["state_version"],
            },
        )
        assert supplemented.status_code == 200
        ready = supplemented.json()
        assert ready["status"] == "ready_for_confirmation"
        stale = client.post(
            f"/v2/runs/{run_id}/requirements/confirm",
            headers={**headers, "Idempotency-Key": "confirm-stale"},
            json={"decision": "confirm", "acknowledged_warnings": ready["requirement_analysis"]["warning_fields"], "expected_state_version": state["state_version"]},
        )
        assert stale.status_code == 409
        confirmed = client.post(
            f"/v2/runs/{run_id}/requirements/confirm",
            headers={**headers, "Idempotency-Key": "confirm-api-1"},
            json={"decision": "confirm", "acknowledged_warnings": ready["requirement_analysis"]["warning_fields"], "expected_state_version": ready["state_version"]},
        )
        assert confirmed.status_code == 200
        assert confirmed.json()["status"] == "complete"
        events = client.get(f"/v2/runs/{run_id}/events", headers=headers)
        assert events.status_code == 200
        assert any(item["event_type"] == "requirements_confirmed" for item in events.json()["events"])
    finally:
        store.close()
