from __future__ import annotations

from src.services.trip_formatter import (
    format_hotel_options,
    format_trip_response_from_json,
    parse_duration_to_days,
    to_hotel_options_payload,
    to_trip_plan_payload,
)
from src.services.trip_scheduler import PlaceCandidate

# Shape matches a real data/current_trip_plan.json bundle as written by
# services/trip_planner.py's _build_trip_data / _save_trip_data — a "hotel" dict,
# an "itineraries" list with one record, "itinerary_items" flat across all days,
# and "adjustments".
TRIP_PLAN_FIXTURE = {
    "hotel": {
        "id": "11111111-1111-1111-1111-111111111111",
        "name": "Muong Thanh Grand Đà Nẵng",
        "star_rating": 4,
        "description": "Khách sạn trung tâm gần biển",
        "matched_rooms": ["Deluxe Ocean View", "Family Suite"],
        "coordinates": "16.054,108.24",
    },
    "itineraries": [
        {
            "id": "22222222-2222-2222-2222-222222222222",
            "session_id": "test-session-abc",
            "destination_id": "33333333-3333-3333-3333-333333333333",
            "duration_days": 2,
            "number_of_adults": 2,
            "number_of_children": 0,
            "budget": None,
            "preferences": ["Đà Nẵng", "biển"],
            "day_themes": [
                {"day_number": 1, "title": "Khám phá bãi biển", "query": "beach"},
                {"day_number": 2, "title": "Văn hóa và di sản", "query": "culture heritage"},
            ],
            "planning_constraints": {},
            "status": "Draft",
        }
    ],
    "itinerary_items": [
        {
            "id": "item-1",
            "day_number": 1,
            "order_index": 1,
            "start_time": "08:00:00",
            "end_time": "09:00:00",
            "activity": "Ăn sáng tại khách sạn",
            "kind": "breakfast",
            "item_kind": "breakfast",
            "reference_type": "Hotel",
            "reference_id": "11111111-1111-1111-1111-111111111111",
        },
        {
            "id": "item-2",
            "day_number": 1,
            "order_index": 2,
            "start_time": "09:30:00",
            "end_time": "11:30:00",
            "activity": "Tham quan Bãi biển Mỹ Khê",
            "kind": "attraction",
            "item_kind": "attraction",
            "reference_type": "Attraction",
            "reference_id": "44444444-4444-4444-4444-444444444444",
        },
        {
            "id": "item-3",
            "day_number": 2,
            "order_index": 1,
            "start_time": "09:00:00",
            "end_time": "11:00:00",
            "activity": "Tham quan Bảo tàng Chăm",
            "kind": "attraction",
            "item_kind": "attraction",
            "reference_type": "Attraction",
            "reference_id": "55555555-5555-5555-5555-555555555555",
        },
    ],
    "adjustments": ["Đã dùng chủ đề từ lịch trình tương tự và lập lại lịch mới theo dữ liệu hiện tại."],
}

# Shape matches the pending_hotel_selection payload tools/recommend_hotels.py
# returns via Command(update={"pending_hotel_selection": ...}).
PENDING_HOTEL_SELECTION_FIXTURE = {
    "mode": "new_trip",
    "destination": "Đà Nẵng",
    "destination_id": "33333333-3333-3333-3333-333333333333",
    "duration": "2 ngày",
    "people": "2 người",
    "preferences_text": "",
    "hotel_query": None,
    "created_at": "2026-07-31T00:00:00",
    "options": [
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "name": "Muong Thanh Grand Đà Nẵng",
            "star_rating": 4,
            "description": "Khách sạn trung tâm gần biển",
            "matched_rooms": ["Deluxe Ocean View", "Family Suite"],
            "rank": 1,
        },
        {
            "id": "66666666-6666-6666-6666-666666666666",
            "name": "Vinpearl Resort",
            "star_rating": 5,
            "description": "Resort riêng biệt với bãi biển riêng",
            "matched_rooms": ["Ocean Suite"],
            "rank": 2,
        },
    ],
}


def test_to_trip_plan_payload_none_when_no_bundle():
    assert to_trip_plan_payload(None) is None
    assert to_trip_plan_payload({}) is None


def test_to_trip_plan_payload_shape_from_real_bundle():
    payload = to_trip_plan_payload(TRIP_PLAN_FIXTURE)

    assert payload["status"] == "Draft"
    assert payload["destination"] == "Đà Nẵng"
    assert payload["duration_days"] == 2
    assert payload["number_of_adults"] == 2
    assert payload["hotel"]["id"] == "11111111-1111-1111-1111-111111111111"
    assert payload["hotel"]["name"] == "Muong Thanh Grand Đà Nẵng"
    assert payload["hotel"]["matched_rooms"] == ["Deluxe Ocean View", "Family Suite"]
    assert len(payload["days"]) == 2

    day_one = payload["days"][0]
    assert day_one["day_number"] == 1
    assert day_one["theme"] == "Khám phá bãi biển"
    assert [item["order_index"] for item in day_one["items"]] == [1, 2]
    assert day_one["items"][0]["kind"] == "breakfast"
    assert day_one["items"][1]["reference_type"] == "Attraction"

    day_two = payload["days"][1]
    assert day_two["day_number"] == 2
    assert day_two["theme"] == "Văn hóa và di sản"
    assert len(day_two["items"]) == 1

    assert payload["adjustments"] == TRIP_PLAN_FIXTURE["adjustments"]


def test_to_trip_plan_payload_produces_empty_day_when_no_items_scheduled():
    bundle = {
        "hotel": {},
        "itineraries": [{"duration_days": 1, "status": "Draft"}],
        "itinerary_items": [],
        "adjustments": [],
    }
    payload = to_trip_plan_payload(bundle)

    assert len(payload["days"]) == 1
    assert payload["days"][0]["items"] == []


def test_to_hotel_options_payload_empty_when_no_pending_selection():
    assert to_hotel_options_payload(None) == []
    assert to_hotel_options_payload({}) == []


def test_to_hotel_options_payload_includes_date_aware_price_fields():
    payload = to_hotel_options_payload(
        {
            "options": [
                {
                    "id": "hotel-1",
                    "name": "Beach Hotel",
                    "average_nightly_price": 1_100_000,
                    "total_stay_price": 2_200_000,
                    "stay_night_count": 2,
                    "currency": "VND",
                }
            ]
        }
    )

    assert payload[0]["average_nightly_price"] == 1_100_000
    assert payload[0]["total_stay_price"] == 2_200_000
    assert payload[0]["stay_night_count"] == 2
    assert payload[0]["currency"] == "VND"


def test_format_hotel_options_shows_average_nightly_and_total_stay_price():
    hotel = {
        "id": "hotel-1",
        "name": "Beach Hotel",
        "coordinates": "16.05,108.2",
        "rank": 1,
        "average_nightly_price": 1_100_000,
        "total_stay_price": 2_200_000,
        "stay_night_count": 2,
        "currency": "VND",
    }
    candidate = PlaceCandidate.from_mapping({**hotel, "category": "Hotel"})

    text = format_hotel_options([(hotel, candidate)])

    assert "1,100,000 VND/đêm" in text
    assert "Tổng 2 đêm: 2,200,000 VND" in text


def test_to_hotel_options_payload_shape_from_real_bundle():
    payload = to_hotel_options_payload(PENDING_HOTEL_SELECTION_FIXTURE)

    assert len(payload) == 2
    assert payload[0] == {
        "index": 1,
        "id": "11111111-1111-1111-1111-111111111111",
        "name": "Muong Thanh Grand Đà Nẵng",
        "star_rating": 4,
        "description": "Khách sạn trung tâm gần biển",
        "matched_rooms": ["Deluxe Ocean View", "Family Suite"],
    }
    assert payload[1]["index"] == 2
    assert payload[1]["id"] == "66666666-6666-6666-6666-666666666666"


def test_to_hotel_options_payload_skips_non_dict_options():
    payload = to_hotel_options_payload({"options": [None, "not a dict", {"id": "ok", "name": "X"}]})

    assert len(payload) == 1
    assert payload[0]["id"] == "ok"


def test_parse_duration_to_days_matches_the_original_behaviour():
    assert parse_duration_to_days("2 ngày") == 2
    assert parse_duration_to_days("1 tuần") == 7
    assert parse_duration_to_days("") == 3


def test_format_trip_response_from_json_still_renders_the_fixture():
    text = format_trip_response_from_json(TRIP_PLAN_FIXTURE)

    assert "Muong Thanh Grand Đà Nẵng" in text
    # Raw themes carry a "query", so format_trip_response_from_json re-derives the
    # title through normalize_day_themes rather than trusting the stored title verbatim.
    assert "Ngày 1 - Biển và thư giãn:" in text
    assert "Ngày 2 - Văn hóa và di sản:" in text
    assert "Tham quan Bãi biển Mỹ Khê" in text


def test_format_hotel_options_still_renders_the_fixture():
    options = [
        (
            option,
            PlaceCandidate.from_mapping({**option, "category": "Hotel", "coordinates": "16.05,108.2"}),
        )
        for option in PENDING_HOTEL_SELECTION_FIXTURE["options"]
    ]
    text = format_hotel_options(options)

    assert "Muong Thanh Grand Đà Nẵng" in text
    assert "Vinpearl Resort" in text
