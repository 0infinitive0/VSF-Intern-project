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
from src.services.amenity_catalog import AmenityBindingResult, AmenityCatalogEntry
from src.services.hotel_selection import NoHotelsMatchAmenities, NoHotelsMatchRating
from src.services.trip_scheduler import PlaceCandidate


def _unreachable_llm(*_args, **_kwargs):
    raise AssertionError("this scenario must never call the LLM")


def _seeded_travel_state(**extra_changes: object) -> dict:
    # budget.target and preferences.themes are required (but
    # skippable-via-NOT_APPLICABLE) slots ahead of hotel_node in the pipeline
    # (ask_slot -> supervisor) -- seeded here so graph-level tests reach
    # hotel_node instead of stopping to ask for one of them first.
    changes = [
        {"path": "destination", "operation": "set", "value": "Đà Nẵng"},
        {"path": "people", "operation": "set", "value": 2},
        {"path": "dates.start", "operation": "set", "value": "2099-01-01"},
        {"path": "dates.end", "operation": "set", "value": "2099-01-05"},
        {"path": "budget.target", "operation": "set", "value": 1_000_000},
        {"path": "preferences.themes", "operation": "set", "value": None},
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


def test_already_paid_session_declines_before_searching(monkeypatch):
    """The absolute lock (plan 260819-lock-hotel-after-payment): a session
    with a CONFIRMED booking must never let hotel_node touch anything —
    checked before even the destination guard above."""
    monkeypatch.setattr(hotel_node_module.session_store, "session_has_paid_booking", lambda _sid: True)
    monkeypatch.setattr(hotel_node_module, "_get_destination_id", _unreachable_llm)

    result = hotel_node(_graph_state(TravelState().to_dict()))

    assert result["task_results"][-1]["status"] == "already_paid"
    assert result["task_results"][-1]["reply"]
    assert "hotel_node" not in result["pending_tasks"]
    assert result["selected_hotel_id"] is None
    assert "trip_data" not in result
    assert "hotel_search_result" not in result["task_results"][-1]


def test_already_paid_session_declines_a_pending_hotel_selection_too(monkeypatch):
    """Same lock, but hit via the selected_hotel_id branch (POST /hotels/
    select) -- the one branch that can actually overwrite trip_data."""
    monkeypatch.setattr(hotel_node_module.session_store, "session_has_paid_booking", lambda _sid: True)
    monkeypatch.setattr(hotel_node_module, "_handle_hotel_selection", _unreachable_llm)

    state = _graph_state(_seeded_travel_state())
    state["selected_hotel_id"] = "h1"
    state["trip_data"] = {"hotel": {"id": "already-paid-hotel"}}

    result = hotel_node(state)

    assert result["task_results"][-1]["status"] == "already_paid"
    assert result["selected_hotel_id"] is None
    assert "trip_data" not in result


def test_not_paid_session_is_unaffected_by_the_guard(monkeypatch):
    monkeypatch.setattr(hotel_node_module.session_store, "session_has_paid_booking", lambda _sid: False)

    result = hotel_node(_graph_state(TravelState().to_dict()))

    assert result["task_results"][-1]["status"] == "no_destination"


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
    captured: dict = {}

    def _select(*_args, **kwargs):
        captured.update(kwargs)
        return [_option(f"h{index}") for index in range(1, 11)]

    monkeypatch.setattr(hotel_node_module, "_get_destination_id", lambda _d: "dest-1")
    monkeypatch.setattr(hotel_node_module, "select_hotel_candidates", _select)
    monkeypatch.setattr(hotel_node_module, "rank_hotel_candidates", lambda options, **_k: options)

    result = hotel_node(_graph_state(_seeded_travel_state()))

    entry = result["task_results"][-1]
    assert entry["status"] == "ok"
    assert [option["id"] for option in entry["hotel_search_result"]["options"]] == ["h1", "h2", "h3", "h4", "h5"]
    assert captured["match_count"] == 5
    assert result["pending_tasks"] == []


def test_hotel_search_uses_the_requested_result_count(monkeypatch):
    captured: dict = {}

    def _select(*_args, **kwargs):
        captured.update(kwargs)
        return [_option(f"h{index}") for index in range(1, 21)]

    monkeypatch.setattr(hotel_node_module, "_get_destination_id", lambda _d: "dest-1")
    monkeypatch.setattr(hotel_node_module, "select_hotel_candidates", _select)
    monkeypatch.setattr(hotel_node_module, "rank_hotel_candidates", lambda options, **_k: options)

    result = hotel_node(_graph_state(_seeded_travel_state(hotel_preferences__result_count=12)))

    options = result["task_results"][-1]["hotel_search_result"]["options"]
    assert captured["match_count"] == 12
    assert [option["id"] for option in options] == [f"h{index}" for index in range(1, 13)]
    assert result["previous_hotel_search_context"]["result_count"] == 12


def test_preference_update_replaces_retained_cards_with_a_fresh_five(monkeypatch):
    captured: dict = {}

    def _select(*_args, **kwargs):
        captured.update(kwargs)
        return [_option(f"h{index}") for index in range(1, 6)]

    monkeypatch.setattr(hotel_node_module, "_get_destination_id", lambda _d: "dest-1")
    monkeypatch.setattr(hotel_node_module, "select_hotel_candidates", _select)
    monkeypatch.setattr(hotel_node_module, "rank_hotel_candidates", lambda options, **_k: options)

    state = _graph_state(_seeded_travel_state(hotel_preferences__amenities=["spa"]))
    state["previous_hotel_options"] = [
        {**_option(f"old-{index}")[0], "match_score": 0.1, "amenity_match": {"required": ["swimming_pool"]}}
        for index in range(1, 6)
    ]
    state["previous_hotel_search_context"] = {
        "destination_id": "dest-1",
        "start_date": "2099-01-01",
        "end_date": "2099-01-05",
        "people": "2",
    }

    result = hotel_node(state)

    assert "exclude_hotel_ids" not in captured
    assert [option["id"] for option in result["task_results"][-1]["hotel_search_result"]["options"]] == [
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
    ]


def _retained_search_query() -> dict:
    return {
        "destination": "Đà Nẵng",
        "destination_id": "dest-1",
        "people": "2",
        "target_price": 1_000_000,
        "amenity_prefs": [],
        "selection_kwargs": {"match_count": 10},
    }


def test_expand_uses_the_retained_ranked_pool_without_another_search(monkeypatch):
    state = _graph_state(_seeded_travel_state())
    state["expand_hotel_options"] = True
    state["previous_hotel_options"] = [_option(f"h{index}")[0] for index in range(1, 6)]
    state["previous_hotel_candidate_pool"] = [_option(f"h{index}")[0] for index in range(1, 11)]
    state["previous_hotel_search_query"] = _retained_search_query()
    monkeypatch.setattr(hotel_node_module, "select_hotel_candidates", _unreachable_llm)

    result = hotel_node(state)

    entry = result["task_results"][-1]
    assert entry["status"] == "ok"
    assert [option["id"] for option in entry["hotel_search_result"]["options"]] == [
        f"h{index}" for index in range(1, 11)
    ]
    assert entry["hotel_search_result"]["has_more_hotel_options"] is True
    assert [option["id"] for option in result["previous_hotel_options"]] == [
        f"h{index}" for index in range(1, 11)
    ]


def test_expand_fetches_only_after_the_retained_pool_is_exhausted(monkeypatch):
    captured: dict = {}

    def _select(*_args, **kwargs):
        captured.update(kwargs)
        return [_option(f"h{index}") for index in range(11, 21)]

    state = _graph_state(_seeded_travel_state())
    state["expand_hotel_options"] = True
    state["previous_hotel_options"] = [_option(f"h{index}")[0] for index in range(1, 11)]
    state["previous_hotel_candidate_pool"] = [_option(f"h{index}")[0] for index in range(1, 11)]
    state["previous_hotel_search_query"] = _retained_search_query()
    monkeypatch.setattr(hotel_node_module, "select_hotel_candidates", _select)
    monkeypatch.setattr(hotel_node_module, "rank_hotel_candidates", lambda options, **_k: options)

    result = hotel_node(state)

    assert captured["exclude_hotel_ids"] == [f"h{index}" for index in range(1, 11)]
    assert [option["id"] for option in result["task_results"][-1]["hotel_search_result"]["options"]] == [
        f"h{index}" for index in range(1, 16)
    ]
    assert [option["id"] for option in result["previous_hotel_candidate_pool"]] == [
        f"h{index}" for index in range(11, 21)
    ]


def test_expand_marks_the_list_exhausted_when_the_pool_has_fewer_than_five_left(monkeypatch):
    state = _graph_state(_seeded_travel_state())
    state["expand_hotel_options"] = True
    state["previous_hotel_options"] = [_option(f"h{index}")[0] for index in range(1, 6)]
    state["previous_hotel_candidate_pool"] = [_option(f"h{index}")[0] for index in range(1, 7)]
    state["previous_hotel_search_query"] = _retained_search_query()
    monkeypatch.setattr(hotel_node_module, "select_hotel_candidates", _unreachable_llm)

    result = hotel_node(state)

    search_result = result["task_results"][-1]["hotel_search_result"]
    assert [option["id"] for option in search_result["options"]] == [f"h{index}" for index in range(1, 7)]
    assert search_result["has_more_hotel_options"] is False


def test_expand_with_no_active_hotel_search_is_a_no_op(monkeypatch):
    state = _graph_state(_seeded_travel_state())
    state["expand_hotel_options"] = True
    monkeypatch.setattr(hotel_node_module, "select_hotel_candidates", _unreachable_llm)

    result = hotel_node(state)

    assert result["task_results"][-1]["status"] == "no_active_hotel_search"
    assert "hotel_search_result" not in result["task_results"][-1]


def test_hotel_search_uses_catalog_ids_for_chat_amenity_aliases(monkeypatch):
    captured: dict = {}

    def _select(*_args, **kwargs):
        captured.update(kwargs)
        return [_option("h1")]

    monkeypatch.setattr(hotel_node_module, "_get_destination_id", lambda _d: "dest-1")
    monkeypatch.setattr(
        hotel_node_module,
        "resolve_hotel_amenity_ids",
        lambda _values: AmenityBindingResult(ids=("swimming_pool",), unresolved=("unknown amenity",)),
    )
    monkeypatch.setattr(
        hotel_node_module,
        "all_approved_amenities",
        lambda: (AmenityCatalogEntry(id="swimming_pool", label="Hồ bơi", match_keywords=()),),
    )
    monkeypatch.setattr(hotel_node_module, "select_hotel_candidates", _select)
    monkeypatch.setattr(hotel_node_module, "rank_hotel_candidates", lambda options, **_k: options)

    result = hotel_node(_graph_state(_seeded_travel_state(hotel_preferences__amenities=["pool", "unknown amenity"])))

    assert captured["required_amenities"] == ["swimming_pool"]
    upgraded_records = result["travel_state"]["hotel_preferences.amenities"]["value"]
    assert upgraded_records == [{
        "id": "swimming_pool", "label": "Hồ bơi", "polarity": "require",
        "source_phrase": "pool", "confidence": 1.0, "active": True,
    }]
    # Catalog-resolved Vietnamese label, not the raw internal ID (bug fix:
    # active_preferences used to leak "swimming_pool" straight to the user).
    assert result["task_results"][-1]["hotel_search_result"]["active_preferences"] == [
        {"id": "swimming_pool", "label": "Hồ bơi", "polarity": "require", "active": True}
    ]
    # The unresolved term is surfaced to the user, not silently dropped.
    assert "unknown amenity" in result["task_results"][-1]["reply"]


def test_zero_results_is_a_generic_no_results_status(monkeypatch):
    monkeypatch.setattr(hotel_node_module, "_get_destination_id", lambda _d: "dest-1")
    monkeypatch.setattr(hotel_node_module, "select_hotel_candidates", lambda *_a, **_k: [])

    result = hotel_node(_graph_state(_seeded_travel_state()))

    assert result["task_results"][-1]["status"] == "no_results"


def test_dates_causing_zero_results_gets_a_date_specific_reply(monkeypatch):
    """Bug fix: a destination with real inventory but no availability for the
    requested dates used to get the same generic "no hotel found" message as
    a destination with zero hotels at all. The dateless fallback isolates
    the cause and reports it specifically."""

    def _select(*_args, **kwargs):
        if kwargs.get("start_date") or kwargs.get("end_date"):
            return []
        return [_option("h1")]

    monkeypatch.setattr(hotel_node_module, "_get_destination_id", lambda _d: "dest-1")
    monkeypatch.setattr(hotel_node_module, "select_hotel_candidates", _select)

    result = hotel_node(_graph_state(_seeded_travel_state()))

    entry = result["task_results"][-1]
    assert entry["status"] == "no_results_dates"
    assert "Đà Nẵng" in entry["reply"]


def test_amenity_binding_constraint_names_the_tag_in_the_reply(monkeypatch):
    def _raise(*_a, **_k):
        raise NoHotelsMatchAmenities({"gym": 3, "pool": 0})

    monkeypatch.setattr(hotel_node_module, "_get_destination_id", lambda _d: "dest-1")
    monkeypatch.setattr(hotel_node_module, "select_hotel_candidates", _raise)
    monkeypatch.setattr(
        hotel_node_module,
        "all_approved_amenities",
        lambda: (AmenityCatalogEntry(id="gym", label="Phòng tập", match_keywords=()),),
    )

    travel_state = _seeded_travel_state(hotel_preferences__amenities=["gym", "pool"])
    result = hotel_node(_graph_state(travel_state))

    entry = result["task_results"][-1]
    assert entry["status"] == "no_results_amenities"
    # Catalog-resolved Vietnamese label, not the raw internal ID (bug fix:
    # the reply used to leak "gym"/"breakfast"-style raw tags verbatim).
    # "pool" has no catalog entry in this fixture, so it falls back to the
    # raw tag -- exactly the documented behavior for an unresolvable ID.
    assert "Phòng tập" in entry["reply"]
    assert "pool" in entry["reply"]
    assert "gym" not in entry["reply"]


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


# ---------------------------------------------------------------------------
# `exclude_hotel_ids` must never decide a constraint is unsatisfiable.
#
# It exists so a follow-up search APPENDS unseen hotels instead of re-listing
# what is already on screen. But the hotels it hides are exactly the ones that
# satisfied the filter, so when they were the only matches the search came
# back empty and the binding-constraint diagnostic -- computed over that
# emptied set -- told the user no hotel in the city had the amenity.
#
# Reported as an "unstable search": Nha Trang 1-4/7 with a breakfast filter
# returned one hotel, then minutes later "không có khách sạn nào ... Bao gồm
# bữa sáng". Deterministic, not flaky.
# ---------------------------------------------------------------------------


def test_non_expand_searches_do_not_exclude_existing_hotels(monkeypatch):
    calls: list[dict] = []

    def _select(*_args, **kwargs):
        calls.append(kwargs)
        if kwargs.get("exclude_hotel_ids"):
            raise NoHotelsMatchAmenities(tag_drop_counts={"breakfast": 0})
        return [_option("h1")]

    monkeypatch.setattr(hotel_node_module, "_get_destination_id", lambda _d: "dest-1")
    monkeypatch.setattr(hotel_node_module, "select_hotel_candidates", _select)

    state = _graph_state(_seeded_travel_state(hotel_preferences__amenities=["breakfast"]))
    state["previous_hotel_options"] = [{"id": "h1", "name": "Hotel h1", "rank": 1}]
    # A normal fresh search must rank the full candidate set.  Only the explicit
    # expand path is allowed to exclude cards already displayed.
    state["previous_hotel_search_context"] = {
        "destination_id": "dest-1",
        "start_date": "2099-01-01",
        "end_date": "2099-01-05",
        "people": "2",
    }

    result = hotel_node(state)

    entry = result["task_results"][-1]
    assert entry["status"] == "ok", f"still reported a binding constraint: {entry}"
    assert len(calls) == 1
    assert "exclude_hotel_ids" not in calls[0]
    assert calls[0]["required_amenities"] == ["breakfast"]


def test_a_genuinely_unsatisfiable_filter_still_reports_the_constraint(monkeypatch):
    """The retry must not paper over a real zero-result: with nothing shown
    yet there is no exclusion to blame, so the diagnostic stands."""

    def _select(*_args, **_kwargs):
        raise NoHotelsMatchAmenities(tag_drop_counts={"breakfast": 0})

    monkeypatch.setattr(hotel_node_module, "_get_destination_id", lambda _d: "dest-1")
    monkeypatch.setattr(hotel_node_module, "select_hotel_candidates", _select)

    result = hotel_node(_graph_state(_seeded_travel_state(hotel_preferences__amenities=["breakfast"])))

    assert result["task_results"][-1]["status"] == "no_results_amenities"


# --- Picking a hotel by typing, not clicking ---------------------------------
#
# Trace 01a0235b-538f-75f3-a70d-5e5c5192c719: "chọn khách sạn đầu tiên"
# extracted as `select_hotel` with an empty patch, `selected_hotel_id` stayed
# None (only POST /hotels/select ever set it), and the turn fell through to
# the search branch -- the user asked to pick and got "Mình tìm được 15 khách
# sạn phù hợp", the same list again.
#
# `pick_shown_option` is stubbed here: which sentence maps to which card is
# its own module's contract (`test_shortlist_pick.py`). What these lock is
# what this node does with each answer it can give.


_SHOWN = [
    {"id": "h-horizon", "name": "Horizon Hotel Apartment"},
    {"id": "h-hoabinh", "name": "Khách sạn Hòa Bình"},
]


def _pick_state(message: str, options: list[dict]) -> dict:
    state = _graph_state(_seeded_travel_state(), message=message)
    state["intent"] = "select_hotel"
    state["previous_hotel_options"] = options
    return state


def _capturing_selection(captured: dict):
    def _fake_selection(**kwargs):
        captured.update(kwargs)
        return {"hotel": {"id": kwargs["hotel_id"]}}, "Đã chọn khách sạn."

    return _fake_selection


def test_a_resolved_position_reaches_the_selection_branch(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(hotel_node_module, "_handle_hotel_selection", _capturing_selection(captured))
    monkeypatch.setattr(hotel_node_module, "pick_shown_option", lambda _msg, _options: 1)

    result = hotel_node(_pick_state("chọn khách sạn đầu tiên", _SHOWN))

    assert captured["hotel_id"] == "h-horizon"
    assert result["task_results"][-1]["status"] == "hotel_selected"
    assert result["trip_data"] == {"hotel": {"id": "h-horizon"}}


def test_the_position_maps_to_the_card_at_that_place_in_the_list(monkeypatch):
    """Position, not `rank`: the cards are numbered by enumerating this list,
    and it is merged across searches, so a card's own `rank` field can no
    longer match the number printed on it."""
    captured: dict = {}
    monkeypatch.setattr(hotel_node_module, "_handle_hotel_selection", _capturing_selection(captured))
    monkeypatch.setattr(hotel_node_module, "pick_shown_option", lambda _msg, _options: 2)

    hotel_node(_pick_state("cho mình Hòa Bình", _SHOWN))

    assert captured["hotel_id"] == "h-hoabinh"


def test_an_unresolved_pick_asks_instead_of_searching_again(monkeypatch):
    """The reported failure mode: answering a pick with a fresh search."""
    monkeypatch.setattr(hotel_node_module, "_handle_hotel_selection", _unreachable_llm)
    monkeypatch.setattr(hotel_node_module, "select_hotel_candidates", _unreachable_llm)
    monkeypatch.setattr(hotel_node_module, "pick_shown_option", lambda _msg, _options: None)

    result = hotel_node(_pick_state("chọn khách sạn nào cũng được", _SHOWN))

    assert result["task_results"][-1]["status"] == "selection_unresolved"
    assert "số thứ tự" in result["task_results"][-1]["reply"]
    assert "trip_data" not in result


def test_select_intent_with_no_cards_yet_still_searches(monkeypatch):
    """No shortlist means there is nothing to pick FROM — searching is the
    right answer, and neither the picker nor the ask-which-one branch runs."""
    calls: list = []

    def _fake_search(*args, **kwargs):
        calls.append(kwargs)
        raise NoHotelsMatchRating(4)

    monkeypatch.setattr(hotel_node_module, "select_hotel_candidates", _fake_search)
    monkeypatch.setattr(hotel_node_module, "pick_shown_option", _unreachable_llm)

    result = hotel_node(_pick_state("chọn khách sạn số 1", []))

    assert calls, "the search branch must still run"
    assert result["task_results"][-1]["status"] != "selection_unresolved"


def test_a_non_select_intent_never_consults_the_picker(monkeypatch):
    """A search turn with cards already on screen must not be re-read as a
    pick — the picker is gated on the extractor's own intent."""
    monkeypatch.setattr(hotel_node_module, "pick_shown_option", _unreachable_llm)
    monkeypatch.setattr(hotel_node_module, "select_hotel_candidates", lambda *a, **k: [])

    state = _pick_state("tìm khách sạn rẻ hơn", _SHOWN)
    state["intent"] = "hotel_search"

    hotel_node(state)
