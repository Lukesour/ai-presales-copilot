"""Optional LangGraph integration for the same explicit portfolio graph.

The core package stays dependency-free for offline CI.  Installing the
``agent`` extra enables this adapter and gives the project a direct path to
LangGraph persistence, interrupts, and deployment without changing the public
state contract.
"""

from __future__ import annotations

from collections.abc import Callable
from itertools import pairwise
from typing import Any, TypedDict


class PresalesGraphState(TypedDict, total=False):
    """Loose schema for the fields shared by ``AgentState`` and graph nodes."""

    run_id: Any
    trace_id: Any
    thread_id: Any
    brief: Any
    status: Any
    current_node: Any
    requirements: Any
    evidence: Any
    recommendation: Any
    architecture: Any
    poc_plan: Any
    model_strategy: Any
    risks: Any
    clarifying_questions: Any
    assumptions: Any
    review_status: Any
    approval_reason: Any
    response: Any
    errors: Any
    metadata: Any


def build_langgraph_graph(
    nodes: dict[str, Callable[[dict[str, Any]], dict[str, Any]]],
):
    """Compile a linear graph from named node handlers.

    Handlers receive a state dictionary and return a partial state update.  A
    caller can replace the ``risk_gate`` edge with an ``interrupt`` in a
    deployment-specific wrapper while keeping the same node boundaries.
    """

    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as exc:  # pragma: no cover - exercised only with optional extra
        raise RuntimeError(
            "LangGraph is optional; install the agent extra to compile this adapter"
        ) from exc

    graph = StateGraph(PresalesGraphState)
    ordered = ("intake", "retrieve", "architect", "poc", "model_strategy", "risk_gate", "finalize")
    for name in ordered:
        if name in nodes:
            graph.add_node(name, nodes[name])
    first = next((name for name in ordered if name in nodes), None)
    if first is None:
        raise ValueError("at least one known Agent node is required")
    graph.add_edge(START, first)
    for current, following in pairwise(ordered):
        if current in nodes and following in nodes:
            graph.add_edge(current, following)
    if "finalize" in nodes:
        graph.add_edge("finalize", END)
    return graph.compile()


def build_reviewable_langgraph_graph(
    nodes: dict[str, Callable[[dict[str, Any]], dict[str, Any]]],
    *,
    checkpointer: Any | None = None,
):
    """Compile the same graph with a real LangGraph human-review interrupt.

    The wrapped ``risk_gate`` must return ``review_status=pending`` or
    ``status=pending_review`` when human input is required.  The compiled graph
    then pauses with ``interrupt()`` and resumes with
    ``graph.invoke(Command(resume="approve"), config=...)``.  A persistent
    checkpointer is required for a production deployment; the argument stays
    optional so import-time CI remains dependency-free.
    """

    try:
        from langgraph.graph import END, START, StateGraph
        from langgraph.types import interrupt
    except ImportError as exc:  # pragma: no cover - exercised only with optional extra
        raise RuntimeError(
            "LangGraph is optional; install the agent extra to compile this adapter"
        ) from exc

    graph = StateGraph(PresalesGraphState)
    ordered = ("intake", "retrieve", "architect", "poc", "model_strategy", "risk_gate", "finalize")
    for name in ordered:
        if name not in nodes:
            continue
        if name != "risk_gate":
            graph.add_node(name, nodes[name])
            continue

        def reviewable_risk_gate(
            state: dict[str, Any], handler: Callable[[dict[str, Any]], dict[str, Any]] = nodes[name]
        ) -> dict[str, Any]:
            update = handler(state)
            needs_review = update.get("review_status") == "pending" or update.get("status") == "pending_review"
            if not needs_review:
                return update
            decision = interrupt(
                {
                    "type": "presales_human_review",
                    "message": "Review high-risk presales output before finalization.",
                    "risk_count": len(update.get("risks", [])),
                }
            )
            approved = decision == "approve" or (
                isinstance(decision, dict) and decision.get("decision") == "approve"
            )
            return {
                **update,
                "review_status": "approved" if approved else "rejected",
                "status": "running" if approved else "rejected",
            }

        graph.add_node(name, reviewable_risk_gate)

    first = next((name for name in ordered if name in nodes), None)
    if first is None:
        raise ValueError("at least one known Agent node is required")
    graph.add_edge(START, first)
    for current, following in pairwise(ordered):
        if current not in nodes or following not in nodes:
            continue
        if current == "risk_gate":
            graph.add_conditional_edges(
                current,
                lambda state, next_node=following: END
                if state.get("status") == "rejected"
                else next_node,
                {following: following, END: END},
            )
        else:
            graph.add_edge(current, following)
    if "finalize" in nodes:
        graph.add_edge("finalize", END)
    return graph.compile(checkpointer=checkpointer)
