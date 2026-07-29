from __future__ import annotations

import os

import pytest

import src.cli.planner_tools as planner_tools_module
from src.cli.trip_builder_svc import PENDING_HOTEL_SELECTION_FILE
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
    """current_trip_plan.json / pending_hotel_selection.json are bare relative
    filenames — sandbox them away from the repo root."""
    monkeypatch.chdir(tmp_path)


def _fake_build_trip_data(captured: dict):
    def _build(
        destination,
        duration,
        people,
        preferences="",
        hotel_query=None,
        themes_override=None,
        preselected_hotel=None,
    ):
        captured["destination"] = destination
        captured["hotel_query"] = hotel_query
        captured["preselected_hotel"] = preselected_hotel
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
    monkeypatch.setattr(planner_tools_module, "rank_hotel_candidates", lambda opts: opts)

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
    monkeypatch.setattr(planner_tools_module, "rank_hotel_candidates", lambda opts: opts)
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
    monkeypatch.setattr(planner_tools_module, "rank_hotel_candidates", lambda opts: opts)
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
