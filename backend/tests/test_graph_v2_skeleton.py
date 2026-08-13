"""Phase 5 (260812-0927-langgraph-orchestration-state-patch-and-interrupts):
topology, contract enforcement, and end-to-end shape tests for the
`orchestrator=graph` skeleton. Supervisor routing behavior itself is
covered by `test_supervisor_routing.py`.
"""

from __future__ import annotations

import inspect
from collections import deque

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver

import src.agents.graph_v2.nodes.extract_patch as extract_patch_module
import src.agents.graph_v2.nodes.supervisor as supervisor_module
import src.agents.graph_v2.nodes.validate_patch as validate_patch_module
from src.agents.graph_v2.contracts import CONTRACTS, ContractViolation, enforce_contract
from src.agents.graph_v2.graph import NODE_NAMES, build_graph
from src.agents.graph_v2.nodes.booking_node import booking_node
from src.agents.graph_v2.nodes.qa_node import QA_TOOLS, build_qa_subgraph
from src.agents.graph_v2.state import initial_graph_state
from src.models.schemas import PlannerChatResponse

# --- Topology ---------------------------------------------------------------


def test_every_declared_node_is_registered_and_reachable_from_start():
    app = build_graph()
    graph_repr = app.get_graph()

    for name in NODE_NAMES:
        assert name in graph_repr.nodes, f"{name} is declared but not registered"

    adjacency: dict[str, set[str]] = {}
    for edge in graph_repr.edges:
        adjacency.setdefault(edge.source, set()).add(edge.target)

    visited: set[str] = set()
    queue = deque(["__start__"])
    while queue:
        current = queue.popleft()
        if current in visited:
            continue
        visited.add(current)
        for target in adjacency.get(current, ()):
            if target not in visited:
                queue.append(target)

    unreachable = set(NODE_NAMES) - visited
    assert not unreachable, f"orphan node(s), unreachable from START: {unreachable}"
    assert "__end__" in visited, "no path reaches END"

    extra = set(graph_repr.nodes) - set(NODE_NAMES) - {"__start__", "__end__"}
    assert not extra, f"node registered but not declared in NODE_NAMES: {extra}"


def test_qa_node_has_exactly_one_outgoing_edge():
    app = build_graph()
    outgoing = [edge for edge in app.get_graph().edges if edge.source == "qa_node"]
    assert len(outgoing) == 1
    assert outgoing[0].target == "respond"


def test_only_validate_patch_calls_interrupt():
    """Phase 7's standing constraint: `interrupt()` re-runs its WHOLE node
    from the start on every resume, so a node calling it must be pure (or
    idempotent) up to that call. `validate_patch` is the only node this
    plan grants that to (see its module docstring) -- asserted here two
    ways: it is the only node whose source references `interrupt`, and it
    imports no LLM/DB/API client that a resume-triggered re-run could
    accidentally re-invoke as a side effect.

    Node modules are derived from `NODE_NAMES` (not hand-listed) so a future
    node is automatically covered instead of silently exempt."""
    import importlib

    # Every node name maps to `nodes.<name>` except the two that don't share
    # their node name with their module (validate_patch is asserted
    # separately below; qa_node is a subgraph built by build_qa_subgraph,
    # not a plain node function, so there is no bare `qa_node` module
    # attribute to source-inspect the same way -- its module is still
    # scanned for `interrupt(`).
    other_node_names = [name for name in NODE_NAMES if name not in ("validate_patch",)]
    other_node_modules = [
        importlib.import_module(f"src.agents.graph_v2.nodes.{name}") for name in other_node_names
    ]

    for module in other_node_modules:
        assert "interrupt(" not in inspect.getsource(module), f"{module.__name__} must not call interrupt()"

    assert "interrupt(" in inspect.getsource(validate_patch_module)

    forbidden = ("get_reasoning_llm", "get_fast_llm", "supabase", "httpx", "requests")
    validate_patch_source = inspect.getsource(validate_patch_module)
    for name in forbidden:
        assert name not in validate_patch_source, (
            f"validate_patch must stay pure up to interrupt() (no LLM/DB/API call) -- found {name!r}"
        )


# --- qa_node: reduced tool list + explicit checkpointer subgraph -----------


def test_qa_node_exposes_exactly_the_two_read_only_tools():
    names = {tool.name for tool in QA_TOOLS}
    assert names == {"query_hotel", "query_hotel_rooms"}
    assert not names & {"recommend_hotels", "select_hotel", "modify_trip_plan"}


def test_qa_node_is_a_compiled_subgraph_with_an_explicit_checkpointer():
    checkpointer = MemorySaver()
    subgraph = build_qa_subgraph(checkpointer)
    assert subgraph.checkpointer is checkpointer


# --- Contracts ---------------------------------------------------------------


def test_qa_node_contract_declares_no_writes():
    assert CONTRACTS["qa_node"].writes == frozenset()


def test_enforce_contract_raises_when_a_node_writes_outside_its_contract():
    def _rogue_qa_node(state):
        # qa_node's contract writes nothing -- this node misbehaves by
        # mutating a hotel_preferences path it was never granted.
        travel_state = dict(state.get("travel_state") or {})
        travel_state["hotel_preferences.amenities"] = {"presence": "set", "value": ["pool"]}
        return {"travel_state": travel_state}

    wrapped = enforce_contract("qa_node", _rogue_qa_node)
    state = initial_graph_state("t1")

    with pytest.raises(ContractViolation):
        wrapped(state)


def test_enforce_contract_allows_a_write_within_the_declared_contract():
    def _compliant_hotel_node(state):
        travel_state = dict(state.get("travel_state") or {})
        travel_state["hotel_preferences.radius_km"] = {"presence": "set", "value": 5.0}
        return {"travel_state": travel_state}

    wrapped = enforce_contract("hotel_node", _compliant_hotel_node)
    state = initial_graph_state("t1")

    result = wrapped(state)
    assert result["travel_state"]["hotel_preferences.radius_km"]["value"] == 5.0


# --- booking_node: explicit decline, never a silent pass-through -----------


def test_booking_node_declines_explicitly():
    state = initial_graph_state("t1")
    result = booking_node(state)

    assert result["task_results"][-1]["worker"] == "booking_node"
    assert result["task_results"][-1]["status"] == "declined"
    assert result["task_results"][-1]["reply"]  # non-empty — never a silent pass-through


def test_booking_node_replies_in_english_when_requested():
    state = initial_graph_state("t1")
    state["language"] = "en"
    result = booking_node(state)
    assert "book" in result["task_results"][-1]["reply"].lower()


# --- End-to-end: orchestrator=graph returns a valid PlannerChatResponse ----


def test_graph_completes_a_turn_end_to_end_and_returns_a_planner_chat_response(monkeypatch):
    """`extract_patch` (Phase 6) now runs for real, so both its LLM call and
    the supervisor's are forced to fail here -- `extract_patch` falls back to
    an empty patch/`general_question` on its own (never raises out), which
    keeps `pending_tasks` empty at the supervisor exactly as the Phase 5
    stub did, exercising the same `workers == [] -> "respond"` fallback
    deterministically, with no real model or network call anywhere in the
    turn."""

    def _raise(*_args, **_kwargs):
        raise RuntimeError("no LLM in this test")

    monkeypatch.setattr(supervisor_module, "get_fast_llm", _raise)
    monkeypatch.setattr(extract_patch_module, "get_reasoning_llm", _raise)
    monkeypatch.setattr(extract_patch_module, "_get_destination_names", lambda: ())

    app = build_graph()
    result = app.invoke(
        {
            "session_id": "turn-1",
            "language": "vi",
            "messages": [HumanMessage(content="Chào bạn")],
        },
        config={"configurable": {"thread_id": "test-e2e-thread"}},
    )

    assert "response" in result
    response = PlannerChatResponse(**result["response"])
    assert response.session_id == "turn-1"
    assert response.reply
    assert response.stage == "intake"


def test_graph_routes_a_completed_worker_through_budget_check_to_respond(monkeypatch):
    """Drives `hotel_node -> all_tasks_done(True) -> budget_check ->
    respond` through the real compiled graph, not just at the node-function
    level -- proving `budget_check` actually executes and the frozen
    response still gets built afterward.

    This substitutes `extract_patch` for one call so the test controls
    exactly what patch reaches `ask_slot`'s Phase 7 slot gate. Every OTHER
    required slot (destination/people/dates) is pre-seeded directly in the
    invoke's starting `travel_state` (not via the patch), so the gate lets
    the turn through to the supervisor instead of stopping to ask for one of
    them first, while the patch itself still only sets `budget.max` -- the
    ONE change that maps to a single workflow (`hotel`) in `IMPACT_MAP`, so
    this also exercises the supervisor's fast path (zero LLM calls) rather
    than the LLM path.
    """
    import src.agents.graph_v2.graph as graph_module
    from src.domain.travel_state import TravelState, apply_patch

    def _fake_extract_patch(_state):
        return {"patch": [{"path": "budget.max", "operation": "set", "value": 5000000}]}

    def _unreachable(*_args, **_kwargs):
        raise AssertionError("fast path must not call the LLM")

    monkeypatch.setattr(graph_module, "extract_patch", _fake_extract_patch)
    monkeypatch.setattr(supervisor_module, "get_fast_llm", _unreachable)

    seeded_state = apply_patch(
        TravelState(),
        [
            {"path": "destination", "operation": "set", "value": "Đà Nẵng"},
            {"path": "people", "operation": "set", "value": 2},
            {"path": "dates.start", "operation": "set", "value": "2099-01-01"},
            {"path": "dates.end", "operation": "set", "value": "2099-01-05"},
        ],
    ).state

    app = graph_module.build_graph()
    result = app.invoke(
        {
            "session_id": "turn-budget",
            "language": "vi",
            "travel_state": seeded_state.to_dict(),
            "messages": [HumanMessage(content="Ngân sách tối đa 5 triệu")],
        },
        config={"configurable": {"thread_id": "test-budget-check-thread"}},
    )

    assert result["pending_tasks"] == []
    assert result["task_results"][-1] == {"worker": "hotel_node", "status": "stub_pass_through"}
    assert result["routing_source"] == "impact_map"  # fast path, not the LLM

    response = PlannerChatResponse(**result["response"])
    assert response.reply  # respond ran and built the frozen shape after budget_check
