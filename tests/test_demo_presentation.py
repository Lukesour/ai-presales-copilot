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
from ai_presales_copilot.schemas import CustomerBrief, CustomerBriefV2

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
        assert len(build_timeline_rows([event.model_dump() for event in snapshot.events])) == 11


def test_missing_scenario_exposes_exact_clarification_fields(scenarios):
    state = scenarios["missing"].brief.model_dump(mode="json")
    assert state["deployment"] == "未说明"
    assert all(value is None for value in state["capacity"].values())
    assert state["governance"]["egress_allowed"] is None
    assert state["governance"]["residency"] is None
    assert scenarios["missing"].expected.missing_fields == [
        "deployment",
        "capacity.peak_concurrency",
        "capacity.latency_target",
        "governance.residency",
    ]


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


def test_legacy_conversion_normalizes_volume_and_latency_units():
    brief = CustomerBrief(
        case_id="legacy",
        industry="制造业",
        use_case="设备问答",
        concurrency="日请求 500 次",
        latency_requirement="首 Token 2 秒内",
    )
    converted = CustomerBriefV2.from_legacy(brief)
    assert converted.capacity.daily_requests == 500
    assert converted.capacity.peak_concurrency is None
    assert converted.capacity.ttft_target_ms == 2000
    assert converted.capacity.full_answer_target_ms is None

    complete = CustomerBrief(
        case_id="legacy-complete",
        industry="制造业",
        use_case="设备问答",
        concurrency="峰值 20",
        latency_requirement="完整答案 10 秒内",
    )
    converted_complete = CustomerBriefV2.from_legacy(complete)
    assert converted_complete.capacity.peak_concurrency == 20
    assert converted_complete.capacity.full_answer_target_ms == 10000
