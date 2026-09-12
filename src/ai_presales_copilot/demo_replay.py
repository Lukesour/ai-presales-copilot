"""Contracts and loaders for the deterministic interview-demo replay.

Replay is an application-level snapshot format. It deliberately does not use
LangGraph time travel because the latter re-executes model and tool calls.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from .requirements import validate_fact_sources
from .schemas import (
    CustomerBriefV2,
    CustomerInputV2,
    InputTurnV2,
    RequirementFactV2,
    SolutionResponseV2,
    StrictModel,
)
from .security import inspect_sensitive_data

DEMO_SCENARIO_IDS = (
    "normal",
    "high_risk",
    "missing_then_clarified",
    "conflict_or_injection",
)
DEMO_WORKFLOW_NODES = (
    "intake",
    "extract_requirements",
    "assess_requirements",
    "clarify",
    "requirements_confirmation",
    "query_rewrite",
    "retrieve",
    "draft",
    "ground_claims",
    "critic",
    "repair",
    "risk_gate",
    "human_review",
    "finalize",
)
_SCENARIO_ID = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_FORBIDDEN_KEYS = {
    "authorization",
    "access_token",
    "api_key",
    "apikey",
    "client_secret",
    "password",
    "secret_key",
}


class DemoExpectedPath(StrictModel):
    """Expected visible branch for one registered synthetic scenario."""

    status: str | None = None
    status_before_review: str | None = None
    status_after_approval: str | None = None
    missing_fields: list[str] = Field(default_factory=list, max_length=16)


class DemoScenario(StrictModel):
    """A complete v2 brief owned by the demo catalog."""

    scenario_id: Literal["normal", "missing_then_clarified", "high_risk", "conflict_or_injection"]
    label: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=2_000)
    brief: CustomerBriefV2
    expected: DemoExpectedPath


class DemoScenarioCatalog(StrictModel):
    """Versioned scenario registry loaded from repository-owned JSON."""

    schema_version: Literal["1.0"] = "1.0"
    scenarios: list[DemoScenario] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def validate_registered_scenarios(self) -> DemoScenarioCatalog:
        ids = [item.scenario_id for item in self.scenarios]
        if len(ids) != len(set(ids)):
            raise ValueError("demo scenario IDs must be unique")
        if set(ids) != set(DEMO_SCENARIO_IDS):
            raise ValueError(
                "demo catalog must contain normal, missing_then_clarified, high_risk, and conflict_or_injection"
            )
        return self


class ReplayProvenance(StrictModel):
    """Build and model metadata required to explain a captured snapshot."""

    git_revision: str = Field(min_length=1, max_length=128)
    model_name: str = Field(min_length=1, max_length=256)
    model_hash: str | None = Field(default=None, max_length=256)
    prompt_version: str = Field(min_length=1, max_length=256)
    knowledge_snapshot_id: str = Field(min_length=1, max_length=256)


class ReplayEvent(StrictModel):
    """Redacted event projection used by the timeline renderer."""

    seq: int = Field(ge=1)
    event_type: str = Field(min_length=1, max_length=128)
    node: str | None = Field(default=None, max_length=64)
    status: str | None = Field(default=None, max_length=64)
    state_version: int | None = Field(default=None, ge=0)
    created_at: str = Field(min_length=1, max_length=128)
    node_latency_ms: float | None = Field(default=None, ge=0)
    details: dict[str, Any] = Field(default_factory=dict)


class ReplayStates(StrictModel):
    """Public states for the complete input-to-delivery journey."""

    initial: dict[str, Any] | None = None
    clarified: dict[str, Any] | None = None
    confirmed: dict[str, Any] | None = None
    pending: dict[str, Any] | None = None
    final: dict[str, Any]


class ReplaySnapshot(StrictModel):
    """Validated, static state and event snapshot for one demo scenario."""

    replay_schema_version: Literal["1.0"] = "1.0"
    scenario_id: Literal["normal", "missing_then_clarified", "high_risk", "conflict_or_injection"]
    label: str = Field(min_length=1, max_length=128)
    case_id: str = Field(min_length=1, max_length=128)
    synthetic: Literal[True] = True
    captured_from: Literal["live_api"] = "live_api"
    captured_at: str = Field(min_length=1, max_length=128)
    provenance: ReplayProvenance
    initial_input: CustomerInputV2 | None = None
    input_turns: list[InputTurnV2] = Field(default_factory=list, max_length=8)
    events: list[ReplayEvent] = Field(min_length=1, max_length=512)
    states: ReplayStates

    @model_validator(mode="after")
    def validate_snapshot(self) -> ReplaySnapshot:
        expected_seq = list(range(1, len(self.events) + 1))
        if [event.seq for event in self.events] != expected_seq:
            raise ValueError("replay events must have contiguous sequence numbers")
        if self.scenario_id == "high_risk":
            if self.states.pending is None:
                raise ValueError("high_risk replay requires a pending state")
            if self.states.pending.get("status") != "waiting_for_review":
                raise ValueError("high_risk pending state must wait for review")
        if self.states.initial is not None:
            if self.states.initial.get("status") not in {
                "needs_clarification",
                "ready_for_confirmation",
                "rejected",
                "needs_review",
            }:
                raise ValueError("replay initial state must stop in requirements or policy gate")
            if self.states.initial.get("response") is not None:
                raise ValueError("replay initial state cannot contain a solution response")
        if self.states.clarified is not None:
            if self.states.clarified.get("status") != "ready_for_confirmation":
                raise ValueError("replay clarified state must wait for requirements confirmation")
            if self.states.clarified.get("response") is not None:
                raise ValueError("replay clarified state cannot contain a solution response")
        if self.states.confirmed is not None and not self.states.confirmed.get("requirements_confirmed"):
            raise ValueError("replay confirmed state must record requirements_confirmed")
        if self.initial_input is not None and not self.input_turns:
            raise ValueError("replay initial_input requires at least one input turn")
        for state_name, state in (
            ("initial", self.states.initial),
            ("clarified", self.states.clarified),
            ("confirmed", self.states.confirmed),
            ("pending", self.states.pending),
            ("final", self.states.final),
        ):
            if state is None or not state.get("requirement_facts"):
                continue
            try:
                facts = [RequirementFactV2.model_validate(item) for item in state["requirement_facts"]]
                validate_fact_sources(facts, self.input_turns)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"replay {state_name} contains invalid requirement attribution") from exc
        allowed_final_statuses = {"complete"}
        if self.scenario_id == "conflict_or_injection":
            allowed_final_statuses.add("rejected")
        if self.states.final.get("status") not in allowed_final_statuses:
            raise ValueError("replay final state must be complete")
        for state_name, state in (
            ("initial", self.states.initial),
            ("clarified", self.states.clarified),
            ("confirmed", self.states.confirmed),
            ("pending", self.states.pending),
            ("final", self.states.final),
        ):
            if state is None:
                continue
            response = state.get("response")
            if response is None:
                if state_name in {"initial", "clarified", "confirmed"}:
                    continue
                raise ValueError(f"replay {state_name} state must contain a response")
            parsed = SolutionResponseV2.model_validate(response)
            if parsed.case_id != self.case_id:
                raise ValueError(f"replay {state_name} response case_id does not match snapshot")
        _reject_sensitive_snapshot(self.model_dump(mode="json"))
        return self


def load_demo_scenarios(path: str | Path) -> dict[str, DemoScenario]:
    """Load and validate the complete registered scenario catalog."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    catalog = DemoScenarioCatalog.model_validate(payload)
    return {item.scenario_id: item for item in catalog.scenarios}


def registered_replay_path(replay_dir: str | Path, scenario_id: str) -> Path:
    """Resolve only a known scenario ID; arbitrary paths never enter the UI."""

    if scenario_id not in DEMO_SCENARIO_IDS or not _SCENARIO_ID.fullmatch(scenario_id):
        raise ValueError(f"unknown demo scenario: {scenario_id}")
    return Path(replay_dir) / f"{scenario_id}.json"


def load_demo_replay(
    replay_dir: str | Path,
    scenario_id: str,
    *,
    scenarios: dict[str, DemoScenario] | None = None,
) -> ReplaySnapshot:
    """Load one registered JSON snapshot and verify its v2 evidence contract."""

    path = registered_replay_path(replay_dir, scenario_id)
    if not path.is_file():
        raise FileNotFoundError(f"replay snapshot is missing: {path}")
    snapshot = ReplaySnapshot.model_validate(json.loads(path.read_text(encoding="utf-8")))
    if snapshot.scenario_id != scenario_id:
        raise ValueError("replay filename and scenario_id do not match")
    if scenarios is not None:
        scenario = scenarios.get(scenario_id)
        if scenario is None or snapshot.case_id != scenario.brief.case_id:
            raise ValueError("replay case_id does not match the registered scenario")
        if snapshot.label != scenario.label:
            raise ValueError("replay label does not match the registered scenario")
    return snapshot


def normalize_live_events(raw_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project persistent events to a small, redacted replay event contract."""

    normalized: list[dict[str, Any]] = []
    for seq, raw in enumerate(raw_events, start=1):
        node = raw.get("node")
        failed_node = raw.get("failed_node")
        if node not in DEMO_WORKFLOW_NODES:
            node = failed_node
        if node not in DEMO_WORKFLOW_NODES:
            node = "human_review" if raw.get("event_type", "").startswith("review_") else None
        details = {
            key: ("demo-reviewer" if key == "reviewer_id" else raw[key])
            for key in ("decision", "reviewer_id", "error_code", "message", "failed_node")
            if key in raw and isinstance(raw[key], (str, int, float, bool))
        }
        latency = raw.get("node_latency_ms")
        normalized.append(
            ReplayEvent(
                seq=seq,
                event_type=str(raw.get("event_type", "event")),
                node=node,
                status=str(raw["status"]) if raw.get("status") is not None else None,
                state_version=(
                    int(raw["state_version"])
                    if isinstance(raw.get("state_version"), (int, float))
                    else None
                ),
                created_at=str(raw.get("created_at") or _utc_now()),
                node_latency_ms=float(latency) if isinstance(latency, (int, float)) else None,
                details=details,
            ).model_dump(mode="json")
        )
    return normalized


def active_replay_state(
    snapshot: ReplaySnapshot, *, approved: bool = False, stage: str | None = None
) -> dict[str, Any]:
    """Return one immutable stage, defaulting to the current review outcome."""

    if stage in {"initial", "clarified", "confirmed"}:
        candidate = getattr(snapshot.states, stage)
        if candidate is not None:
            return candidate
    if approved or snapshot.states.pending is None:
        return snapshot.states.final
    return snapshot.states.pending


def repository_demo_path(*parts: str) -> Path:
    """Resolve repository-owned demo data for scripts and the UI."""

    return Path(__file__).resolve().parents[2].joinpath(*parts)


def _reject_sensitive_snapshot(payload: dict[str, Any]) -> None:
    serialized = json.dumps(payload, ensure_ascii=False)
    if inspect_sensitive_data(serialized).blocked:
        raise ValueError("replay snapshot contains sensitive data")
    _walk_keys(payload)


def _walk_keys(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in _FORBIDDEN_KEYS:
                raise ValueError(f"replay snapshot contains forbidden key: {key}")
            _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            _walk_keys(child)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
