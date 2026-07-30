import pytest
from src.services.itinerary_reuse import (
    ItineraryReuseQuery,
    ItineraryTemplate,
    build_reuse_fingerprint,
    classify_reuse_candidate,
    validate_template_bundle,
)
from src.services.trip_scheduler import (
    PlanningPolicy,
    PlaceCandidate,
    fits_opening_hours,
    haversine_distance_km,
)

HCM_ID = "6f860287-189e-46db-81f6-cd3c7ee5f1f7"


def test_build_reuse_fingerprint_reproducible():
    query1 = ItineraryReuseQuery(
        destination_id=HCM_ID,
        destination_name="Hồ Chí Minh",
        duration_days=3,
        number_of_adults=1,
        number_of_children=0,
        preferences=("lịch sử", "văn hóa"),
        child_focused=False,
        hotel_id="hotel-1",
    )
    query2 = ItineraryReuseQuery(
        destination_id=HCM_ID,
        destination_name="Hồ Chí Minh",
        duration_days=3,
        number_of_adults=1,
        number_of_children=0,
        preferences=("Văn Hóa", "Lịch Sử"),
        child_focused=False,
        hotel_id="hotel-1",
    )
    fp1 = build_reuse_fingerprint(query1)
    fp2 = build_reuse_fingerprint(query2)

    assert fp1.summary == fp2.summary
    assert fp1.content_hash == fp2.content_hash


def test_classify_reuse_candidate_qualified():
    query = ItineraryReuseQuery(
        destination_id=HCM_ID,
        destination_name="Hồ Chí Minh",
        duration_days=1,
        number_of_adults=1,
        hotel_id="hotel-1",
    )
    items = tuple(
        {
            "day_number": 1,
            "order_index": i + 1,
            "start_time": f"{8+i:02d}:00:00",
            "end_time": f"{9+i:02d}:00:00",
            "reference_type": "Attraction",
            "reference_id": f"00000000-0000-0000-0000-{i:012d}",
            "kind": "attraction" if i % 2 == 0 else "rest",
        }
        for i in range(7)
    )
    template = ItineraryTemplate(
        id="golden-template-1",
        destination_id=HCM_ID,
        hotel_id="hotel-1",
        duration_days=1,
        status="Finalized",
        similarity=0.92,
        day_themes=({"day_number": 1, "title": "Sài Gòn Historic"},),
        items=items,
    )

    decision = classify_reuse_candidate(template, query, threshold=0.88)
    assert decision.action == "reuse"
    assert decision.reason == "qualified"
    assert decision.template_id == "golden-template-1"


def test_classify_reuse_candidate_rejected_duration_mismatch():
    query = ItineraryReuseQuery(
        destination_id=HCM_ID,
        destination_name="Hồ Chí Minh",
        duration_days=3,
        hotel_id="hotel-1",
    )
    template = ItineraryTemplate(
        id="golden-template-2",
        destination_id=HCM_ID,
        hotel_id="hotel-1",
        duration_days=5,  # Mismatch 5 vs 3
        status="Finalized",
        similarity=0.95,
        day_themes=(),
        items=(),
    )
    decision = classify_reuse_candidate(template, query, threshold=0.88)
    assert decision.action == "miss"
    assert decision.reason == "duration_mismatch"


def test_recommendation_opening_hours_filtering():
    candidate_open = PlaceCandidate(
        id="place-open",
        name="Bảo tàng Chứng tích Chiến tranh",
        opening_time="07:30:00",
        closing_time="17:30:00",
    )
    candidate_closed = PlaceCandidate(
        id="place-closed",
        name="Quán Bar Đêm",
        opening_time="18:00:00",
        closing_time="02:00:00",
    )

    # 10:00 AM check
    assert fits_opening_hours(candidate_open, "10:00:00", 60) is True
    assert fits_opening_hours(candidate_closed, "10:00:00", 60) is False


def test_haversine_distance_recommendation_clustering():
    coords_hcm_center = (10.7769, 106.7009)  # Dinh Độc Lập / Quận 1
    coords_ben_thanh = (10.7725, 106.6980)   # Chợ Bến Thành (~0.5 km)
    coords_cu_chi = (11.1424, 106.4623)      # Địa đạo Củ Chi (~55 km)

    dist_near = haversine_distance_km(coords_hcm_center, coords_ben_thanh)
    dist_far = haversine_distance_km(coords_hcm_center, coords_cu_chi)

    assert dist_near < 1.0
    assert dist_far > 40.0
