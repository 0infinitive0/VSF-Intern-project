"""Phase 5 tests for the chat-turn StateGraph (`build_chat_turn_graph`).

Reuses the stubbing seams tests/test_chat_session.py and
tests/test_chat_turn_characterization.py already established (`_FakeTool`,
`_FakeTools`, `_session()`, forcing `decide_route_by_llm` off) rather than
inventing new ones — these tests exercise the graph wiring itself, not the
node bodies, which are already pinned by those files.
"""

from __future__ import annotations

import pytest

import src.agents.session as session_module
from src.agents.graph import _CHAT_TURN_RECURSION_LIMIT, build_chat_turn_graph
from src.agents.session import ChatSession, process_chat_turn


@pytest.fixture(autouse=True)
def _no_live_supervisor(monkeypatch):
    monkeypatch.setattr(session_module, "decide_route_by_llm", lambda session, user_input: None)


class _FakeTool:
    def __init__(self, invoke_fn):
        self._invoke_fn = invoke_fn

    def invoke(self, args):
        return self._invoke_fn(args)


def _never_called(name):
    def _raise(_args):
        raise AssertionError(f"{name} not stubbed for this test")

    return _FakeTool(_raise)


class _FakeTools:
    def __init__(self):
        self.recommend_hotels = _never_called("recommend_hotels")
        self.select_hotel = _never_called("select_hotel")
        self.finalize_trip_plan = _never_called("finalize_trip_plan")
        self.modify_trip_plan = _never_called("modify_trip_plan")


def _session(**overrides) -> ChatSession:
    defaults = dict(
        session_id="graph-test",
        agent=object(),
        config={"configurable": {"thread_id": "graph-test"}},
        tools=_FakeTools(),
    )
    defaults.update(overrides)
    return ChatSession(**defaults)


_EXPECTED_NODES = {"router", "select_hotel", "finalize", "new_trip_or_edit", "edit_draft", "chat_agent"}


def test_graph_has_exactly_six_nodes_no_orphan_branches():
    session = _session()
    graph = build_chat_turn_graph(session)
    drawable = graph.get_graph()

    node_names = set(drawable.nodes.keys()) - {"__start__", "__end__"}
    assert node_names == _EXPECTED_NODES

    reachable_from = {name for edge in drawable.edges for name in (edge.source, edge.target)}
    for node in _EXPECTED_NODES:
        assert node in reachable_from, f"{node} has no edges at all — orphan branch"


def test_recursion_limit_is_set_on_the_compiled_graph():
    session = _session()
    graph = build_chat_turn_graph(session)
    assert graph.config.get("recursion_limit") == _CHAT_TURN_RECURSION_LIMIT


def test_reroute_count_capped_at_one_when_select_hotel_keeps_being_proposed(monkeypatch):
    """Forces the pathological case the plan's reroute_count guard exists
    for: an LLM router that keeps proposing select_hotel even after the
    pending list is dropped. Without the cap, select_hotel -> router would
    cycle forever (bounded here only by recursion_limit, which would raise
    instead of returning a reply). With the cap, the tool fires exactly
    once — the second router decision that still proposes select_hotel is
    given up on without a second tool invocation (session.py's original
    cascade only ever called select_hotel once per turn too) — and the
    turn falls through to new_trip_or_edit's normal intake/chat_agent
    decision."""
    session = _session(pending_hotel_selection={"mode": "new_trip", "options": []}, initial_plan_complete=True)
    monkeypatch.setattr(session_module, "_decide_route", lambda *_args, **_kwargs: "select_hotel")

    calls = {"n": 0}

    def _never_resolves(_args):
        calls["n"] += 1
        # Simulate a hotel list that is always shown but never resolves —
        # keeps `picked` False so _run_select_hotel keeps returning None
        # (drop-and-reroute) instead of terminating.
        session.pending_hotel_selection = {"mode": "new_trip", "options": []}
        return "Mình chưa xác định được đúng khách sạn bạn muốn chọn."

    session.tools.select_hotel = _FakeTool(_never_resolves)

    class _FakeMessage:
        type = "ai"
        tool_calls = []
        content = "Đây là câu trả lời chung."

    class _FallbackAgent:
        def stream(self, *_args, **_kwargs):
            yield {"messages": [_FakeMessage()]}

    session.agent = _FallbackAgent()

    # "chốt lịch trình" is not a hotel-choice attempt (is_finalization_request
    # matches it), so _run_select_hotel drops the pending list and returns
    # None each time — the same seam tests/test_chat_session.py already uses.
    result = process_chat_turn(session, "chốt lịch trình")

    assert calls["n"] == 1, "select_hotel must fire exactly once, never twice in one turn"
    assert result.tool == "agent_stream"
    assert result.text == "Đây là câu trả lời chung."


def test_llm_proposed_chat_route_does_not_run_the_new_trip_or_edit_block(monkeypatch):
    """Regression test for a real bug caught in review: routing intake/chat
    labels through new_trip_or_edit is only safe if that node gates its
    new_trip/edit_draft handling on the ROUTE LABEL itself (matching the
    original cascade's `if route in ("new_trip", "edit_draft")`), not on a
    re-derived `has_saved_plan and not planning_new_trip` condition.
    `validate_route`'s impossibility map does not constrain "chat"/"intake",
    so the LLM supervisor (the production default,
    src/config.py trip_supervisor_router=True) can legitimately propose
    "chat" even when a saved plan exists and planning_new_trip is False —
    exactly the state that would otherwise make new_trip_or_edit think this
    is an edit_draft turn and call plan_trip_edit / mutate the saved plan."""
    session = _session(
        trip_data={"itineraries": [{"duration_days": 3, "status": "Draft"}]},
        initial_plan_complete=True,
    )
    monkeypatch.setattr(session_module, "decide_route_by_llm", lambda _session, _user_input: "chat")

    def _never_called_plan_trip_edit(*_args, **_kwargs):
        raise AssertionError("an LLM-proposed 'chat' route must never reach the saved-plan edit planner")

    monkeypatch.setattr(session_module, "plan_trip_edit", _never_called_plan_trip_edit)

    class _FakeMessage:
        type = "ai"
        tool_calls = []
        content = "Đây là câu trả lời chung."

    class _ChatAgent:
        def stream(self, *_args, **_kwargs):
            yield {"messages": [_FakeMessage()]}

    session.agent = _ChatAgent()

    result = process_chat_turn(session, "gợi ý thêm cho tôi")

    assert result.tool == "agent_stream"
    assert result.text == "Đây là câu trả lời chung."
    assert session.trip_data is not None  # untouched, not silently reset or edited
    assert session.planning_new_trip is False
