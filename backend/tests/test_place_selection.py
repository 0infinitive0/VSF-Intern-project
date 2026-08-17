"""Phase 13 (`phase-13-place-search.md`): suggest-before-replace's shortlist
interrupt, which lives inside `rebuild_day.fetch_and_schedule_node` (never
`itinerary_node` -- an interrupt there would re-run day selection and
`plan_trip_edit` on resume, see the plan's Architecture section).

Runs the REAL compiled subgraph through an actual interrupt/resume cycle
(`Command(resume=...)`), mirroring `test_rebuild_day.py`'s and
`test_hotel_node.py`'s established pattern for interrupt-driven paths --
directly calling the node function can't exercise `interrupt()` at all,
since it raises a control-flow exception that only a running graph catches.
"""

from __future__ import annotations

import json

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

import src.agents.graph.subgraphs.rebuild_day as rebuild_day_module
from src.agents.graph.nodes.itinerary_node import itinerary_node
from src.agents.graph.state import TravelGraphState, initial_graph_state
from src.agents.graph.subgraphs.rebuild_day import build_rebuild_day_subgraph
from src.services.trip_scheduler import PlaceCandidate

_CANDIDATES = [
    PlaceCandidate(id="attr-1", name="Nhà hàng Biển Xanh", description="Hải sản tươi"),
    PlaceCandidate(id="attr-2", name="Quán Cơm Nhà", description="Cơm Việt bình dân"),
]


def _trip_data() -> dict:
    return {
        "hotel": {"id": "hotel-1", "coordinates": "16.05,108.2"},
        "itineraries": [{"duration_days": 1}],
        "itinerary_items": [{"id": "item-lunch-1", "day_number": 1, "kind": "lunch"}],
    }


def _suggest_task(item_id: str = "item-lunch-1", item_kind: str = "lunch", query: str = "quán ăn trưa hải sản") -> dict:
    return {"target": {"item_id": item_id}, "requirements": {"item_kind": item_kind, "semantic_query": query}}


def test_shortlist_pauses_with_numbered_options(monkeypatch):
    monkeypatch.setattr(rebuild_day_module, "search_attraction_candidates", lambda *_a, **_kw: _CANDIDATES)
    monkeypatch.setattr(rebuild_day_module, "_current_trip_parameters", lambda _data: ("Đà Nẵng", "1", "2", ""))
    monkeypatch.setattr(rebuild_day_module, "_get_destination_id", lambda _name: "dest-1")

    subgraph = build_rebuild_day_subgraph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "t-pause"}}

    result = subgraph.invoke(
        {
            "trip_data": _trip_data(),
            "day_number": 1,
            "day_theme": {},
            "locked_days": [],
            "suggest_operations": [_suggest_task()],
        },
        config=config,
    )

    assert "__interrupt__" in result, "must pause instead of picking silently"
    payload = result["__interrupt__"][0].value
    assert payload["type"] == "place_selection"
    assert [opt["id"] for opt in payload["options"]] == ["attr-1", "attr-2"]
    assert "1. Nhà hàng Biển Xanh" in payload["message"]
    assert "2. Quán Cơm Nhà" in payload["message"]


def test_shortlist_search_supplies_max_radius_km_alongside_hotel_coordinates(monkeypatch):
    """search_attraction_candidates requires all of root_latitude/root_longitude/
    max_radius_km together (validate_radius_filter) or none of them. _trip_data's
    hotel has coordinates, so max_radius_km must accompany them here -- omitting
    it raised ValueError on every suggest_operations search, caught by
    fetch_and_schedule_node's except Exception and surfaced as rebuild_error
    instead of a pause, so this regresses as a missing __interrupt__ too."""
    captured: dict = {}

    def _capturing_search(_query, _destination_id, *, match_count, root_latitude, root_longitude, max_radius_km):
        captured.update(
            match_count=match_count, root_latitude=root_latitude,
            root_longitude=root_longitude, max_radius_km=max_radius_km,
        )
        return _CANDIDATES

    monkeypatch.setattr(rebuild_day_module, "search_attraction_candidates", _capturing_search)
    monkeypatch.setattr(rebuild_day_module, "_current_trip_parameters", lambda _data: ("Đà Nẵng", "1", "2", ""))
    monkeypatch.setattr(rebuild_day_module, "_get_destination_id", lambda _name: "dest-1")

    subgraph = build_rebuild_day_subgraph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "t-radius"}}

    result = subgraph.invoke(
        {
            "trip_data": _trip_data(),
            "day_number": 1,
            "day_theme": {},
            "locked_days": [],
            "suggest_operations": [_suggest_task()],
        },
        config=config,
    )

    assert "__interrupt__" in result, f"expected a pause, got rebuild_error={result.get('rebuild_error')!r}"
    assert captured["root_latitude"] == 16.05
    assert captured["root_longitude"] == 108.2
    assert captured["max_radius_km"] == rebuild_day_module.DEFAULT_NEARBY_SEARCH_RADIUS_KM


def test_resume_by_rank_number_applies_the_picked_candidate_not_a_research(monkeypatch):
    monkeypatch.setattr(rebuild_day_module, "search_attraction_candidates", lambda *_a, **_kw: _CANDIDATES)
    monkeypatch.setattr(rebuild_day_module, "_current_trip_parameters", lambda _data: ("Đà Nẵng", "1", "2", ""))
    monkeypatch.setattr(rebuild_day_module, "_get_destination_id", lambda _name: "dest-1")

    applied: list = []

    def _spy_apply(_current_data, operation):
        applied.append(operation)
        return [f"applied {operation.preselected_candidate.name}"]

    monkeypatch.setattr(rebuild_day_module, "_apply_replace_or_add", _spy_apply)

    subgraph = build_rebuild_day_subgraph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "t-resume"}}

    subgraph.invoke(
        {
            "trip_data": _trip_data(),
            "day_number": 1,
            "day_theme": {},
            "locked_days": [],
            "suggest_operations": [_suggest_task()],
        },
        config=config,
    )
    result = subgraph.invoke(Command(resume="2"), config=config)

    assert "__interrupt__" not in result
    assert result.get("rebuild_error") is None
    assert len(applied) == 1, "the resolved candidate must be applied via _apply_replace_or_add, not re-searched"
    op = applied[0]
    assert op.operation == "replace_item"
    assert op.preselected_candidate.id == "attr-2", "rank '2' must resolve to the second listed option"
    assert op.target.item_id == "item-lunch-1"
    assert op.target.day_number == 1
    assert op.requirements.item_kind == "lunch"


def test_unresolved_resume_reply_skips_the_operation_without_crashing(monkeypatch):
    monkeypatch.setattr(rebuild_day_module, "search_attraction_candidates", lambda *_a, **_kw: _CANDIDATES)
    monkeypatch.setattr(rebuild_day_module, "_current_trip_parameters", lambda _data: ("Đà Nẵng", "1", "2", ""))
    monkeypatch.setattr(rebuild_day_module, "_get_destination_id", lambda _name: "dest-1")

    applied: list = []
    monkeypatch.setattr(rebuild_day_module, "_apply_replace_or_add", lambda *_a: applied.append(1) or [])

    subgraph = build_rebuild_day_subgraph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "t-unresolved"}}

    subgraph.invoke(
        {
            "trip_data": _trip_data(),
            "day_number": 1,
            "day_theme": {},
            "locked_days": [],
            "suggest_operations": [_suggest_task()],
        },
        config=config,
    )
    result = subgraph.invoke(Command(resume="thôi khỏi cần"), config=config)

    assert "__interrupt__" not in result
    assert result.get("rebuild_error") is None
    assert applied == [], "an unrecognized reply must not apply any candidate"


def test_interrupt_is_never_swallowed_as_a_generic_failure(monkeypatch):
    """Regression: the suggest-flow's try/except previously caught
    `GraphInterrupt` (a subclass of `Exception`) as a generic failure,
    turning every shortlist pause into a `rebuild_error` and breaking the
    whole flow. Asserting no `rebuild_error` on the FIRST (pausing) call is
    the direct proof this doesn't regress."""
    monkeypatch.setattr(rebuild_day_module, "search_attraction_candidates", lambda *_a, **_kw: _CANDIDATES)
    monkeypatch.setattr(rebuild_day_module, "_current_trip_parameters", lambda _data: ("Đà Nẵng", "1", "2", ""))
    monkeypatch.setattr(rebuild_day_module, "_get_destination_id", lambda _name: "dest-1")

    subgraph = build_rebuild_day_subgraph(checkpointer=MemorySaver())
    result = subgraph.invoke(
        {
            "trip_data": _trip_data(),
            "day_number": 1,
            "day_theme": {},
            "locked_days": [],
            "suggest_operations": [_suggest_task()],
        },
        config={"configurable": {"thread_id": "t-not-swallowed"}},
    )
    assert result.get("rebuild_error") is None
    assert "__interrupt__" in result


# ---------------------------------------------------------------------------
# Through the parent turn — the path the API actually runs
# ---------------------------------------------------------------------------


def _parent_graph():
    """A one-node stand-in for the real graph: enough to run `itinerary_node`
    the way a turn does, with a checkpointer, so `interrupt()` and
    `Command(resume=...)` behave as they do in `_run_turn_via_graph`."""
    builder: StateGraph = StateGraph(TravelGraphState)
    builder.add_node("itinerary", itinerary_node)
    builder.add_edge(START, "itinerary")
    builder.add_edge("itinerary", END)
    return builder.compile(checkpointer=MemorySaver())


def _turn_state() -> TravelGraphState:
    state = initial_graph_state("s-place")
    state.update(
        trip_data=_trip_data(),
        task_description=json.dumps({"action": "rebuild_days", "day_numbers": [1]}),
        pending_suggest_operations=[_suggest_task()],
        pending_tasks=["itinerary_node"],
    )
    return state


def test_shortlist_reaches_the_user_and_the_pick_applies_through_the_parent_turn(monkeypatch):
    """Regression: `_invoke_rebuild_day` used to hand the subgraph its own
    `uuid4` thread_id. That detached it from the turn, so the subgraph caught
    its own `GraphInterrupt` and returned `__interrupt__` in the result dict
    — the parent saw a normal return, the shortlist question never reached
    the user, and the suggest operation was dropped without a trace."""
    monkeypatch.setattr(rebuild_day_module, "search_attraction_candidates", lambda *_a, **_kw: _CANDIDATES)
    monkeypatch.setattr(rebuild_day_module, "_current_trip_parameters", lambda _data: ("Đà Nẵng", "1", "2", ""))
    monkeypatch.setattr(rebuild_day_module, "_get_destination_id", lambda _name: "dest-1")

    applied: list = []
    monkeypatch.setattr(
        rebuild_day_module,
        "_apply_replace_or_add",
        lambda _data, operation: applied.append(operation) or ["applied"],
    )

    app = _parent_graph()
    config = {"configurable": {"thread_id": "parent-place-1"}}

    paused = app.invoke(_turn_state(), config=config)

    interrupts = paused.get("__interrupt__")
    assert interrupts, "the shortlist must surface as an interrupt on the PARENT turn"
    assert interrupts[0].value["type"] == "place_selection"
    assert applied == [], "nothing may be applied before the user answers"

    resumed = app.invoke(Command(resume="2"), config=config)

    assert "__interrupt__" not in resumed, "the answered turn must not pause again"
    assert len(applied) == 1, "the user's pick must be applied exactly once"
    assert applied[0].preselected_candidate.id == "attr-2"
