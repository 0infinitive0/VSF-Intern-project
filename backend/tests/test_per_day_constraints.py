from __future__ import annotations

from src.services.trip_scheduler import (
    DayTheme,
    PlaceCandidate,
    build_itinerary,
)

HOTEL = PlaceCandidate(
    id="hotel-1",
    name="Central Hotel",
    category="Hotel",
    coordinates="16.0544,108.2022",
)


def place(
    place_id: str,
    name: str,
    category: str,
    latitude: float,
    longitude: float,
    **overrides: object,
) -> PlaceCandidate:
    values = {
        "id": place_id,
        "name": name,
        "category": category,
        "coordinates": f"{latitude},{longitude}",
        "similarity": 0.9,
        "rating": 4.5,
    }
    values.update(overrides)
    return PlaceCandidate(**values)


def test_one_item_per_day_bounds_strictly() -> None:
    theme = DayTheme(1, "Culture", "culture")
    p1 = place("p1", "Museum 1", "Museums & culture", 16.0602, 108.2235)
    p2 = place("p2", "Museum 2", "Museums & culture", 16.0612, 108.2245)
    p3 = place("p3", "Museum 3", "Museums & culture", 16.0622, 108.2255)

    schedule = build_itinerary(
        hotel=HOTEL,
        themes=[theme],
        themed_candidates={1: [p1, p2, p3]},
        restaurants=[],
        cafes=[],
        planning_constraints={"max_items_per_day": 1}
    )

    day = schedule.items_for_day(1)
    attractions = [item for item in day if item.kind in ("attraction", "evening") and item.reference_id != "hotel-1"]
    assert len(attractions) == 1
    
    assert any("đã đạt giới hạn số lượng 1 địa điểm" in adj for adj in schedule.adjustments)


def test_ten_items_per_day_yields_up_to_slots_and_does_not_fail() -> None:
    theme = DayTheme(1, "Culture", "culture")
    p1 = place("p1", "Museum 1", "Museums & culture", 16.0602, 108.2235)
    p2 = place("p2", "Museum 2", "Museums & culture", 16.0612, 108.2245)
    p3 = place("p3", "Museum 3", "Museums & culture", 16.0622, 108.2255)

    schedule = build_itinerary(
        hotel=HOTEL,
        themes=[theme],
        themed_candidates={1: [p1, p2, p3]},
        restaurants=[],
        cafes=[],
        planning_constraints={"max_items_per_day": 10}
    )

    day = schedule.items_for_day(1)
    attractions = [item for item in day if item.kind in ("attraction", "evening") and item.reference_id != "hotel-1"]
    assert len(attractions) == 3
    # It just naturally scheduled 3 because it ran out of slots, which is "up to 10".
    assert not any("đã đạt giới hạn số lượng 10 địa điểm" in adj for adj in schedule.adjustments)


def test_distance_bound_restricts_candidates() -> None:
    theme = DayTheme(1, "Culture", "culture")
    # p1 is near hotel, p2 is very far
    p1 = place("p1", "Museum 1", "Museums & culture", 16.0602, 108.2235)
    p2 = place("p2", "Museum 2", "Museums & culture", 10.762622, 106.660172) # HCMC
    p3 = place("p3", "Museum 3", "Museums & culture", 16.0605, 108.2238)

    schedule = build_itinerary(
        hotel=HOTEL,
        themes=[theme],
        themed_candidates={1: [p1, p2, p3]},
        restaurants=[],
        cafes=[],
        planning_constraints={"max_item_distance_km": 1.0}
    )

    day = schedule.items_for_day(1)
    attractions = [item for item in day if item.kind in ("attraction", "evening") and item.reference_id != "hotel-1"]
    # Should schedule p1, and maybe p3 (which is close to p1 and hotel). p2 is excluded.
    scheduled_ids = [a.reference_id for a in attractions]
    assert "p2" not in scheduled_ids
    assert len(attractions) <= 2
    if len(attractions) < 3:
        assert any("không tìm được" in adj and "trong bán kính 1.0km" in adj for adj in schedule.adjustments)


def test_meal_and_rest_do_not_count_towards_limit() -> None:
    theme = DayTheme(1, "Culture", "culture")
    p1 = place("p1", "Museum 1", "Museums & culture", 16.0602, 108.2235)
    p2 = place("p2", "Museum 2", "Museums & culture", 16.0612, 108.2245)
    lunch = place("lunch", "Bếp Đà Nẵng", "Restaurants & cafes", 16.058, 108.225)
    dinner = place("dinner", "River Dinner", "Restaurants & cafes", 16.058, 108.224)

    schedule = build_itinerary(
        hotel=HOTEL,
        themes=[theme],
        themed_candidates={1: [p1, p2]},
        restaurants=[lunch],
        cafes=[],
        dinners=[dinner],
        planning_constraints={"max_items_per_day": 1}
    )

    day = schedule.items_for_day(1)
    attractions = [item for item in day if item.kind in ("attraction", "evening") and item.reference_id != "hotel-1"]
    assert len(attractions) == 1
    assert any(item.kind == "lunch" and item.reference_id == "lunch" for item in day)
    assert any(item.kind == "dinner" and item.reference_id == "dinner" for item in day)


def test_per_day_override_takes_precedence() -> None:
    theme1 = DayTheme(1, "Culture", "culture")
    theme2 = DayTheme(2, "Nature", "nature")
    pool1 = [
        place("p1", "Museum 1", "Museums & culture", 16.0602, 108.2235),
        place("p2", "Museum 2", "Museums & culture", 16.0612, 108.2245),
        place("p3", "Museum 3", "Museums & culture", 16.0622, 108.2255),
    ]
    pool2 = [
        place("p4", "Nature 1", "Nature", 16.0602, 108.2235),
        place("p5", "Nature 2", "Nature", 16.0612, 108.2245),
        place("p6", "Nature 3", "Nature", 16.0622, 108.2255),
    ]

    schedule = build_itinerary(
        hotel=HOTEL,
        themes=[theme1, theme2],
        themed_candidates={1: pool1, 2: pool2},
        restaurants=[],
        cafes=[],
        planning_constraints={
            "max_items_per_day": 3,
            "max_items_by_day": {"2": 1}
        }
    )

    day1 = schedule.items_for_day(1)
    attractions1 = [item for item in day1 if item.kind in ("attraction", "evening") and item.reference_id != "hotel-1"]
    assert len(attractions1) == 3

    day2 = schedule.items_for_day(2)
    attractions2 = [item for item in day2 if item.kind in ("attraction", "evening") and item.reference_id != "hotel-1"]
    assert len(attractions2) == 1
