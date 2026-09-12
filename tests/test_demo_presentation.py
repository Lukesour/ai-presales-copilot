import copy
import json
from pathlib import Path

import pytest

from ai_presales_copilot.demo_controller import (
    apply_replay_decision,
    new_session,
)
from ai_presales_copilot.demo_replay import (
    DEMO_SCENARIO_IDS,
    load_demo_replay,
    load_demo_scenarios,
    registered_replay_path,
)
from ai_presales_copilot.demo_view import (
    build_claim_evidence_rows,
    build_readiness_view,
    build_solution_view,
    build_timeline_rows,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def scenarios():
    return load_demo_scenarios(ROOT / "data/demo/scenarios.json")


def test_registered_replays_validate_all_v2_fields(scenarios):
    assert tuple(scenarios) == DEMO_SCENARIO_IDS
    for scenario_id in DEMO_SCENARIO_IDS:
        snapshot = load_demo_replay(ROOT / "data/demo/replays", scenario_id, scenarios=scenarios)
        view = build_solution_view(snapshot.states.final["response"])
        assert all(view["visible_fields"].values())
        assert len(build_timeline_rows([event.model_dump() for event in snapshot.events])) == 14


def test_missing_then_clarified_replay_exposes_requirement_gate(scenarios):
    snapshot = load_demo_replay(
        ROOT / "data/demo/replays", "missing_then_clarified", scenarios=scenarios
    )
    assert snapshot.states.initial is not None
    assert snapshot.states.initial["status"] == "needs_clarification"
    assert snapshot.states.initial["response"] is None
    assert snapshot.states.clarified["status"] == "ready_for_confirmation"


def test_claim_evidence_one_to_many_and_unknown_reference_marker():
    response = {
        "claims": [
            {
                "claim_id": "claim-1",
                "text": "受支持的事实",
                "claim_type": "fact",
                "support_status": "supported",
                "evidence_ids": ["e-1", "e-2"],
            },
            {
                "claim_id": "claim-2",
                "text": "没有证据的结论",
                "claim_type": "unknown",
                "support_status": "needs_review",
                "evidence_ids": [],
            },
        ],
        "evidence": [
            {"evidence_id": "e-1", "title": "资料一", "excerpt": "片段一"},
            {"evidence_id": "e-2", "title": "资料二", "excerpt": "片段二"},
        ],
    }
    rows = build_claim_evidence_rows(response)
    assert len(rows) == 3
    assert [row["evidence_id"] for row in rows] == ["e-1", "e-2", "—"]
    assert rows[-1]["support_status"] == "needs_review"


def test_timeline_keeps_unexecuted_repair_and_missing_latency():
    rows = build_timeline_rows(
        [
            {"event_type": "node_finished", "node": "critic", "status": "running", "state_version": 2},
            {"event_type": "review_requested", "node": "human_review", "status": "waiting_for_review"},
        ]
    )
    by_node = {row["node"]: row for row in rows}
    assert by_node["critic"]["status"] == "已完成"
    assert by_node["repair"]["status"] == "未执行"
    assert by_node["human_review"]["status"] == "等待审核"
    assert by_node["human_review"]["node_latency_ms"] == "—"


def test_timeline_labels_review_approval_separately_from_completion(scenarios):
    snapshot = load_demo_replay(ROOT / "data/demo/replays", "high_risk", scenarios=scenarios)
    rows = build_timeline_rows([event.model_dump() for event in snapshot.events])
    review = next(row for row in rows if row["node"] == "human_review")
    assert review["status"] == "已通过"


def test_requirements_first_timeline_has_one_row_per_node_and_surfaces_failure():
    rows = build_timeline_rows(
        [
            {"event_type": "node_started", "node": "intake", "status": "running"},
            {"event_type": "node_finished", "node": "intake", "status": "running", "state_version": 2},
            {"event_type": "node_started", "node": "extract_requirements", "status": "running"},
            {
                "event_type": "model_unavailable",
                "node": "done",
                "failed_node": "extract_requirements",
                "status": "model_unavailable",
                "error_code": "model_unavailable",
            },
        ]
    )
    assert len(rows) == 14
    assert [row["node"] for row in rows].count("intake") == 1
    extraction = next(row for row in rows if row["node"] == "extract_requirements")
    assert extraction["phase"] == "需求分析"
    assert extraction["status"] == "模型不可用"
    assert extraction["event"] == "模型不可用"


def test_rendering_escapes_untrusted_model_text_and_preserves_nested_strategy():
    response = {
        "schema_version": "2.0",
        "case_id": "case",
        "executive_summary": "<script>alert(1)</script>",
        "model_strategy": {"nested": {"provider": "value", "threshold": 0.8}},
    }
    view = build_solution_view(response)
    assert "<script>" not in view["summary_markdown"]
    assert view["model_strategy"]["nested"]["threshold"] == 0.8


def test_readiness_view_distinguishes_ready_and_not_ready():
    assert build_readiness_view({"status": "ready", "checks": {"model": True}})["ready"] is True
    not_ready = build_readiness_view({"status": "not_ready", "checks": {"model": False}})
    assert not_ready["ready"] is False
    assert not_ready["checks_rows"] == [{"check": "model", "status": "失败"}]


def test_readiness_view_names_the_actual_checkpoint_failure():
    view = build_readiness_view(
        {
            "status": "not_ready",
            "checks": {
                "database": False,
                "knowledge_index": True,
                "model": True,
                "database_error_code": "checkpoint_format_unsupported",
            },
        }
    )
    assert "checkpoint" in view["message"]
    assert "llama-server 未启动" in view["message"]


def test_readiness_view_names_the_configured_model_mismatch():
    view = build_readiness_view(
        {
            "status": "not_ready",
            "checks": {
                "database": True,
                "knowledge_index": True,
                "model": False,
                "model_error_code": "model_mismatch",
                "model_configured": "qwen3-8b-q4",
                "model_available": ["qwen3-1.7b-demo"],
            },
        }
    )
    assert "qwen3-8b-q4" in view["message"]
    assert "qwen3-1.7b-demo" in view["message"]
    assert "--model" in view["message"]


def test_replay_approval_is_local_and_does_not_need_api(monkeypatch, scenarios):
    snapshot = load_demo_replay(ROOT / "data/demo/replays", "high_risk", scenarios=scenarios)
    session = new_session()
    session.update(
        {
            "mode": "replay",
            "scenario_id": "high_risk",
            "replay_states": snapshot.states.model_dump(mode="json"),
            "public_state": copy.deepcopy(snapshot.states.pending),
        }
    )
    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: pytest.fail("Replay made a network call"))
    apply_replay_decision(session, "approve")
    assert session["public_state"]["status"] == "complete"
    assert session["public_state"]["review"]["status"] == "approved"


def test_replay_load_does_not_call_network(monkeypatch, scenarios):
    from ai_presales_copilot.demo_controller import load_replay_session

    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: pytest.fail("Replay made a network call"))
    session = new_session()
    session.update({"mode": "replay", "scenario_id": "normal"})
    load_replay_session(session, scenarios, str(ROOT / "data/demo/replays"))
    assert session["public_state"]["status"] == "complete"
    assert session["readiness"]["status"] == "skipped"


def test_live_run_stops_before_post_when_readiness_fails(monkeypatch, scenarios):
    from ai_presales_copilot.demo_controller import run_live

    monkeypatch.setattr(
        "ai_presales_copilot.demo_controller.fetch_readiness",
        lambda *_args: {"status": "not_ready", "checks": {"model": False}},
    )
    monkeypatch.setattr(
        "ai_presales_copilot.demo_controller.api_request",
        lambda *_args, **_kwargs: pytest.fail("not_ready Live run sent POST"),
    )
    session = new_session()
    run_live(session, scenarios, "http://unused", "token")
    assert session["public_state"] == {}
    assert "阻止创建 run" in session["message"]


def test_replay_rejects_path_traversal_and_invalid_snapshot(tmp_path, scenarios):
    with pytest.raises(ValueError, match="unknown demo scenario"):
        registered_replay_path(tmp_path, "../secrets")
    source = json.loads((ROOT / "data/demo/replays/high_risk.json").read_text(encoding="utf-8"))
    source["states"].pop("pending")
    (tmp_path / "high_risk.json").write_text(json.dumps(source), encoding="utf-8")
    with pytest.raises(ValueError, match="pending"):
        load_demo_replay(tmp_path, "high_risk", scenarios=scenarios)
