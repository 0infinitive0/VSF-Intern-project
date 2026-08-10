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

import json

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
        intake_context="",
        language="vi",
    ):
        captured["destination"] = destination
        captured["hotel_query"] = hotel_query
        captured["preselected_hotel"] = preselected_hotel
        captured["planning_constraints"] = planning_constraints
        captured["session_id"] = session_id
        captured["intake_context"] = intake_context
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
        start_date="2026-08-10",
        end_date="2026-08-13",
        people="2 người",
        preferences="",
        hotel_preferences="",
    )

    assert reply == (
        "Mình đã tìm được danh sách khách sạn phù hợp. Bạn xem và chọn trực tiếp "
        "khách sạn mong muốn trong tab Khách sạn để tạo lịch trình nhé!"
    )
    assert updates["pending_hotel_selection"] is not None
    assert [option["id"] for option in updates["pending_hotel_selection"]["options"]] == ["h1", "h2"]


def test_recommend_hotels_excludes_hotels_already_shown_when_searching_more(monkeypatch):
    captured_select_kwargs: dict = {}
    existing_option = _fake_option("shown-hotel", "Khách sạn Đã Hiển Thị", 1)[0]
    new_options = [_fake_option("new-hotel", "Khách sạn Mới", 1)]

    def fake_select_hotel_candidates(*args, **kwargs):
        captured_select_kwargs.update(kwargs)
        return new_options

    monkeypatch.setattr(recommend_hotels_module, "_get_destination_id", lambda destination: "dest-1")
    monkeypatch.setattr(recommend_hotels_module, "select_hotel_candidates", fake_select_hotel_candidates)
    monkeypatch.setattr(recommend_hotels_module, "rank_hotel_candidates", lambda options, **_kwargs: options)

    state = initial_state("test-session")
    state["pending_hotel_selection"] = {"options": [existing_option]}
    reply, updates = invoke_tool_directly(
        recommend_hotels,
        state,
        session_id="test-session",
        destination="Đà Nẵng",
        duration="3 ngày",
        start_date="2026-08-10",
        end_date="2026-08-13",
        people="2 người",
        exclude_hotel_ids=["explicit-exclude"],
    )

    assert captured_select_kwargs["exclude_hotel_ids"] == ["shown-hotel", "explicit-exclude"]
    assert reply == (
        "Mình đã tìm được danh sách khách sạn phù hợp. Bạn xem và chọn trực tiếp "
        "khách sạn mong muốn trong tab Khách sạn để tạo lịch trình nhé!"
    )
    assert [option["id"] for option in updates["pending_hotel_selection"]["options"]] == [
        "shown-hotel",
        "new-hotel",
    ]


def test_recommend_hotels_keeps_original_list_when_preferences_change(monkeypatch):
    captured_select_kwargs: dict = {}
    stale_option = _fake_option("stale-hotel", "KhÃ¡ch sáº¡n CÅ©", 1)[0]
    fresh_options = [_fake_option("fresh-hotel", "KhÃ¡ch sáº¡n PhÃ¹ Há»£p", 1)]

    def _select(*_args, **kwargs):
        captured_select_kwargs.update(kwargs)
        return fresh_options

    stale_option["match_score"] = 0.99
    fresh_options[0][0]["match_score"] = 0.81

    monkeypatch.setattr(recommend_hotels_module, "_get_destination_id", lambda _destination: "dest-1")
    monkeypatch.setattr(recommend_hotels_module, "select_hotel_candidates", _select)
    monkeypatch.setattr(recommend_hotels_module, "rank_hotel_candidates", lambda options, **_kwargs: options)
    state = initial_state("test-session")
    state["pending_hotel_selection"] = {
        "destination": "ÄÃ  Náºµng",
        "start_date": "2026-08-10",
        "end_date": "2026-08-13",
        "preferences_text": "biá»ƒn",
        "hotel_query": "biá»ƒn",
        "options": [stale_option],
    }

    _, updates = invoke_tool_directly(
        recommend_hotels,
        state,
        session_id="test-session",
        destination="ÄÃ  Náºµng",
        duration="3 ngÃ y",
        start_date="2026-08-10",
        end_date="2026-08-13",
        people="2 ngÆ°á»i",
        preferences="vÄƒn hÃ³a",
        hotel_preferences="",
    )

    assert captured_select_kwargs["hotel_query"] == "vÄƒn hÃ³a"
    assert captured_select_kwargs["exclude_hotel_ids"] == ["stale-hotel"]
    assert [option["id"] for option in updates["pending_hotel_selection"]["options"]] == [
        "stale-hotel",
        "fresh-hotel",
    ]


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
    assert reply != "Hotel: ok"
    assert updates["trip_data"]["hotel"]["id"] == "h2"


def test_select_hotel_calculates_routes_before_returning_the_trip_plan(monkeypatch):
    options = [_fake_option("h1", "KhÃ¡ch sáº¡n Má»™t", 1)]
    state = initial_state("test-session")
    state["pending_hotel_selection"] = {
        "mode": "new_trip",
        "destination": "ÄÃ  Náºµng",
        "duration": "3 ngÃ y",
        "people": "2 ngÆ°á»i",
        "preferences_text": "",
        "options": [data for data, _candidate in options],
    }
    generated = {
        "hotel": {"coordinates": [16.05, 108.2]},
        "itineraries": [{"id": "itinerary-1", "status": "Draft"}],
        "itinerary_items": [{"id": "item-1", "coordinates": [16.06, 108.21]}],
    }

    def _generate(*_args, **kwargs):
        kwargs["save"](generated)
        return "Hotel: ok"

    def _routes(trip_data):
        trip_data["itinerary_items"][0]["route_from_hotel"] = {"distance_km": 1.5}
        trip_data["itinerary_items"][0]["route_to_next"] = {"distance_km": 1.5}
        return trip_data

    monkeypatch.setattr(select_hotel_module, "_generate_and_save_itinerary", _generate)
    monkeypatch.setattr("src.services.routing.recalculate_itinerary_routes", _routes)

    _, updates = invoke_tool_directly(select_hotel, state, session_id="test-session", selection="1")

    item = updates["trip_data"]["itinerary_items"][0]
    assert item["route_from_hotel"]["distance_km"] == 1.5
    assert item["route_to_next"]["distance_km"] == 1.5


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


def test_select_hotel_replacement_mode_builds_fresh_dated_draft(monkeypatch):
    options = [_fake_option("h1", "Khách sạn Mới", 1)]
    old_trip = {
        "hotel": {"id": "hotel-old"},
        "itineraries": [{"id": "trip-old", "status": "Draft"}],
        "itinerary_items": [{"id": "old-item"}],
    }
    state = initial_state("test-session")
    state["trip_data"] = old_trip
    state["pending_hotel_selection"] = {
        "mode": "replace_trip_preferences",
        "destination": "Đà Nẵng",
        "duration": "5 ngày",
        "start_date": "2026-08-10",
        "end_date": "2026-08-15",
        "people": "4 người",
        "preferences_text": "thiên nhiên",
        "options": [data for data, _candidate in options],
    }
    captured = {}

    def _build(destination, duration, people, preferences, **kwargs):
        captured.update(
            destination=destination,
            duration=duration,
            people=people,
            preferences=preferences,
            **kwargs,
        )
        return {
            "hotel": kwargs["preselected_hotel"],
            "itineraries": [{"id": "trip-new", "status": "Draft"}],
            "itinerary_items": [{"id": "new-item"}],
        }

    monkeypatch.setattr(select_hotel_module, "_build_trip_data", _build)

    reply, updates = invoke_tool_directly(select_hotel, state, session_id="test-session", selection="1")

    assert not reply.startswith("SYSTEM ERROR:")
    assert captured["start_date"] == "2026-08-10"
    assert captured["end_date"] == "2026-08-15"
    assert captured["people"] == "4 người"
    assert captured["planning_constraints"] == {}
    assert updates["trip_data"]["itineraries"][0]["id"] == "trip-new"
    assert updates["trip_data"]["itinerary_items"] == [{"id": "new-item"}]
    assert updates["pending_hotel_selection"] is None


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


def test_tiered_candidate_adapter_uses_selected_hotel_coordinates_and_preserves_tier(monkeypatch):
    hotel = PlaceCandidate(
        id="hotel-1",
        name="Selected Hotel",
        category="Hotel",
        coordinates="16.0544,108.2022",
    )
    captured: dict = {}

    def fake_tiered_search(query, **kwargs):
        captured["query"] = query
        captured.update(kwargs)
        return [{"id": "museum", "retrieval_tier": 2, "similarity": 0.7}]

    monkeypatch.setattr(trip_planner_module, "rpc_search_attractions_tiered", fake_tiered_search)
    monkeypatch.setattr(
        trip_planner_module,
        "_hydrate_records",
        lambda *_args, **_kwargs: [
            {
                "id": "museum",
                "name": "Museum",
                "category": "Museums & culture",
                "coordinates": "16.055,108.203",
                "retrieval_tier": 2,
                "similarity": 0.7,
            }
        ],
    )

    candidates = trip_planner_module._search_attraction_candidates_tiered(
        "culture museum",
        "destination-id",
        hotel,
        required_count=3,
    )

    assert captured == {
        "query": "culture museum",
        "required_count": 3,
        "filter_destination_id": "destination-id",
        "root_latitude": 16.0544,
        "root_longitude": 108.2022,
    }
    assert candidates[0].id == "museum"
    assert candidates[0].retrieval_tier == 2


def test_preselected_hotel_builds_final_pools_from_its_coordinates(monkeypatch):
    hotel_data, _ = _fake_option("hotel-1", "Selected Hotel", 1)
    captured: dict = {}

    monkeypatch.setattr(trip_planner_module, "_get_destination_id", lambda _destination: "destination-id")

    def fake_tiered_pools(destination, destination_id, themes, hotel):
        captured.update(
            destination=destination,
            destination_id=destination_id,
            hotel_id=hotel.id,
            coordinates=hotel.coordinate_pair,
            theme_count=len(themes),
        )
        return {1: []}, [], [], [], []

    monkeypatch.setattr(trip_planner_module, "_build_tiered_candidate_pools", fake_tiered_pools)

    result = trip_planner_module._build_trip_data(
        "Đà Nẵng",
        "1 ngày",
        "2 người",
        themes_override=[{"day_number": 1, "title": "Culture", "query": "culture"}],
        preselected_hotel=hotel_data,
    )

    assert captured == {
        "destination": "Đà Nẵng",
        "destination_id": "destination-id",
        "hotel_id": "hotel-1",
        "coordinates": (16.05, 108.2),
        "theme_count": 1,
    }
    assert result["hotel"]["id"] == "hotel-1"


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
        start_date="2026-08-10",
        end_date="2026-08-13",
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
        start_date="2026-08-10",
        end_date="2026-08-13",
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
        start_date="2026-08-10",
        end_date="2026-08-13",
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
        start_date="2026-08-10",
        end_date="2026-08-13",
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


class _FakeThemeResponse:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeThemeLLM:
    def __init__(self) -> None:
        self.captured_prompts: list[str] = []

    def invoke(self, messages):
        self.captured_prompts.append(messages[1].content)
        content = json.dumps(
            {
                "themes": [
                    {"day_number": 1, "title": "Khám phá bãi biển", "query": "bãi biển"},
                    {"day_number": 2, "title": "Ẩm thực địa phương", "query": "món ngon"},
                ]
            },
            ensure_ascii=False,
        )
        return _FakeThemeResponse(content)


def test_generate_day_themes_prompt_includes_intake_context(monkeypatch) -> None:
    """Phase 3/6: the day-theme generation prompt must carry the advisory
    travel-style context (pace/day rhythm/notes) when set, and cleanly omit
    the context line when unset."""
    fake_llm = _FakeThemeLLM()
    monkeypatch.setattr(trip_planner_module, "get_llm", lambda **kwargs: fake_llm)

    categories = ["bãi biển", "ẩm thực"]
    context = "nhịp độ: vừa phải; nhịp sinh hoạt: bắt đầu sớm; ăn chay"

    themes = trip_planner_module._generate_day_themes(
        "Đà Nẵng", 2, categories, ["biển"], context=context
    )
    assert len(themes) == 2
    assert context in fake_llm.captured_prompts[0]

    # Unset context → the whole context line is omitted, not emitted empty.
    fake_llm.captured_prompts.clear()
    trip_planner_module._generate_day_themes("Đà Nẵng", 2, categories, ["biển"], context="")
    assert "Additional user context" not in fake_llm.captured_prompts[0]
