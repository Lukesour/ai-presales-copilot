import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver

from ai_presales_copilot.api_v2 import LocalTokenAuth, create_fastapi_app
from ai_presales_copilot.ingestion import (
    IngestionRejected,
    SourceRegistry,
    SourceSpec,
    _AllowlistedRedirectHandler,
    ingest_source,
)
from ai_presales_copilot.knowledge import KnowledgeBase
from ai_presales_copilot.llama_client import GenerationResult, LlamaClient
from ai_presales_copilot.llm_agent import LocalModelWorkflow
from ai_presales_copilot.persistence import CheckpointStore
from ai_presales_copilot.schemas import ClaimV2, CustomerBriefV2, EvidenceChunkV2, SolutionDraftV2

RAW_COMPLETE = "制造业客户希望减少停机损失。设备运维知识助手服务维修工程师，使用维修手册，部署在企业内网，数据驻留中国境内，数据可以出域。验收要求答案必须可引用。"


class FakeModel:
    model = "fake-qwen3"
    model_hash = "sha256:test"
    quantization = "Q4_K_M"
    context_length = 8192
    llama_cpp_commit = "test-commit"

    def health(self):
        return {"status": 200}

    def chat(self, _messages, **kwargs):
        properties = kwargs["response_schema"].get("properties", {})
        prompt = "\n".join(item.get("content", "") for item in _messages)
        if "customer_data=" in prompt:
            facts = {
                "business_goal": {"value": "减少停机损失", "quote": "减少停机损失"},
                "use_case": {"value": "设备运维知识助手", "quote": "设备运维知识助手"},
                "target_users": {"value": "维修工程师", "quote": "维修工程师"},
                "data_types": {"value": "维修手册", "quote": "维修手册"},
                "deployment": {"value": "企业内网", "quote": "企业内网"},
                "governance.residency": {"value": "中国境内", "quote": "中国境内"},
                "acceptance_criteria": {"value": "答案必须可引用", "quote": "答案必须可引用"},
                "industry": {"value": "制造业", "quote": "制造业"},
                "capacity.peak_concurrency": {"value": "", "quote": ""},
                "capacity.latency_target": {"value": "", "quote": ""},
                "governance.egress_allowed": {"value": "true", "quote": "数据可以出域"},
            }
            payload = {
                path: facts.get(path, {"value": "", "quote": ""})
                for path in properties
            }
        elif "queries" in properties:
            payload = {"queries": ["制造业 设备运维 本地部署"]}
        elif "pass" in properties:
            payload = {"pass": True, "issues": []}
        else:
            payload = {
                "schema_version": "2.0",
                "case_id": "v2-test",
                "executive_summary": "基于证据的待验证方案。",
                "requirements": [],
                "claims": [],
                "recommendations": ["先执行 POC"],
                "architecture": ["API", "RAG"],
                "implementation_steps": ["准备脱敏资料"],
                "risks": [],
                "clarifying_questions": [],
                "selected_evidence_ids": [],
                "poc_plan": [],
                "model_strategy": {"primary_serving_path": "llama.cpp"},
                "assumptions": [],
                "review": {"required": False, "status": "not_required"},
            }
        return GenerationResult(json.dumps(payload, ensure_ascii=False), self.model, 10, 20, 30, 1.0, 0.5)


class FlakyModel(FakeModel):
    def __init__(self):
        self.calls = 0

    def chat(self, messages, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return GenerationResult("{", self.model, 1, 1, 2, 0.1, 0.1)
        return super().chat(messages, **kwargs)


class AlwaysInvalidModel(FakeModel):
    def chat(self, _messages, **_kwargs):
        return GenerationResult("not-json", self.model, 1, 1, 2, 0.1, 0.1)


class SensitiveOutputModel(FakeModel):
    def chat(self, messages, **kwargs):
        result = super().chat(messages, **kwargs)
        properties = kwargs["response_schema"].get("properties", {})
        if "queries" not in properties and "pass" not in properties:
            payload = json.loads(result.text)
            payload["executive_summary"] = "联系人手机号 13812345678，邮箱 leaked@example.com"
            return GenerationResult(
                json.dumps(payload, ensure_ascii=False),
                self.model,
                result.prompt_tokens,
                result.completion_tokens,
                result.total_tokens,
                result.latency_ms,
                result.time_to_first_token_ms,
            )
        return result


def _brief(**overrides):
    payload = {
        "schema_version": "2.0",
        "case_id": "v2-test",
        "industry": "制造业",
        "use_case": "设备运维知识助手",
        "raw_request": "请给出设备运维知识助手 POC。",
    }
    payload.update(overrides)
    return payload


def test_local_model_graph_is_real_and_durable(tmp_path: Path):
    with CheckpointStore(tmp_path / "checkpoints.db") as store:
        workflow = LocalModelWorkflow(FakeModel(), KnowledgeBase("data/knowledge"), store)
        state = workflow.run(
            CustomerBriefV2.model_validate(_brief()),
            thread_id="v2:test",
            tenant_id="tenant-a",
            project_id="project-a",
            user_id="user-a",
            roles=["presales"],
            idempotency_key="run-1",
        )
        assert state["status"] in {"complete", "waiting_for_review"}
        assert state["response"]["schema_version"] == "2.0"
        assert state["response"]["provenance"]["model_quantization"] == "Q4_K_M"
        assert store.events("v2:test")
        assert store.load_by_run_id(state["run_id"])["run_id"] == state["run_id"]


def test_claim_references_are_retained_in_final_evidence():
    with CheckpointStore(":memory:") as store:
        workflow = LocalModelWorkflow(FakeModel(), KnowledgeBase("data/knowledge"), store)
        brief = CustomerBriefV2.model_validate(_brief())
        state = workflow._new_state(brief, "claim-evidence")
        evidence = EvidenceChunkV2(
            evidence_id="manual:1",
            source_id="manual",
            title="维修手册",
            excerpt="执行安全停机后再进行维修。",
            content_hash="sha256:manual",
        )
        draft = SolutionDraftV2(
            case_id=brief.case_id,
            executive_summary="基于维修手册的待验证方案。",
            claims=[
                ClaimV2(
                    claim_id="claim-1",
                    text="维修前应执行安全停机。",
                    claim_type="fact",
                    support_status="supported",
                    evidence_ids=[evidence.evidence_id],
                )
            ],
        )
        response = workflow._build_response(
            brief,
            draft,
            [evidence],
            state,
            review_status="not_required",
            elapsed_ms=1,
        )
        assert [item.evidence_id for item in response.evidence] == [evidence.evidence_id]
        assert response.claims[0].evidence_ids == [evidence.evidence_id]


def test_model_unavailable_never_falls_back_to_template():
    with CheckpointStore(":memory:") as store:
        workflow = LocalModelWorkflow(
            LlamaClient("http://127.0.0.1:1", "unavailable", timeout_s=0.05),
            KnowledgeBase("data/knowledge"),
            store,
        )
        state = workflow.run(CustomerBriefV2.model_validate(_brief()), thread_id="no-model", idempotency_key="x")
        assert state["status"] == "model_unavailable"
        assert state.get("response") is None
        assert state["error_code"] == "model_unavailable"


def test_llama_readiness_rejects_an_unserved_configured_model(monkeypatch):
    client = LlamaClient("http://unused", "configured-model")
    monkeypatch.setattr(client, "health", lambda: {"status": 200})
    monkeypatch.setattr(client, "_get", lambda _path: {"data": [{"id": "served-model"}]})

    result = client.readiness()

    assert result["status"] == "not_ready"
    assert result["error_code"] == "model_mismatch"
    assert result["configured_model"] == "configured-model"
    assert result["available_models"] == ["served-model"]


def test_sensitive_customer_input_requires_review():
    with CheckpointStore(":memory:") as store:
        workflow = LocalModelWorkflow(FakeModel(), KnowledgeBase("data/knowledge"), store)
        brief = CustomerBriefV2.model_validate(
            _brief(raw_request="请分析设备运维需求，联系人手机号 13812345678。")
        )
        state = workflow.run(brief, thread_id="sensitive-input", idempotency_key="x")
        assert state["status"] == "waiting_for_review"
        assert state["policy"]["sensitive_blocked"] is True
        assert state["error_code"] == "needs_review"


def test_sensitive_model_output_is_redacted_before_checkpoint():
    with CheckpointStore(":memory:") as store:
        workflow = LocalModelWorkflow(SensitiveOutputModel(), KnowledgeBase("data/knowledge"), store)
        state = workflow.run(CustomerBriefV2.model_validate(_brief()), thread_id="sensitive-output", idempotency_key="x")
        serialized = json.dumps(state["response"], ensure_ascii=False)
        assert state["status"] == "waiting_for_review"
        assert "13812345678" not in serialized
        assert "leaked@example.com" not in serialized
        assert "[PHONE_REDACTED]" in serialized
        assert "[EMAIL_REDACTED]" in serialized


def test_native_langgraph_interrupt_resumes_review():
    with CheckpointStore(":memory:") as store:
        workflow = LocalModelWorkflow(
            FakeModel(),
            KnowledgeBase("data/knowledge"),
            store,
            graph_checkpointer=MemorySaver(),
        )
        brief = CustomerBriefV2.model_validate(_brief(governance={"egress_allowed": False}))
        pending = workflow.run(brief, thread_id="native-review", idempotency_key="run-native")
        assert pending["status"] == "waiting_for_review"
        assert "__interrupt__" not in pending
        approved = workflow.run(
            None,
            thread_id="native-review",
            user_id="reviewer-1",
            roles=["reviewer"],
            review_decision="approve",
            reviewer_id="reviewer-1",
            reviewer_role="reviewer",
            review_reason="已核对证据",
            idempotency_key="review-native",
        )
        assert approved["status"] == "complete"
        assert approved["current_node"] == "done"
        assert approved["review"]["reviewer_id"] == "reviewer-1"


def test_structured_output_has_one_run_level_retry():
        with CheckpointStore(":memory:") as store:
            workflow = LocalModelWorkflow(FlakyModel(), KnowledgeBase("data/knowledge"), store)
            state = workflow.run(CustomerBriefV2.model_validate(_brief()), thread_id="flaky", idempotency_key="x")
        assert state["status"] == "complete"
        assert state["structured_retries"] == 1
        assert state["response"]["quality"]["structured_retries"] == 1


def test_repeated_structured_failure_is_terminal_without_template():
    with CheckpointStore(":memory:") as store:
        workflow = LocalModelWorkflow(AlwaysInvalidModel(), KnowledgeBase("data/knowledge"), store)
        state = workflow.run(CustomerBriefV2.model_validate(_brief()), thread_id="invalid", idempotency_key="x")
        assert state["status"] == "model_unavailable"
        assert state["structured_retries"] == 1
        assert state.get("response") is None


def test_fastapi_auth_idempotency_and_events():
    with CheckpointStore(":memory:") as store:
        workflow = LocalModelWorkflow(FakeModel(), KnowledgeBase("data/knowledge"), store)
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
            "Idempotency-Key": "run-1",
        }
        payload = {
            "input": {
                "raw_request": RAW_COMPLETE,
                "source": "meeting_notes",
            }
        }
        first = client.post("/v2/projects/project-a/runs", headers=headers, json=payload)
        assert first.status_code == 200
        run_id = first.json()["run_id"]
        assert first.json()["status"] == "ready_for_confirmation"
        assert first.json()["requirements_confirmed"] is False
        second = client.post("/v2/projects/project-a/runs", headers=headers, json=payload)
        assert second.status_code == 200
        assert second.json()["run_id"] == run_id
        conflicting_payload = {
            "input": {
                "raw_request": "这是同一个幂等键下的不同客户需求。",
                "source": "meeting_notes",
            }
        }
        conflict = client.post(
            "/v2/projects/project-a/runs", headers=headers, json=conflicting_payload
        )
        assert conflict.status_code == 409
        read_headers = {**headers, "X-Project-ID": "project-a"}
        events = client.get(f"/v2/runs/{run_id}/events", headers=read_headers)
        assert events.status_code == 200
        assert events.json()["events"]
        unauthorized = client.get(f"/v2/runs/{run_id}")
        assert unauthorized.status_code == 401

        other_tenant = client.get(
            f"/v2/runs/{run_id}/events",
            headers={**read_headers, "X-Tenant-ID": "tenant-b"},
        )
        assert other_tenant.status_code == 404

        confirm_headers = {
            **read_headers,
            "X-Roles": "presales",
            "Idempotency-Key": "confirm-1",
        }
        confirmed = client.post(
            f"/v2/runs/{run_id}/requirements/confirm",
            headers=confirm_headers,
            json={
                "decision": "confirm",
                "expected_state_version": first.json()["state_version"],
                "acknowledged_warnings": first.json()["requirement_analysis"]["warning_fields"],
            },
        )
        assert confirmed.status_code == 200
        assert confirmed.json()["requirements_confirmed"] is True
        assert confirmed.json()["status"] in {"complete", "waiting_for_review", "model_unavailable"}
        retired = client.post("/v1/projects/project-a/runs", headers=headers, json=payload)
        assert retired.status_code in {404, 405}


def test_ingestion_emits_hash_and_locator(tmp_path: Path):
    source_path = tmp_path / "manual.md"
    source_path.write_text("# 维修流程\n\n先确认设备状态，再执行安全停机。", encoding="utf-8")
    registry = SourceRegistry.from_json(_write_registry(tmp_path / "registry.json", source_path))
    result = ingest_source(registry.get("manual"), root=tmp_path)
    assert result.content_hash
    assert result.chunks[0].content_hash == result.content_hash
    assert "heading=" in result.chunks[0].to_dict()["locator"]


def test_knowledge_retrieval_filters_tenant_acl_and_effective_time(tmp_path: Path):
    chunks_path = tmp_path / "chunks.jsonl"
    chunks_path.write_text(
        "\n".join(
            json.dumps(item, ensure_ascii=False)
            for item in [
                {
                    "evidence_id": "public:1",
                    "source_id": "public-source",
                    "title": "公共维修资料",
                    "excerpt": "设备维修流程和安全停机",
                    "content_hash": "hash-public",
                    "tenant_id": "public",
                },
                {
                    "evidence_id": "tenant-a:1",
                    "source_id": "tenant-source",
                    "title": "租户资料",
                    "excerpt": "设备维修流程和租户专属报警码",
                    "content_hash": "hash-tenant",
                    "tenant_id": "tenant-a",
                    "acl": ["presales"],
                },
                {
                    "evidence_id": "future:1",
                    "source_id": "future-source",
                    "title": "未来版本",
                    "excerpt": "设备维修流程和未来报警码",
                    "content_hash": "hash-future",
                    "tenant_id": "tenant-a",
                    "effective_from": "2999-01-01T00:00:00Z",
                },
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    knowledge = KnowledgeBase(tmp_path / "docs", chunks_path=chunks_path)
    presales_ids = {
        item.evidence_id
        for item in knowledge.search("设备维修流程", tenant_id="tenant-a", roles=["presales"], top_k=10)
    }
    assert presales_ids == {"public:1", "tenant-a:1"}
    viewer_ids = {
        item.evidence_id
        for item in knowledge.search("设备维修流程", tenant_id="tenant-a", roles=["viewer"], top_k=10)
    }
    assert viewer_ids == {"public:1"}
    assert knowledge.revoke_source("tenant-source") == 1


def test_authoritative_empty_sql_index_does_not_fallback_to_local_chunks():
    class EmptyAuthoritativeIndex:
        def has_sources(self):
            return True

        def search(self, *_args, **_kwargs):
            return []

    with CheckpointStore(":memory:") as store:
        workflow = LocalModelWorkflow(
            FakeModel(),
            KnowledgeBase("data/knowledge"),
            store,
            knowledge_index=EmptyAuthoritativeIndex(),
        )
        brief = CustomerBriefV2.model_validate(_brief())
        evidence = workflow._retrieve(["制造业 设备运维"], brief, {"tenant_id": "local", "roles": []})
        assert evidence == []


def test_remote_ingestion_requires_https_allowlisted_source():
    with pytest.raises(IngestionRejected):
        SourceSpec(
            source_id="bad",
            title="bad",
            license="test",
            source_url="http://127.0.0.1/private",
            allowed_domains=("127.0.0.1",),
        )


def test_remote_redirect_rechecks_allowlist_and_private_networks():
    handler = _AllowlistedRedirectHandler(("docs.example.com",))
    with pytest.raises(IngestionRejected):
        handler.redirect_request(
            None,
            None,
            302,
            "Found",
            "http://127.0.0.1/private",
            {},
        )


def test_local_ingestion_cannot_escape_root(tmp_path: Path):
    source = SourceSpec(
        source_id="escape",
        title="escape",
        license="test",
        local_path="../outside.md",
    )
    with pytest.raises(IngestionRejected):
        ingest_source(source, root=tmp_path)


def _write_registry(path: Path, source_path: Path) -> Path:
    path.write_text(
        json.dumps(
            [{"source_id": "manual", "title": "维修手册", "license": "test", "local_path": source_path.name}]
        ),
        encoding="utf-8",
    )
    return path
