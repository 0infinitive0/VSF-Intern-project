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

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

import src.agents.graph.subgraphs.rebuild_day as rebuild_day_module
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
