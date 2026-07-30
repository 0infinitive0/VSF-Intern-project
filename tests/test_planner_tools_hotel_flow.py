from __future__ import annotations

import os

import pytest

import src.cli.planner_tools as planner_tools_module
from src.cli.trip_builder_svc import PENDING_HOTEL_SELECTION_FILE, SESSION_DATA_DIR
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


@pytest.fixture(autouse=True)
def _isolate_cwd(tmp_path, monkeypatch):
    """current_trip_plan.json / pending_hotel_selection.json live under data/,
    relative to cwd — sandbox them away from the repo root."""
    monkeypatch.chdir(tmp_path)
    os.makedirs(SESSION_DATA_DIR, exist_ok=True)


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
    ):
        captured["destination"] = destination
        captured["hotel_query"] = hotel_query
        captured["preselected_hotel"] = preselected_hotel
        captured["planning_constraints"] = planning_constraints
        return {
            "hotel": preselected_hotel or {},
            "itineraries": [{"id": "itinerary-1", "status": "Draft"}],
            "itinerary_items": [],
            "adjustments": [],
        }

    return _build


def test_recommend_hotels_writes_pending_file_and_lists_names(monkeypatch):
    options = [_fake_option("h1", "Khách sạn Một", 1), _fake_option("h2", "Khách sạn Hai", 2)]
    monkeypatch.setattr(planner_tools_module, "_get_destination_id", lambda destination: "dest-1")
    monkeypatch.setattr(planner_tools_module, "select_hotel_candidates", lambda *a, **k: options)
    monkeypatch.setattr(planner_tools_module, "rank_hotel_candidates", lambda opts, **_kwargs: opts)

    result = planner_tools_module.recommend_hotels.invoke(
        {
            "destination": "Đà Nẵng",
            "duration": "3 ngày",
            "people": "2 người",
            "preferences": "",
            "hotel_preferences": "",
        }
    )

    assert "Khách sạn Một" in result
    assert "Khách sạn Hai" in result
    assert os.path.exists(PENDING_HOTEL_SELECTION_FILE)


def test_recommend_hotels_missing_field_returns_system_error():
    result = planner_tools_module.recommend_hotels.invoke(
        {"destination": "Đà Nẵng", "duration": "", "people": "2 người", "preferences": "", "hotel_preferences": ""}
    )

    assert result.startswith("SYSTEM ERROR:")
    assert not os.path.exists(PENDING_HOTEL_SELECTION_FILE)


def test_select_hotel_with_valid_rank_builds_itinerary_and_clears_pending(monkeypatch):
    options = [_fake_option("h1", "Khách sạn Một", 1), _fake_option("h2", "Khách sạn Hai", 2)]
    monkeypatch.setattr(planner_tools_module, "_get_destination_id", lambda destination: "dest-1")
    monkeypatch.setattr(planner_tools_module, "select_hotel_candidates", lambda *a, **k: options)
    monkeypatch.setattr(planner_tools_module, "rank_hotel_candidates", lambda opts, **_kwargs: opts)
    planner_tools_module.recommend_hotels.invoke(
        {
            "destination": "Đà Nẵng",
            "duration": "3 ngày",
            "people": "2 người",
            "preferences": "",
            "hotel_preferences": "",
        }
    )
    assert os.path.exists(PENDING_HOTEL_SELECTION_FILE)

    captured: dict = {}
    monkeypatch.setattr(planner_tools_module, "_build_trip_data", _fake_build_trip_data(captured))
    monkeypatch.setattr(planner_tools_module, "_save_trip_data", lambda trip_data: None)

    result = planner_tools_module.select_hotel.invoke({"selection": "2"})

    assert captured["preselected_hotel"]["id"] == "h2"
    assert not os.path.exists(PENDING_HOTEL_SELECTION_FILE)
    assert not result.startswith("SYSTEM ERROR:")


def test_select_hotel_unresolved_selection_reshows_list_and_keeps_pending(monkeypatch):
    options = [_fake_option("h1", "Khách sạn Một", 1)]
    monkeypatch.setattr(planner_tools_module, "_get_destination_id", lambda destination: "dest-1")
    monkeypatch.setattr(planner_tools_module, "select_hotel_candidates", lambda *a, **k: options)
    monkeypatch.setattr(planner_tools_module, "rank_hotel_candidates", lambda opts, **_kwargs: opts)
    planner_tools_module.recommend_hotels.invoke(
        {
            "destination": "Đà Nẵng",
            "duration": "3 ngày",
            "people": "2 người",
            "preferences": "",
            "hotel_preferences": "",
        }
    )

    result = planner_tools_module.select_hotel.invoke({"selection": "không tồn tại đâu"})

    assert "Khách sạn Một" in result
    assert os.path.exists(PENDING_HOTEL_SELECTION_FILE)


def test_select_hotel_without_pending_file_returns_system_error():
    result = planner_tools_module.select_hotel.invoke({"selection": "1"})

    assert result.startswith("SYSTEM ERROR:")


def test_generate_full_itinerary_with_hotel_id_skips_search(monkeypatch):
    hotel_data, _candidate = _fake_option("h9", "Khách sạn Chín", 1)
    monkeypatch.setattr(planner_tools_module, "_get_destination_id", lambda destination: "dest-1")
    monkeypatch.setattr(
        planner_tools_module,
        "fetch_hotel_by_id",
        lambda hotel_id, destination_id=None: (hotel_data, None),
    )

    captured: dict = {}
    monkeypatch.setattr(planner_tools_module, "_build_trip_data", _fake_build_trip_data(captured))
    monkeypatch.setattr(planner_tools_module, "_save_trip_data", lambda trip_data: None)

    result = planner_tools_module.generate_full_itinerary.invoke(
        {
            "destination": "Đà Nẵng",
            "duration": "3 ngày",
            "people": "2 người",
            "preferences": "",
            "hotel_id": "h9",
        }
    )

    assert captured["preselected_hotel"]["id"] == "h9"
    assert not result.startswith("SYSTEM ERROR:")


def test_generate_full_itinerary_without_hotel_id_uses_legacy_path(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(planner_tools_module, "_build_trip_data", _fake_build_trip_data(captured))
    monkeypatch.setattr(planner_tools_module, "_save_trip_data", lambda trip_data: None)

    result = planner_tools_module.generate_full_itinerary.invoke(
        {
            "destination": "Đà Nẵng",
            "duration": "3 ngày",
            "people": "2 người",
            "preferences": "",
            "hotel_id": "",
        }
    )

    assert captured["preselected_hotel"] is None
    assert not result.startswith("SYSTEM ERROR:")


def test_recommend_hotels_threads_budget_and_amenity_prefs_into_ranking(monkeypatch):
    options = [_fake_option("h1", "Khách sạn Một", 1)]
    captured_rank_kwargs: dict = {}

    def fake_rank_hotel_candidates(opts, **kwargs):
        captured_rank_kwargs.update(kwargs)
        return opts

    monkeypatch.setattr(planner_tools_module, "_get_destination_id", lambda destination: "dest-1")
    monkeypatch.setattr(planner_tools_module, "select_hotel_candidates", lambda *a, **k: options)
    monkeypatch.setattr(planner_tools_module, "rank_hotel_candidates", fake_rank_hotel_candidates)
    monkeypatch.setattr(planner_tools_module, "lookup_sea_view_hotel_ids", lambda ids: frozenset())

    planner_tools_module.recommend_hotels.invoke(
        {
            "destination": "Đà Nẵng",
            "duration": "3 ngày",
            "people": "2 người",
            "preferences": "",
            "hotel_preferences": "",
            "target_price": "4000000",
            "hotel_amenity_prefs": "sea_view,pool",
        }
    )

    assert captured_rank_kwargs["target_price"] == 4_000_000.0
    assert captured_rank_kwargs["amenity_prefs"] == frozenset({"sea_view", "pool"})


def test_recommend_hotels_calls_sea_view_lookup_only_when_requested(monkeypatch):
    options = [_fake_option("h1", "Khách sạn Một", 1)]
    lookup_calls: list = []

    monkeypatch.setattr(planner_tools_module, "_get_destination_id", lambda destination: "dest-1")
    monkeypatch.setattr(planner_tools_module, "select_hotel_candidates", lambda *a, **k: options)
    monkeypatch.setattr(planner_tools_module, "rank_hotel_candidates", lambda opts, **kwargs: opts)
    monkeypatch.setattr(
        planner_tools_module,
        "lookup_sea_view_hotel_ids",
        lambda ids: lookup_calls.append(ids) or frozenset(ids),
    )

    base_args = {
        "destination": "Đà Nẵng",
        "duration": "3 ngày",
        "people": "2 người",
        "preferences": "",
        "hotel_preferences": "",
        "target_price": "",
    }

    planner_tools_module.recommend_hotels.invoke({**base_args, "hotel_amenity_prefs": "pool"})
    assert lookup_calls == []

    planner_tools_module.recommend_hotels.invoke({**base_args, "hotel_amenity_prefs": "sea_view,pool"})
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

    monkeypatch.setattr(planner_tools_module, "_get_destination_id", lambda destination: "dest-1")
    monkeypatch.setattr(planner_tools_module, "select_hotel_candidates", fake_select_hotel_candidates)
    monkeypatch.setattr(planner_tools_module, "rank_hotel_candidates", lambda opts, **kwargs: opts)

    planner_tools_module.recommend_hotels.invoke(
        {
            "destination": "Đà Nẵng",
            "duration": "3 ngày",
            "people": "2 người",
            "preferences": "",
            "hotel_preferences": "",
            "target_price": "1000000",
        }
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

    monkeypatch.setattr(planner_tools_module, "_get_destination_id", lambda destination: "dest-1")
    monkeypatch.setattr(planner_tools_module, "select_hotel_candidates", fake_select_hotel_candidates)
    monkeypatch.setattr(planner_tools_module, "rank_hotel_candidates", lambda opts, **kwargs: opts)

    planner_tools_module.recommend_hotels.invoke(
        {
            "destination": "Đà Nẵng",
            "duration": "3 ngày",
            "people": "2 người",
            "preferences": "",
            "hotel_preferences": "",
            "target_price": "1500000",
            "min_price": "800000",
            "max_price": "2500000",
        }
    )

    assert captured_select_kwargs["min_price"] == 800_000.0
    assert captured_select_kwargs["max_price"] == 2_500_000.0


def test_legacy_modify_trip_plan_change_hotel_forwards_parsed_budget(monkeypatch):
    """A budget mentioned in a change-hotel edit request must also reach both
    select_hotel_candidates and rank_hotel_candidates as a numeric target_price.

    Covers `_legacy_modify_trip_plan`, not the active `modify_trip_plan` — the
    latter now routes through `plan_trip_edit`/`execute_trip_edit_request` (a
    separate, concurrently-developed edit pipeline) whose own hotel_change branch
    does not yet forward any price param at all. That's a distinct, still-open gap
    in that newer pipeline, out of scope here."""
    import json

    from src.cli.trip_builder_svc import CURRENT_TRIP_PLAN_FILE
    from src.services.trip_scheduler import TripChange

    with open(CURRENT_TRIP_PLAN_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {
                "itineraries": [
                    {
                        "status": "Draft",
                        "destination_id": "dest-1",
                        "preferences": ["Đà Nẵng"],
                        "duration_days": 3,
                        "number_of_adults": 2,
                    }
                ]
            },
            f,
        )

    options = [_fake_option("h1", "Khách sạn Một", 1)]
    captured_select_kwargs: dict = {}
    captured_rank_kwargs: dict = {}

    def fake_select_hotel_candidates(*args, **kwargs):
        captured_select_kwargs.update(kwargs)
        return options

    def fake_rank_hotel_candidates(opts, **kwargs):
        captured_rank_kwargs.update(kwargs)
        return opts

    monkeypatch.setattr(planner_tools_module, "_get_destination_id", lambda destination: "dest-1")
    monkeypatch.setattr(
        planner_tools_module,
        "_parse_trip_change",
        lambda modification_request: TripChange(action="change_hotel", query="khách sạn gần biển"),
    )
    monkeypatch.setattr(planner_tools_module, "select_hotel_candidates", fake_select_hotel_candidates)
    monkeypatch.setattr(planner_tools_module, "rank_hotel_candidates", fake_rank_hotel_candidates)

    planner_tools_module._legacy_modify_trip_plan.invoke(
        {"modification_request": "Đổi khách sạn khác, giá tầm 1 triệu"}
    )

    assert captured_select_kwargs["max_price"] == 1_000_000.0
    assert captured_rank_kwargs["target_price"] == 1_000_000.0
