"""Production coverage of the agent-visible recommend_hotels/select_hotel tools
and their trip_planner helpers (generate_full_itinerary, _legacy_modify_trip_plan).

Backfills tests/test_planner_tools_hotel_flow.py, deleted in Phase 1 of
260802-1437-langgraph-full-orchestration-and-durable-state as part of the
src/cli fork cleanup. That file was misleadingly named after the fork but
actually exercised this production code — the recommend_hotels/select_hotel
pair enforcing the hotel-pick gate is the single highest-risk area of the
LangGraph migration (see plan risk R1), so this ground is restored here under
an accurate name rather than left uncovered. Two tests from the original file
are NOT restored: they referenced `planner_tools_module` and
`PENDING_HOTEL_SELECTION_FILE`, both from the deleted CLI fork, and a
`root_latitude`/`max_radius_km` radius-filter feature the current
recommend_hotels tool does not implement — they were already failing before
deletion.

Updated for Phase 4 (same plan): recommend_hotels/select_hotel are now
module-level `ToolRuntime`/`Command` tools with no session reference, driven
here via `invoke_tool_directly` — the same adapter
`process_chat_turn`'s deterministic cascade uses — against a plain
`TripState` dict instead of a session double. `generate_full_itinerary` and
`_legacy_modify_trip_plan` are untouched plain functions in trip_planner.py,
unaffected by the tool rewrite, so their tests are unchanged.
"""

from __future__ import annotations

import src.agents.tools.recommend_hotels as recommend_hotels_module
import src.agents.tools.select_hotel as select_hotel_module
import src.services.trip_planner as trip_planner_module
from src.agents.state import initial_state
from src.agents.tools.direct_invoke import invoke_tool_directly
from src.agents.tools.recommend_hotels import recommend_hotels
from src.agents.tools.select_hotel import select_hotel
from src.services.trip_scheduler import PlaceCandidate


def _fake_option(id_: str, name: str, rank: int) -> tuple[dict, PlaceCandidate]:
    data = {
        "id": id_,
        "destination_id": "dest-1",
        "name": name,
        "star_rating": 4,
        "description": "desc",
        "coordinates": "16.05,108.2",
        "matched_rooms": [],
        "covered_meals": [],
        "review_score": None,
        "review_count": None,
        "address": None,
        "area_name": None,
        "lowest_price": None,
        "currency": "VND",
        "image_url": None,
        "similarity": 0.8,
        "rank": rank,
        "recommendation_score": 0.8,
    }
    candidate = PlaceCandidate.from_mapping({**data, "category": "Hotel"})
    return data, candidate


def _fake_build_trip_data(captured: dict):
    def _build(
        destination,
        duration,
        people,
        preferences="",
        hotel_query=None,
        themes_override=None,
        preselected_hotel=None,
        planning_constraints=None,
        session_id="poc_trip_planner_1",
    ):
        captured["destination"] = destination
        captured["hotel_query"] = hotel_query
        captured["preselected_hotel"] = preselected_hotel
        captured["planning_constraints"] = planning_constraints
        captured["session_id"] = session_id
        return {
            "hotel": preselected_hotel or {},
            "itineraries": [{"id": "itinerary-1", "status": "Draft"}],
            "itinerary_items": [],
            "adjustments": [],
        }

    return _build


def _fake_generate_and_save(captured: dict, kwargs: dict) -> str:
    captured["preselected_hotel"] = kwargs.get("preselected_hotel")
    save = kwargs.get("save")
    if save:
        save({"hotel": kwargs.get("preselected_hotel") or {}, "itineraries": [{"status": "Draft"}]})
    return "Hotel: ok"


def test_recommend_hotels_writes_pending_selection_and_lists_names(monkeypatch):
    options = [_fake_option("h1", "Khách sạn Một", 1), _fake_option("h2", "Khách sạn Hai", 2)]
    monkeypatch.setattr(recommend_hotels_module, "_get_destination_id", lambda destination: "dest-1")
    monkeypatch.setattr(recommend_hotels_module, "select_hotel_candidates", lambda *a, **k: options)
    monkeypatch.setattr(recommend_hotels_module, "rank_hotel_candidates", lambda opts, **_kwargs: opts)

    state = initial_state("test-session")
    reply, updates = invoke_tool_directly(
        recommend_hotels,
        state,
        session_id="test-session",
        destination="Đà Nẵng",
        duration="3 ngày",
        people="2 người",
        preferences="",
        hotel_preferences="",
    )

    assert "Khách sạn Một" in reply
    assert "Khách sạn Hai" in reply
    assert updates["pending_hotel_selection"] is not None


def test_recommend_hotels_missing_field_returns_system_error():
    state = initial_state("test-session")
    reply, updates = invoke_tool_directly(
        recommend_hotels,
        state,
        session_id="test-session",
        destination="Đà Nẵng",
        duration="",
        people="2 người",
        preferences="",
        hotel_preferences="",
    )

    assert reply.startswith("SYSTEM ERROR:")
    assert updates["pending_hotel_selection"] is None


def test_select_hotel_with_valid_rank_builds_itinerary_and_clears_pending(monkeypatch):
    options = [_fake_option("h1", "Khách sạn Một", 1), _fake_option("h2", "Khách sạn Hai", 2)]
    state = initial_state("test-session")
    state["pending_hotel_selection"] = {
        "mode": "new_trip",
        "destination": "Đà Nẵng",
        "duration": "3 ngày",
        "people": "2 người",
        "preferences_text": "",
        "options": [data for data, _candidate in options],
    }

    captured: dict = {}
    monkeypatch.setattr(select_hotel_module, "_build_trip_data", _fake_build_trip_data(captured))
    monkeypatch.setattr(
        select_hotel_module, "_generate_and_save_itinerary", lambda *a, **k: _fake_generate_and_save(captured, k)
    )

    reply, updates = invoke_tool_directly(select_hotel, state, session_id="test-session", selection="2")

    assert captured["preselected_hotel"]["id"] == "h2"
    assert updates["pending_hotel_selection"] is None
    assert not reply.startswith("SYSTEM ERROR:")


def test_select_hotel_unresolved_selection_reshows_list_and_keeps_pending():
    options = [_fake_option("h1", "Khách sạn Một", 1)]
    state = initial_state("test-session")
    state["pending_hotel_selection"] = {
        "mode": "new_trip",
        "destination": "Đà Nẵng",
        "options": [data for data, _candidate in options],
    }

    reply, updates = invoke_tool_directly(
        select_hotel, state, session_id="test-session", selection="không tồn tại đâu"
    )

    assert "Khách sạn Một" in reply
    assert updates["pending_hotel_selection"] is not None


def test_select_hotel_without_pending_selection_returns_system_error():
    state = initial_state("test-session")
    reply, _updates = invoke_tool_directly(select_hotel, state, session_id="test-session", selection="1")

    assert reply.startswith("SYSTEM ERROR:")


def test_generate_full_itinerary_with_hotel_id_skips_search(monkeypatch):
    hotel_data, _candidate = _fake_option("h9", "Khách sạn Chín", 1)
    monkeypatch.setattr(trip_planner_module, "_get_destination_id", lambda destination: "dest-1")
    monkeypatch.setattr(
        trip_planner_module,
        "fetch_hotel_by_id",
        lambda hotel_id, destination_id=None: (hotel_data, None),
    )

    captured: dict = {}
    monkeypatch.setattr(trip_planner_module, "_build_trip_data", _fake_build_trip_data(captured))

    result = trip_planner_module.generate_full_itinerary(
        "Đà Nẵng",
        "3 ngày",
        "2 người",
        "",
        hotel_id="h9",
        save=lambda trip_data: None,
    )

    assert captured["preselected_hotel"]["id"] == "h9"
    assert not result.startswith("SYSTEM ERROR:")


def test_generate_full_itinerary_without_hotel_id_uses_legacy_path(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(trip_planner_module, "_build_trip_data", _fake_build_trip_data(captured))

    result = trip_planner_module.generate_full_itinerary(
        "Đà Nẵng",
        "3 ngày",
        "2 người",
        "",
        hotel_id="",
        save=lambda trip_data: None,
    )

    assert captured["preselected_hotel"] is None
    assert not result.startswith("SYSTEM ERROR:")


def test_recommend_hotels_threads_budget_and_amenity_prefs_into_ranking(monkeypatch):
    options = [_fake_option("h1", "Khách sạn Một", 1)]
    captured_rank_kwargs: dict = {}

    def fake_rank_hotel_candidates(opts, **kwargs):
        captured_rank_kwargs.update(kwargs)
        return opts

    monkeypatch.setattr(recommend_hotels_module, "_get_destination_id", lambda destination: "dest-1")
    monkeypatch.setattr(recommend_hotels_module, "select_hotel_candidates", lambda *a, **k: options)
    monkeypatch.setattr(recommend_hotels_module, "rank_hotel_candidates", fake_rank_hotel_candidates)
    monkeypatch.setattr(recommend_hotels_module, "lookup_sea_view_hotel_ids", lambda ids: frozenset())

    state = initial_state("test-session")
    invoke_tool_directly(
        recommend_hotels,
        state,
        session_id="test-session",
        destination="Đà Nẵng",
        duration="3 ngày",
        people="2 người",
        preferences="",
        hotel_preferences="",
        target_price="4000000",
        hotel_amenity_prefs="sea_view,pool",
    )

    assert captured_rank_kwargs["target_price"] == 4_000_000.0
    assert captured_rank_kwargs["amenity_prefs"] == frozenset({"sea_view", "pool"})


def test_recommend_hotels_calls_sea_view_lookup_only_when_requested(monkeypatch):
    options = [_fake_option("h1", "Khách sạn Một", 1)]
    lookup_calls: list = []

    monkeypatch.setattr(recommend_hotels_module, "_get_destination_id", lambda destination: "dest-1")
    monkeypatch.setattr(recommend_hotels_module, "select_hotel_candidates", lambda *a, **k: options)
    monkeypatch.setattr(recommend_hotels_module, "rank_hotel_candidates", lambda opts, **kwargs: opts)
    monkeypatch.setattr(
        recommend_hotels_module,
        "lookup_sea_view_hotel_ids",
        lambda ids: lookup_calls.append(ids) or frozenset(ids),
    )

    base_args = dict(
        destination="Đà Nẵng",
        duration="3 ngày",
        people="2 người",
        preferences="",
        hotel_preferences="",
        target_price="",
    )

    invoke_tool_directly(
        recommend_hotels, initial_state("s1"), session_id="s1", **base_args, hotel_amenity_prefs="pool"
    )
    assert lookup_calls == []

    invoke_tool_directly(
        recommend_hotels, initial_state("s2"), session_id="s2", **base_args, hotel_amenity_prefs="sea_view,pool"
    )
    assert lookup_calls == [["h1"]]


def test_recommend_hotels_forwards_target_price_to_search(monkeypatch):
    """A single ceiling-only target_price (no explicit range) must reach
    select_hotel_candidates as max_price (the hard search-side filter), not just
    rank_hotel_candidates (the soft ranking bonus) — see hotel_selection.py's
    _budget_bonus docstring: the ranking bonus alone is too weak to keep an 8x-over-budget
    hotel out of the results."""
    options = [_fake_option("h1", "Khách sạn Một", 1)]
    captured_select_kwargs: dict = {}

    def fake_select_hotel_candidates(*args, **kwargs):
        captured_select_kwargs.update(kwargs)
        return options

    monkeypatch.setattr(recommend_hotels_module, "_get_destination_id", lambda destination: "dest-1")
    monkeypatch.setattr(recommend_hotels_module, "select_hotel_candidates", fake_select_hotel_candidates)
    monkeypatch.setattr(recommend_hotels_module, "rank_hotel_candidates", lambda opts, **kwargs: opts)

    invoke_tool_directly(
        recommend_hotels,
        initial_state("test-session"),
        session_id="test-session",
        destination="Đà Nẵng",
        duration="3 ngày",
        people="2 người",
        preferences="",
        hotel_preferences="",
        target_price="1000000",
    )

    assert captured_select_kwargs["min_price"] is None
    assert captured_select_kwargs["max_price"] == 1_000_000.0


def test_recommend_hotels_forwards_explicit_min_and_max_price_range(monkeypatch):
    """A real tier range (e.g. resolved from the guided budget question's "tầm trung"
    pick) must reach select_hotel_candidates as both min_price and max_price — the
    reported gap where "chưa handle được min price" for the tier options."""
    options = [_fake_option("h1", "Khách sạn Một", 1)]
    captured_select_kwargs: dict = {}

    def fake_select_hotel_candidates(*args, **kwargs):
        captured_select_kwargs.update(kwargs)
        return options

    monkeypatch.setattr(recommend_hotels_module, "_get_destination_id", lambda destination: "dest-1")
    monkeypatch.setattr(recommend_hotels_module, "select_hotel_candidates", fake_select_hotel_candidates)
    monkeypatch.setattr(recommend_hotels_module, "rank_hotel_candidates", lambda opts, **kwargs: opts)

    invoke_tool_directly(
        recommend_hotels,
        initial_state("test-session"),
        session_id="test-session",
        destination="Đà Nẵng",
        duration="3 ngày",
        people="2 người",
        preferences="",
        hotel_preferences="",
        target_price="1500000",
        min_price="800000",
        max_price="2500000",
    )

    assert captured_select_kwargs["min_price"] == 800_000.0
    assert captured_select_kwargs["max_price"] == 2_500_000.0


def test_legacy_modify_trip_plan_change_hotel_forwards_parsed_budget(monkeypatch):
    """A budget mentioned in a change-hotel edit request must also reach both
    select_hotel_candidates and rank_hotel_candidates as a numeric target_price.

    Covers `_legacy_modify_trip_plan`, not the active `modify_trip_plan` — the
    latter now routes through `plan_trip_edit`/`resolve_trip_edit_request` (a
    separate, concurrently-developed edit pipeline) whose own hotel_change branch
    does not yet forward any price param at all. That's a distinct, still-open gap
    in that newer pipeline, out of scope here."""
    from src.services.trip_scheduler import TripChange

    current_data = {
        "itineraries": [
            {
                "status": "Draft",
                "destination_id": "dest-1",
                "preferences": ["Đà Nẵng"],
                "duration_days": 3,
                "number_of_adults": 2,
            }
        ]
    }

    options = [_fake_option("h1", "Khách sạn Một", 1)]
    captured_select_kwargs: dict = {}
    captured_rank_kwargs: dict = {}

    def fake_select_hotel_candidates(*args, **kwargs):
        captured_select_kwargs.update(kwargs)
        return options

    def fake_rank_hotel_candidates(opts, **kwargs):
        captured_rank_kwargs.update(kwargs)
        return opts

    monkeypatch.setattr(trip_planner_module, "_get_destination_id", lambda destination: "dest-1")
    monkeypatch.setattr(
        trip_planner_module,
        "_parse_trip_change",
        lambda modification_request: TripChange(action="change_hotel", query="khách sạn gần biển"),
    )
    monkeypatch.setattr(trip_planner_module, "select_hotel_candidates", fake_select_hotel_candidates)
    monkeypatch.setattr(trip_planner_module, "rank_hotel_candidates", fake_rank_hotel_candidates)

    trip_planner_module._legacy_modify_trip_plan(
        current_data, "Đổi khách sạn khác, giá tầm 1 triệu"
    )

    assert captured_select_kwargs["max_price"] == 1_000_000.0
    assert captured_rank_kwargs["target_price"] == 1_000_000.0
