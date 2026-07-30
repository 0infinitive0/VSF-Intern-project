from __future__ import annotations

from src.services.itinerary_reuse import (
    ItineraryReuseQuery,
    ItineraryTemplate,
    build_itinerary_summary,
    build_reuse_fingerprint,
    classify_reuse_candidate,
    validate_template_bundle,
)


def query() -> ItineraryReuseQuery:
    return ItineraryReuseQuery(
        destination_id="destination-da-nang",
        destination_name="Đà Nẵng",
        duration_days=2,
        number_of_adults=2,
        number_of_children=1,
        preferences=("ẩm thực", "beach", "ẨM THỰC"),
        child_focused=True,
        hotel_id="hotel-1",
    )


def valid_template(**overrides: object) -> ItineraryTemplate:
    values = {
        "id": "template-1",
        "destination_id": "destination-da-nang",
        "hotel_id": "hotel-1",
        "duration_days": 2,
        "number_of_adults": 2,
        "number_of_children": 1,
        "day_themes": (
            {"day_number": 1, "title": "Biển", "query": "beach relaxation"},
            {"day_number": 2, "title": "Ẩm thực", "query": "local food"},
        ),
        "items": tuple(
            {
                "day_number": day,
                "order_index": order,
                "reference_type": "Hotel" if order in {1, 4} else "Attraction",
                "reference_id": f"place-{day}-{order}",
                "item_kind": "rest" if order == 4 else "attraction",
                "start_time": f"0{7 + order}:00:00",
                "end_time": f"0{8 + order}:00:00",
            }
            for day in (1, 2)
            for order in range(1, 8)
        ),
        "status": "Finalized",
        "similarity": 0.93,
    }
    values.update(overrides)
    return ItineraryTemplate(**values)


def test_fingerprint_is_stable_for_reordered_preferences() -> None:
    first = build_reuse_fingerprint(query())
    second = build_reuse_fingerprint(
        ItineraryReuseQuery(
            destination_id="destination-da-nang",
            destination_name="Đà Nẵng",
            duration_days=2,
            number_of_adults=2,
            number_of_children=1,
            preferences=("beach", "ẩm thực"),
            child_focused=True,
            hotel_id="hotel-1",
        )
    )

    assert first.summary == second.summary
    assert first.content_hash == second.content_hash
    assert "destination_id=destination-da-nang" in first.summary


def test_summary_excludes_volatile_place_ids_and_times() -> None:
    summary = build_itinerary_summary(
        query(),
        day_themes=[{"day_number": 1, "title": "Biển", "query": "beach relaxation"}],
        hotel={"id": "hotel-uuid", "star_rating": 4, "covered_meals": ["breakfast"]},
        items=[
            {
                "reference_id": "attraction-uuid",
                "reference_type": "Attraction",
                "item_kind": "attraction",
                "category": "Nature & outdoor",
                "start_time": "08:00:00",
            }
        ],
    )

    assert "hotel-uuid" not in summary
    assert "attraction-uuid" not in summary
    assert "08:00:00" not in summary
    assert "Khách sạn: 4 sao; bao gồm bữa ăn: bữa sáng." in summary


def test_summary_is_deterministic_human_readable_vietnamese() -> None:
    summary = build_itinerary_summary(
        query(),
        day_themes=[
            {"day_number": 2, "title": "Ẩm thực", "query": "local food"},
            {"day_number": 1, "title": "Biển", "query": "beach relaxation"},
        ],
        hotel={"star_rating": 4, "covered_meals": ["breakfast"]},
        items=[
            {"item_kind": "coffee", "category": "Food"},
            {"item_kind": "attraction", "category": "Nature"},
            {"item_kind": "attraction", "category": "Nature"},
        ],
        budget="mid-range",
    )

    assert summary == (
        "Chuyến đi 2 ngày tại Đà Nẵng dành cho 2 người lớn và 1 trẻ em. "
        "Sở thích: beach, ẩm thực. Chuyến đi ưu tiên trải nghiệm phù hợp với trẻ em. "
        "Khách sạn: 4 sao; bao gồm bữa ăn: bữa sáng. "
        "Ngày 1: Biển — beach relaxation. Ngày 2: Ẩm thực — local food. "
        "Hoạt động trong lịch trình: tham quan, nghỉ tại quán cà phê. "
        "Nhóm địa điểm: food, nature. Ngân sách: mid-range."
    )
    assert "destination_id=" not in summary
    assert " | " not in summary


def test_template_bundle_requires_complete_real_item_references() -> None:
    valid, reasons = validate_template_bundle(valid_template())
    assert valid
    assert reasons == ()

    invalid, reasons = validate_template_bundle(
        valid_template(items=valid_template().items[:-1])
    )
    assert not invalid
    assert "incomplete_day_2" in reasons


def test_only_exact_safe_candidate_is_reused() -> None:
    decision = classify_reuse_candidate(valid_template(), query(), threshold=0.88)
    assert decision.action == "reuse"
    assert decision.template_id == "template-1"

    decision = classify_reuse_candidate(
        valid_template(destination_id="other-destination"), query(), threshold=0.88
    )
    assert decision.action == "miss"
    assert decision.reason == "destination_mismatch"

    decision = classify_reuse_candidate(
        valid_template(hotel_id="hotel-2"), query(), threshold=0.88
    )
    assert decision.action == "miss"
    assert decision.reason == "hotel_mismatch"

    decision = classify_reuse_candidate(
        valid_template(similarity=0.80), query(), threshold=0.88
    )
    assert decision.action == "miss"
    assert decision.reason == "below_threshold"
