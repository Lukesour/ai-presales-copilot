import pytest

from ai_presales_copilot.compact_contract import (
    compact_target_from_payload,
    merge_compact_solution,
    validate_compact_solution_dict,
)


def _base_payload() -> dict:
    return {
        "schema_version": "2.0",
        "case_id": "case-001",
        "executive_summary": "确定性基线方案",
        "requirements": [],
        "recommendations": ["基线建议"],
        "architecture": ["检索", "审核"],
        "implementation_steps": ["准备数据"],
        "claims": [],
        "risks": [],
        "clarifying_questions": ["峰值并发是多少？"],
        "evidence": [
            {
                "evidence_id": "KB-001",
                "source_id": "source-001",
                "title": "部署约束",
                "excerpt": "私有化需要承担运维成本。",
                "source_path": "data/knowledge/deployment-security.md",
                "content_hash": "hash-001",
            }
        ],
        "poc_plan": [],
        "model_strategy": {},
        "assumptions": ["需要客户确认"],
        "review": {"status": "pending", "required": True},
        "provenance": {
            "run_id": "run-001",
            "trace_id": "trace-001",
            "thread_id": "thread-001",
            "model_name": "test",
            "prompt_version": "test",
            "generated_at": "2026-09-11T00:00:00Z",
        },
        "quality": {},
    }


def test_compact_target_is_small_and_valid() -> None:
    target = compact_target_from_payload(
        {
            **_base_payload(),
            "risks": [
                {
                    "category": "合规",
                    "description": "需要确认数据边界",
                    "action": "安全评审",
                }
            ],
        }
    )
    validate_compact_solution_dict(target)
    assert set(target) == {
        "case_id",
        "executive_summary",
        "recommendations",
        "risk_flags",
        "clarifying_questions",
        "evidence_ids",
        "review_status",
    }
    assert target["evidence_ids"] == ["KB-001"]
    assert target["risk_flags"] == ["合规：需要确认数据边界；行动：安全评审"]


def test_compact_validator_rejects_object_recommendations() -> None:
    with pytest.raises(TypeError, match="recommendations must be an array"):
        validate_compact_solution_dict(
            {
                "case_id": "case-001",
                "executive_summary": "摘要",
                "recommendations": "错误类型",
                "risk_flags": [],
                "clarifying_questions": [],
                "evidence_ids": [],
                "review_status": "pending",
            }
        )


def test_merge_keeps_deterministic_fields_and_review_gate() -> None:
    merged = merge_compact_solution(
        _base_payload(),
        {
            "case_id": "case-001",
            "executive_summary": "模型生成的简短摘要",
            "recommendations": ["建议先做 RAG POC"],
            "risk_flags": ["不要承诺未经验证的 SLA"],
            "clarifying_questions": ["需要多少并发？"],
            "evidence_ids": ["KB-001"],
            "review_status": "not_required",
        },
    )
    assert merged["executive_summary"] == "模型生成的简短摘要"
    assert merged["recommendations"] == ["建议先做 RAG POC"]
    assert merged["architecture"] == ["检索", "审核"]
    assert merged["poc_plan"] == []
    assert merged["evidence"][0]["evidence_id"] == "KB-001"
    assert merged["review"]["status"] == "pending"
    assert merged["risks"][-1]["action"] == "人工复核"


def test_merge_drops_unknown_evidence_id_and_adds_high_risk() -> None:
    merged = merge_compact_solution(
        _base_payload(),
        {
            "case_id": "case-001",
            "executive_summary": "摘要",
            "recommendations": [],
            "risk_flags": [],
            "clarifying_questions": [],
            "evidence_ids": ["KB-NOT-IN-RETRIEVAL"],
            "review_status": "pending",
        },
    )
    assert [item["evidence_id"] for item in merged["evidence"]] == ["KB-001"]
    assert merged["risks"][-1]["severity"] == "high"
