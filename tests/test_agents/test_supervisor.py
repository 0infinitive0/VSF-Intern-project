from __future__ import annotations

import pytest

import src.agents.supervisor as supervisor_module
from src.agents.routing_decision import RouteContext, validate_route
from src.agents.supervisor import _ROUTE_TOOLS, decide_route_by_llm


def _context(**overrides) -> RouteContext:
    defaults = dict(
        has_pending_hotel_selection=False,
        has_trip_data=False,
        is_trip_finalized=False,
        initial_plan_complete=False,
        planning_new_trip=False,
        intake_complete=False,
        hotel_prefs_complete=False,
        has_pending_edit_clarification=False,
    )
    defaults.update(overrides)
    return RouteContext(**defaults)


def test_every_supervisor_tool_has_an_empty_signature():
    """Executable form of the "supervisor cannot emit a fact" guarantee: none
    of the six route tools take any argument for a destination, duration,
    people, or venue to travel through."""
    for route_tool in _ROUTE_TOOLS:
        assert route_tool.args == {}, f"{route_tool.name} must take no arguments"


@pytest.mark.parametrize(
    "route",
    ["select_hotel", "finalize", "new_trip", "edit_draft", "intake", "chat"],
)
def test_each_label_round_trips_through_validation_when_possible(route):
    context = _context(
        has_pending_hotel_selection=(route == "select_hotel"),
        has_trip_data=(route in ("finalize", "edit_draft")),
    )
    assert validate_route(route, context) == route


def test_edit_draft_rejected_without_trip_data():
    context = _context(has_trip_data=False)
    assert validate_route("edit_draft", context) is None


def test_finalize_rejected_on_already_finalized_trip():
    context = _context(has_trip_data=True, is_trip_finalized=True)
    assert validate_route("finalize", context) is None


def test_finalize_rejected_without_trip_data():
    context = _context(has_trip_data=False)
    assert validate_route("finalize", context) is None


def test_select_hotel_rejected_without_a_pending_list():
    context = _context(has_pending_hotel_selection=False)
    assert validate_route("select_hotel", context) is None


def test_unknown_label_is_rejected():
    context = _context()
    assert validate_route("teleport_to_paris", context) is None


class _FakeIntakeState:
    is_complete = False


class _FakeHotelPrefState:
    is_complete = False


class _FakeSession:
    """Minimal stand-in with exactly the attributes route_context_from_session
    reads — decide_route_by_llm builds a state summary from these before ever
    touching the (stubbed) supervisor."""

    def __init__(self, **overrides):
        self.trip_data = None
        self.pending_hotel_selection = None
        self.initial_plan_complete = False
        self.planning_new_trip = False
        self.pending_trip_edit_request = None
        self.intake_state = _FakeIntakeState()
        self.hotel_pref_state = _FakeHotelPrefState()
        self.__dict__.update(overrides)


class _FakeMessage:
    def __init__(self, type_, tool_calls=None):
        self.type = type_
        self.tool_calls = tool_calls or []


class _FakeSupervisor:
    def __init__(self, events):
        self._events = events

    def stream(self, *_args, **_kwargs):
        yield from self._events


def _stub_supervisor(monkeypatch, events):
    monkeypatch.setattr(supervisor_module, "build_supervisor", lambda session: _FakeSupervisor(events))


def test_decide_route_by_llm_extracts_the_first_tool_call(monkeypatch):
    events = [
        {"messages": [_FakeMessage("ai", tool_calls=[{"name": "route_select_hotel"}])]},
    ]
    _stub_supervisor(monkeypatch, events)

    assert decide_route_by_llm(session=_FakeSession(), user_input="1") == "select_hotel"


def test_decide_route_by_llm_takes_only_the_first_call_when_the_model_emits_two(monkeypatch):
    events = [
        {
            "messages": [
                _FakeMessage(
                    "ai",
                    tool_calls=[{"name": "route_finalize"}, {"name": "route_chat"}],
                )
            ]
        },
    ]
    _stub_supervisor(monkeypatch, events)

    assert decide_route_by_llm(session=_FakeSession(), user_input="chốt lịch trình") == "finalize"


def test_decide_route_by_llm_returns_none_when_the_supervisor_raises(monkeypatch):
    class _RaisingSupervisor:
        def stream(self, *_args, **_kwargs):
            raise RuntimeError("Ollama unreachable")

    monkeypatch.setattr(supervisor_module, "build_supervisor", lambda session: _RaisingSupervisor())

    assert decide_route_by_llm(session=_FakeSession(), user_input="bất kỳ gì") is None


def test_decide_route_by_llm_returns_none_for_prose_with_no_tool_call(monkeypatch):
    class _ProseMessage:
        type = "ai"
        tool_calls = []
        content = "Mình chưa hiểu ý bạn."

    events = [{"messages": [_ProseMessage()]}]
    _stub_supervisor(monkeypatch, events)

    assert decide_route_by_llm(session=_FakeSession(), user_input="ừm") is None


def test_decide_route_by_llm_returns_none_for_an_unrecognized_tool_name(monkeypatch):
    events = [
        {"messages": [_FakeMessage("ai", tool_calls=[{"name": "not_a_real_tool"}])]},
    ]
    _stub_supervisor(monkeypatch, events)

    assert decide_route_by_llm(session=_FakeSession(), user_input="gì đó") is None
