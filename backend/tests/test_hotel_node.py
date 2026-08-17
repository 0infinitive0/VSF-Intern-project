"""Phase 8 (260812-0927-langgraph-orchestration-state-patch-and-interrupts):
`hotel_node` — hard filters, radius, center. Direct unit tests exercise the
non-interrupting paths (missing destination, unknown destination, success,
zero-result variants) by calling the node function directly; the radius/
center-ask paths call `interrupt()`, so those are driven through the real
compiled graph via `Command(resume=...)`, mirroring
`test_interrupt_resume.py`'s established pattern for `validate_patch`.
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage
from langgraph.types import Command

import src.agents.graph.graph as graph_module
import src.agents.graph.nodes.hotel_node as hotel_node_module
import src.agents.graph.nodes.supervisor as supervisor_module
import src.services.search_center as search_center_module
from src.agents.graph.nodes.hotel_node import hotel_node
from src.domain.travel_state import TravelState, apply_patch
from src.services.hotel_selection import NoHotelsMatchAmenities, NoHotelsMatchRating
from src.services.trip_scheduler import PlaceCandidate


def _unreachable_llm(*_args, **_kwargs):
    raise AssertionError("this scenario must never call the LLM")


def _seeded_travel_state(**extra_changes: object) -> dict:
    # budget.target is a required (but skippable-via-NOT_APPLICABLE) slot
    # ahead of hotel_node in the pipeline (ask_slot -> supervisor) -- seeded
    # here so graph-level tests reach hotel_node instead of stopping to ask
    # for a budget first.
    changes = [
        {"path": "destination", "operation": "set", "value": "Đà Nẵng"},
        {"path": "people", "operation": "set", "value": 2},
        {"path": "dates.start", "operation": "set", "value": "2099-01-01"},
        {"path": "dates.end", "operation": "set", "value": "2099-01-05"},
        {"path": "budget.target", "operation": "set", "value": 1_000_000},
    ]
    for path, value in extra_changes.items():
        changes.append({"path": path.replace("__", "."), "operation": "set", "value": value})
    return apply_patch(TravelState(), changes).state.to_dict()


def _graph_state(travel_state: dict, message: str = "tìm khách sạn") -> dict:
    return {
        "session_id": "s1",
        "language": "vi",
        "messages": [HumanMessage(content=message)],
        "travel_state": travel_state,
        "pending_tasks": ["hotel_node"],
        "task_results": [],
    }


def _option(id_: str) -> tuple[dict, PlaceCandidate]:
    data = {
        "id": id_,
        "destination_id": "dest-1",
        "name": f"Hotel {id_}",
        "star_rating": 4,
        "coordinates": "16.05,108.2",
        "matched_rooms": [],
        "covered_meals": [],
        "review_score": 8.0,
        "amenities": [],
        "similarity": 0.7,
    }
    return data, PlaceCandidate.from_mapping({**data, "category": "Hotel"})


class _FakeQuery:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def limit(self, _n: int) -> _FakeQuery:
        return self

    def execute(self) -> _FakeResult:
        return _FakeResult(self._rows)


class _FakeResult:
    def __init__(self, data: list[dict]) -> None:
        self.data = data


class _FakeTable:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def select(self, *_args, **_kwargs) -> _FakeTable:
        return self

    def eq(self, column: str, value) -> _FakeTable:
        return _FakeTable([row for row in self._rows if row.get(column) == value])

    def ilike(self, column: str, pattern: str) -> _FakeQuery:
        needle = pattern.strip("%").casefold()
        return _FakeQuery([row for row in self._rows if needle in str(row.get(column, "")).casefold()])


class _FakeSupabaseClient:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def table(self, _name: str) -> _FakeTable:
        return _FakeTable(self._rows)


# --- direct unit tests: no interrupt involved -------------------------------


def test_missing_destination_returns_defensive_message_and_completes():
    state = _graph_state(TravelState().to_dict())

    result = hotel_node(state)

    assert result["task_results"][-1]["status"] == "no_destination"
    assert "hotel_node" not in result["pending_tasks"]


def test_unknown_destination_id_returns_error(monkeypatch):
    monkeypatch.setattr(hotel_node_module, "_get_destination_id", lambda _d: None)

    result = hotel_node(_graph_state(_seeded_travel_state()))

    assert result["task_results"][-1]["status"] == "unknown_destination"


def test_successful_search_populates_hotel_search_result_for_respond(monkeypatch):
    monkeypatch.setattr(hotel_node_module, "_get_destination_id", lambda _d: "dest-1")
    monkeypatch.setattr(hotel_node_module, "select_hotel_candidates", lambda *_a, **_k: [_option("h1")])
    monkeypatch.setattr(hotel_node_module, "rank_hotel_candidates", lambda options, **_k: options)

    result = hotel_node(_graph_state(_seeded_travel_state()))

    entry = result["task_results"][-1]
    assert entry["status"] == "ok"
    assert entry["hotel_search_result"]["options"][0]["id"] == "h1"
    assert result["pending_tasks"] == []


def test_zero_results_is_a_generic_no_results_status(monkeypatch):
    monkeypatch.setattr(hotel_node_module, "_get_destination_id", lambda _d: "dest-1")
    monkeypatch.setattr(hotel_node_module, "select_hotel_candidates", lambda *_a, **_k: [])

    result = hotel_node(_graph_state(_seeded_travel_state()))

    assert result["task_results"][-1]["status"] == "no_results"


def test_amenity_binding_constraint_names_the_tag_in_the_reply(monkeypatch):
    def _raise(*_a, **_k):
        raise NoHotelsMatchAmenities({"gym": 3, "pool": 0})

    monkeypatch.setattr(hotel_node_module, "_get_destination_id", lambda _d: "dest-1")
    monkeypatch.setattr(hotel_node_module, "select_hotel_candidates", _raise)

    travel_state = _seeded_travel_state(hotel_preferences__amenities=["gym", "pool"])
    result = hotel_node(_graph_state(travel_state))

    entry = result["task_results"][-1]
    assert entry["status"] == "no_results_amenities"
    assert "gym" in entry["reply"]


def test_rating_zero_results_reports_the_threshold_not_a_widened_list(monkeypatch):
    def _raise(*_a, **_k):
        raise NoHotelsMatchRating(min_star_rating=4, min_review_score=None)

    monkeypatch.setattr(hotel_node_module, "_get_destination_id", lambda _d: "dest-1")
    monkeypatch.setattr(hotel_node_module, "select_hotel_candidates", _raise)

    travel_state = _seeded_travel_state(hotel_preferences__min_star_rating=4)
    result = hotel_node(_graph_state(travel_state))

    entry = result["task_results"][-1]
    assert entry["status"] == "no_results_rating"
    assert "hotel_search_result" not in entry


def test_radius_forwarded_when_center_already_resolved_no_reask(monkeypatch):
    captured: dict = {}

    def _fake_select(*_args, **kwargs):
        captured.update(kwargs)
        return [_option("h1")]

    monkeypatch.setattr(hotel_node_module, "_get_destination_id", lambda _d: "dest-1")
    monkeypatch.setattr(hotel_node_module, "select_hotel_candidates", _fake_select)
    monkeypatch.setattr(hotel_node_module, "rank_hotel_candidates", lambda options, **_k: options)

    travel_state = _seeded_travel_state(hotel_preferences__radius_km=3, hotel_preferences__center="16.05,108.2")
    result = hotel_node(_graph_state(travel_state))

    assert captured["root_latitude"] == 16.05
    assert captured["root_longitude"] == 108.2
    assert captured["max_radius_km"] == 3
    # Center was already resolved from a prior turn -- no state rewrite needed.
    assert "travel_state" not in result


# --- interrupt/resume through the real compiled graph -----------------------


def test_radius_without_center_or_named_place_pauses_and_asks(monkeypatch):
    def _fake_extract_patch(_state):
        return {"patch": [{"path": "hotel_preferences.radius_km", "operation": "set", "value": 3}]}

    monkeypatch.setattr(graph_module, "extract_patch", _fake_extract_patch)
    monkeypatch.setattr(supervisor_module, "get_fast_llm", _unreachable_llm)
    monkeypatch.setattr(hotel_node_module, "_get_destination_id", lambda _d: "dest-1")
    monkeypatch.setattr(search_center_module, "get_supabase_client", lambda: _FakeSupabaseClient([]))

    app = graph_module.build_graph()
    config = {"configurable": {"thread_id": "test-radius-ask"}}

    paused = app.invoke(
        {
            "session_id": "s1",
            "language": "vi",
            "travel_state": _seeded_travel_state(),
            "messages": [HumanMessage(content="Tìm khách sạn trong bán kính 3km")],
        },
        config=config,
    )

    assert "__interrupt__" in paused
    payload = paused["__interrupt__"][0].value
    assert payload["kind"] == "hotel_radius_center"


def test_radius_resumed_with_a_named_place_completes_the_search(monkeypatch):
    def _fake_extract_patch(_state):
        return {"patch": [{"path": "hotel_preferences.radius_km", "operation": "set", "value": 3}]}

    monkeypatch.setattr(graph_module, "extract_patch", _fake_extract_patch)
    monkeypatch.setattr(supervisor_module, "get_fast_llm", _unreachable_llm)
    monkeypatch.setattr(hotel_node_module, "_get_destination_id", lambda _d: "dest-1")
    monkeypatch.setattr(
        search_center_module,
        "get_supabase_client",
        lambda: _FakeSupabaseClient(
            [{"id": "a1", "destination_id": "dest-1", "name": "Bà Nà Hills", "coordinates": "15.9977,107.9857"}]
        ),
    )
    captured: dict = {}

    def _fake_select(*_args, **kwargs):
        captured.update(kwargs)
        return [_option("h1")]

    monkeypatch.setattr(hotel_node_module, "select_hotel_candidates", _fake_select)
    monkeypatch.setattr(hotel_node_module, "rank_hotel_candidates", lambda options, **_k: options)

    app = graph_module.build_graph()
    config = {"configurable": {"thread_id": "test-radius-resume"}}

    app.invoke(
        {
            "session_id": "s1",
            "language": "vi",
            "travel_state": _seeded_travel_state(),
            "messages": [HumanMessage(content="Tìm khách sạn trong bán kính 3km")],
        },
        config=config,
    )
    resumed = app.invoke(Command(resume="Bà Nà Hills"), config=config)

    assert "__interrupt__" not in resumed
    assert captured["root_latitude"] == 15.9977
    assert captured["root_longitude"] == 107.9857
    assert resumed["travel_state"]["hotel_preferences.center"]["value"] == "15.9977,107.9857"


def test_radius_resumed_with_an_unrelated_reply_is_replayed_as_a_fresh_turn(monkeypatch):
    """The 'different intent' case: a reply to "Bán kính 3km tính từ đâu?"
    that answers something else entirely (a budget change) must reach
    extract_patch, not be swallowed as a failed place-name lookup."""

    def _fake_extract_patch(state):
        text = str(state["messages"][-1].content)
        if "km" in text:
            return {"patch": [{"path": "hotel_preferences.radius_km", "operation": "set", "value": 3}]}
        return {"patch": [{"path": "budget.max", "operation": "set", "value": 2_000_000}]}

    monkeypatch.setattr(graph_module, "extract_patch", _fake_extract_patch)
    monkeypatch.setattr(supervisor_module, "get_fast_llm", _unreachable_llm)
    monkeypatch.setattr(hotel_node_module, "_get_destination_id", lambda _d: "dest-1")
    monkeypatch.setattr(search_center_module, "get_supabase_client", lambda: _FakeSupabaseClient([]))
    monkeypatch.setattr(hotel_node_module, "select_hotel_candidates", lambda *_a, **_k: [])

    app = graph_module.build_graph()
    config = {"configurable": {"thread_id": "test-radius-different-intent"}}

    app.invoke(
        {
            "session_id": "s1",
            "language": "vi",
            "travel_state": _seeded_travel_state(),
            "messages": [HumanMessage(content="Tìm khách sạn trong bán kính 3km")],
        },
        config=config,
    )
    resumed = app.invoke(Command(resume="đổi ngân sách xuống 2 triệu"), config=config)

    assert "__interrupt__" not in resumed
    unresolved = resumed["unresolved_resume_text"]
    assert unresolved == "đổi ngân sách xuống 2 triệu"

    # This is what api/routes.py::_run_turn_via_graph does with it.
    final = app.invoke(
        {"session_id": "s1", "language": "vi", "messages": [HumanMessage(content=unresolved)]},
        config=config,
    )

    assert final["travel_state"]["budget.max"]["value"] == 2_000_000
