from __future__ import annotations

import src.services.trip_planner as trip_builder_svc
from src.services.trip_edit_planner import parse_trip_edit_plan
from src.services.trip_formatter import to_trip_plan_payload
from src.services.trip_planner import (
    _apply_local_trip_change,
    _generate_and_save_itinerary,
    _reapply_planning_constraints,
    apply_trip_edit_plan,
    build_selected_hotel_trip,
    resolve_trip_edit_request,
)
from src.services.trip_scheduler import PlaceCandidate, TripChange


def _trip_data() -> dict:
    return {
        "itineraries": [{"id": "trip-1", "duration_days": 2}],
        "itinerary_items": [
            {
                "id": "breakfast-1",
                "day_number": 1,
                "order_index": 1,
                "item_kind": "breakfast",
                "activity": "Ăn sáng tại Quán Một",
            },
            {
                "id": "museum-1",
                "day_number": 1,
                "order_index": 2,
                "item_kind": "attraction",
                "activity": "Tham quan bảo tàng",
            },
            {
                "id": "breakfast-2",
                "day_number": 2,
                "order_index": 1,
                "item_kind": "breakfast",
                "activity": "Ăn sáng tại Quán Hai",
            },
            {
                "id": "park-2",
                "day_number": 2,
                "order_index": 2,
                "item_kind": "attraction",
                "activity": "Đi dạo công viên",
            },
        ],
    }


def test_initial_itinerary_reply_is_concise_while_the_full_plan_is_saved(monkeypatch) -> None:
    trip_data = _trip_data()
    trip_data["hotel"] = {"name": "Khách sạn Một"}
    saved: dict[str, dict] = {}
    monkeypatch.setattr(trip_builder_svc, "_build_trip_data", lambda *_args, **_kwargs: trip_data)

    reply = _generate_and_save_itinerary(
        "Đà Nẵng",
        "2",
        "2",
        save=lambda data: saved.setdefault("trip", data),
    )

    assert "Ngày 1" not in reply
    assert "Khách sạn Một" in reply
    assert saved["trip"] is trip_data
    assert saved["trip"]["itinerary_items"]


def test_hotel_replacement_reply_is_concise_while_the_full_plan_is_returned(monkeypatch) -> None:
    trip_data = _trip_data()
    trip_data["hotel"] = {"name": "Khách sạn Mới"}
    monkeypatch.setattr(trip_builder_svc, "_build_trip_data", lambda *_args, **_kwargs: trip_data)

    result = build_selected_hotel_trip(
        {
            "mode": "change_hotel",
            "destination": "Đà Nẵng",
            "duration": "2",
            "people": "2",
        },
        {"id": "hotel-2", "name": "Khách sạn Mới"},
        current_trip_data=_trip_data(),
        session_id="test-session",
    )

    assert "Ngày 1" not in result.reply
    assert "Khách sạn Mới" in result.reply
    assert result.trip_data is trip_data
    assert result.trip_data["itinerary_items"]


def test_self_selected_meal_removes_breakfast_without_adding_a_replacement() -> None:
    trip_data = _trip_data()
    change = TripChange(action="set_meal_self_selected", meal_kind="breakfast")

    adjustments = _apply_local_trip_change(
        trip_data,
        change,
        "tôi muốn tự chọn chỗ ăn sáng",
    )

    assert [item["id"] for item in trip_data["itinerary_items"]] == ["museum-1", "park-2"]
    assert [item["order_index"] for item in trip_data["itinerary_items"]] == [1, 1]
    assert trip_data["itineraries"][0]["planning_constraints"] == {
        "meal_preferences": {"breakfast": "self_selected"}
    }
    assert any("tự chọn bữa sáng" in message for message in adjustments)


def test_self_selected_meal_preference_is_reapplied_after_replanning() -> None:
    trip_data = _trip_data()
    trip_data["itineraries"][0]["planning_constraints"] = {
        "meal_preferences": {"breakfast": "self_selected"}
    }

    _reapply_planning_constraints(trip_data)

    assert [item["id"] for item in trip_data["itinerary_items"]] == ["museum-1", "park-2"]


def test_remove_item_leave_blank_does_not_add_a_hotel_rest_block() -> None:
    trip_data = _trip_data()
    plan = parse_trip_edit_plan(
        {
            "decision": "apply",
            "summary": "Bỏ bảo tàng ngày 1",
            "operations": [
                {
                    "operation": "remove_item",
                    "target": {"item_id": "museum-1"},
                    "gap_policy": "leave_blank",
                }
            ],
        },
        trip_data,
    )

    adjustments = apply_trip_edit_plan(trip_data, plan)

    assert [item["id"] for item in trip_data["itinerary_items"]] == ["breakfast-1", "breakfast-2", "park-2"]
    assert all(item.get("item_kind") != "rest" for item in trip_data["itinerary_items"])
    assert any("bỏ" in adjustment.casefold() for adjustment in adjustments)


def test_trip_edit_reply_confirms_update_without_rendering_the_trip_plan(monkeypatch) -> None:
    trip_data = _trip_data()
    monkeypatch.setattr(trip_builder_svc, "_persist_itinerary_metadata", lambda _trip_data: None)
    plan = parse_trip_edit_plan(
        {
            "decision": "apply",
            "summary": "Remove the museum on day 1",
            "operations": [
                {
                    "operation": "remove_item",
                    "target": {"item_id": "museum-1"},
                    "gap_policy": "leave_blank",
                }
            ],
        },
        trip_data,
    )

    reply, updates = resolve_trip_edit_request(trip_data, "remove the museum", plan)

    assert reply == "Đã bỏ Tham quan bảo tàng."
    assert "Ngày 1" not in reply
    assert updates["trip_data"] is trip_data
    assert updates["trip_data"]["itinerary_items"]
    assert to_trip_plan_payload(updates["trip_data"])["days"][0]["items"]


def test_breakfast_replacement_uses_real_nearby_breakfast_candidate(monkeypatch) -> None:
    trip_data = {
        "hotel": {
            "id": "hotel-1",
            "name": "Hotel One",
            "destination_id": "destination-1",
            "coordinates": "10.7000,106.7000",
        },
        "itineraries": [{"id": "trip-1", "duration_days": 1, "destination_id": "destination-1"}],
        "itinerary_items": [
            {
                "id": "breakfast-1",
                "itinerary_id": "trip-1",
                "day_number": 1,
                "order_index": 1,
                "item_kind": "breakfast",
                "kind": "breakfast",
                "reference_type": "Attraction",
                "reference_id": "old-breakfast",
                "activity": "Ăn sáng tại Quán Cũ",
                "start_time": "07:00:00",
                "end_time": "08:00:00",
                "coordinates": [10.7010, 106.7010],
            }
        ],
    }
    candidate = PlaceCandidate(
        id="near-breakfast",
        name="Near Breakfast Restaurant",
        category="Restaurant",
        coordinates=(10.7050, 106.7050),
        similarity=0.9,
        opening_time="06:00:00",
        closing_time="11:00:00",
    )
    monkeypatch.setattr(trip_builder_svc, "_search_attraction_candidates", lambda *_args, **_kwargs: [candidate])
    plan = parse_trip_edit_plan(
        {
            "decision": "apply",
            "summary": "Đổi chỗ ăn sáng ngày 1",
            "operations": [
                {
                    "operation": "replace_item",
                    "target": {"item_id": "breakfast-1", "day_number": 1, "item_kind": "breakfast"},
                    "requirements": {
                        "item_kind": "breakfast",
                        "semantic_query": "địa điểm ăn sáng",
                        "near": "hotel",
                        "preserve_start_time": True,
                        "preserve_duration": True,
                    },
                }
            ],
        },
        trip_data,
    )

    apply_trip_edit_plan(trip_data, plan)

    item = trip_data["itinerary_items"][0]
    assert item["reference_id"] == "near-breakfast"
    assert item["start_time"] == "07:00:00"
    assert item["end_time"] == "08:00:00"


def test_start_only_time_change_preserves_the_existing_duration() -> None:
    trip_data = {
        "hotel": {"id": "hotel-1", "name": "Hotel One", "coordinates": "10.7,106.7"},
        "itineraries": [{"id": "trip-1", "duration_days": 1}],
        "itinerary_items": [
            {
                "id": "museum-1",
                "itinerary_id": "trip-1",
                "day_number": 1,
                "order_index": 1,
                "item_kind": "attraction",
                "kind": "attraction",
                "reference_type": "Attraction",
                "reference_id": "museum-reference",
                "activity": "Tham quan bảo tàng",
                "start_time": "08:00:00",
                "end_time": "09:30:00",
                "coordinates": [10.7010, 106.7010],
            }
        ],
    }
    plan = parse_trip_edit_plan(
        {
            "decision": "apply",
            "summary": "Dời bảo tàng",
            "operations": [
                {
                    "operation": "update_time",
                    "target": {"item_id": "museum-1"},
                    "start_time": "10:00",
                }
            ],
        },
        trip_data,
    )

    apply_trip_edit_plan(trip_data, plan)

    assert trip_data["itinerary_items"][0]["start_time"] == "10:00:00"
    assert trip_data["itinerary_items"][0]["end_time"] == "11:30:00"


def test_day_scoped_self_selected_meal_is_preserved_after_replanning() -> None:
    trip_data = _trip_data()
    plan = parse_trip_edit_plan(
        {
            "decision": "apply",
            "summary": "Tự chọn bữa sáng ngày 1",
            "operations": [
                {
                    "operation": "set_meal_preference",
                    "day_number": 1,
                    "meal_kind": "breakfast",
                    "meal_preference": "self_selected",
                }
            ],
        },
        trip_data,
    )

    apply_trip_edit_plan(trip_data, plan)
    trip_data["itinerary_items"].append(
        {
            "id": "breakfast-rebuilt-1",
            "day_number": 1,
            "order_index": 1,
            "item_kind": "breakfast",
            "activity": "Ăn sáng tại Quán Mới",
        }
    )
    _reapply_planning_constraints(trip_data, only_days=(1,))

    assert all(item["id"] != "breakfast-rebuilt-1" for item in trip_data["itinerary_items"])
    assert any(item["id"] == "breakfast-2" for item in trip_data["itinerary_items"])


def test_replan_day_changes_only_the_requested_theme_and_day_items(monkeypatch) -> None:
    trip_data = {
        "hotel": {"id": "hotel-1", "name": "Hotel One", "coordinates": "10.7,106.7", "destination_id": "destination-1"},
        "itineraries": [
            {
                "id": "trip-1",
                "duration_days": 2,
                "number_of_adults": 1,
                "preferences": ["Hồ Chí Minh", "văn hóa"],
                "destination_id": "destination-1",
                "day_themes": [
                    {"day_number": 1, "title": "Văn hóa", "query": "museum"},
                    {"day_number": 2, "title": "Thiên nhiên", "query": "park"},
                ],
            }
        ],
        "itinerary_items": [
            {"id": "day-one", "itinerary_id": "trip-1", "day_number": 1, "order_index": 1, "item_kind": "attraction", "kind": "attraction", "reference_type": "Attraction", "reference_id": "old-day-one", "activity": "Ngày 1", "start_time": "09:00:00", "end_time": "10:30:00", "coordinates": [10.7, 106.7]},
            {"id": "day-two", "itinerary_id": "trip-1", "day_number": 2, "order_index": 1, "item_kind": "attraction", "kind": "attraction", "reference_type": "Attraction", "reference_id": "old-day-two", "activity": "Ngày 2", "start_time": "09:00:00", "end_time": "10:30:00", "coordinates": [10.7, 106.7]},
        ],
    }
    rebuilt = {
        "hotel": trip_data["hotel"],
        "itineraries": [{**trip_data["itineraries"][0], "day_themes": [{"day_number": 1, "title": "Văn hóa", "query": "museum"}, {"day_number": 2, "title": "Ẩm thực", "query": "local food"}]}],
        "itinerary_items": [
            {"id": "rebuilt-day-two", "itinerary_id": "new-trip", "day_number": 2, "order_index": 1, "item_kind": "attraction", "kind": "attraction", "reference_type": "Attraction", "reference_id": "new-day-two", "activity": "Ngày 2 mới", "start_time": "09:00:00", "end_time": "10:30:00", "coordinates": [10.71, 106.71]},
        ],
    }
    captured = {}

    def _build(*_args, **kwargs):
        captured["preferences"] = _args[3]
        captured["themes"] = kwargs["themes_override"]
        captured["exclude_attraction_ids"] = kwargs["exclude_attraction_ids"]
        return rebuilt

    monkeypatch.setattr(trip_builder_svc, "_build_trip_data", _build)
    plan = parse_trip_edit_plan(
        {
            "decision": "apply",
            "summary": "Lập lại ngày 2 theo ẩm thực",
            "operations": [
                {
                    "operation": "replan_day",
                    "day_number": 2,
                    "theme": {"selection_mode": "user_specified", "title": "Ẩm thực", "semantic_query": "ăn sáng"},
                }
            ],
        },
        trip_data,
    )

    apply_trip_edit_plan(trip_data, plan)

    assert any(item["id"] == "day-one" for item in trip_data["itinerary_items"])
    assert any(item["reference_id"] == "new-day-two" for item in trip_data["itinerary_items"])
    assert trip_data["itineraries"][0]["day_themes"][1]["title"] == "Ẩm thực"
    assert captured["preferences"] == "văn hóa"
    assert "markets" in captured["themes"][1]["query"]
    assert captured["exclude_attraction_ids"] == ["old-day-one", "old-day-two"]
    # Bug A: the replanned day must be stamped user_specified so normalize_day_themes
    # (called inside the real _build_trip_data, mocked away here) preserves it verbatim
    # instead of overriding it with the trip's preference-driven theme.
    assert captured["themes"][1]["selection_mode"] == "user_specified"
    assert captured["themes"][0]["day_number"] == 1
    assert "selection_mode" not in captured["themes"][0]


def test_reused_template_day_themes_are_rethemed_not_frozen_from_the_donor_trip(monkeypatch) -> None:
    """A Tier-1 reuse template's day_themes are historical data from a DIFFERENT
    trip. If that donor trip had a user-specified day (selection_mode stamped by
    _apply_day_replan), reusing its themes here must not freeze the donor's
    theme -- re-theming to this trip's own preferences is the entire point of
    reuse (trip_planner.py `_build_trip_data`, reusable_template branch)."""
    from src.services.itinerary_reuse import ItineraryTemplate

    template = ItineraryTemplate(
        id="template-1",
        destination_id="destination-1",
        hotel_id="hotel-1",
        duration_days=1,
        day_themes=(
            {
                "day_number": 1,
                "title": "Donor's theme",
                "query": "donor query",
                "selection_mode": "user_specified",
            },
        ),
    )
    monkeypatch.setattr(trip_builder_svc, "_get_destination_id", lambda _destination: "destination-1")
    monkeypatch.setattr(trip_builder_svc, "_find_reusable_template", lambda _query: template)

    captured = {}

    class _Stop(Exception):
        pass

    def _fake_normalize(raw_themes, _number_of_days, _preferences):
        captured["raw_themes"] = raw_themes
        raise _Stop()

    monkeypatch.setattr(trip_builder_svc, "normalize_day_themes", _fake_normalize)

    hotel = {"id": "hotel-1", "coordinates": "10.7,106.7", "destination_id": "destination-1"}
    try:
        trip_builder_svc._build_trip_data(
            "Đà Nẵng",
            "1 ngày",
            "2 người",
            "ẩm thực",
            preselected_hotel=hotel,
        )
    except _Stop:
        pass

    assert "raw_themes" in captured
    assert captured["raw_themes"][0]["selection_mode"] == "auto"
    assert captured["raw_themes"][0]["title"] == "Donor's theme"
