from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from src.services.trip_scheduler import (
    DayTheme,
    PlaceCandidate,
    PlanningPolicy,
    ScheduledItem,
    apply_latest_outing_start,
    build_itinerary,
    build_itinerary_with_hotel_reselection,
    default_duration_minutes,
    detect_covered_hotel_meals,
    fits_opening_hours,
    haversine_distance_km,
    infer_trip_change,
    normalize_day_themes,
    serialize_day_themes,
    validate_or_repair_day,
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


def test_builds_balanced_day_with_real_food_rest_and_no_noon_beach() -> None:
    theme = DayTheme(1, "Biển và văn hóa", "beach culture")
    beach = place("beach", "My Khe Beach", "Nature & outdoor", 16.0610, 108.2460)
    museum = place("museum", "Cham Museum", "Museums & culture", 16.0602, 108.2235)
    lunch = place("lunch", "Bếp Đà Nẵng Restaurant", "Restaurants & cafes", 16.058, 108.225)
    breakfast = place("breakfast", "Morning Bistro", "Restaurants & cafes", 16.057, 108.224)
    coffee = place("coffee", "Han Coffee", "Restaurants & cafes", 16.057, 108.224)
    dinner = place("dinner", "River Dinner Restaurant", "Restaurants & cafes", 16.058, 108.224)
    evening = place("market", "Han Night Market", "Other activities", 16.059, 108.223)

    schedule = build_itinerary(
        hotel=HOTEL,
        themes=[theme],
        themed_candidates={1: [beach, museum, evening]},
        restaurants=[lunch],
        cafes=[coffee],
        breakfasts=[breakfast],
        dinners=[dinner],
    )

    day = schedule.items_for_day(1)
    assert 7 <= len(day) <= 8
    assert any(item.kind == "breakfast" and item.reference_id == "breakfast" for item in day)
    lunch_item = next(item for item in day if item.kind == "lunch")
    assert lunch_item.reference_id == "lunch"
    assert lunch_item.start_time == "11:30:00"
    assert any(item.kind == "rest" and item.reference_type == "Hotel" for item in day)
    assert any(item.kind == "coffee" and item.reference_id == "coffee" for item in day)
    assert any(item.kind == "dinner" and item.reference_id == "dinner" for item in day)
    beach_item = next(item for item in day if item.reference_id == "beach")
    assert beach_item.start_time < "10:30:00" or beach_item.start_time >= "15:30:00"
    for previous, current in zip(day, day[1:]):
        assert previous.end_time <= current.start_time


def test_missing_morning_attraction_does_not_imply_missing_breakfast() -> None:
    theme = DayTheme(1, "Culture", "culture")
    breakfast = place("breakfast", "Morning Bistro", "Restaurants & cafes", 16.057, 108.224)

    schedule = build_itinerary(
        hotel=HOTEL,
        themes=[theme],
        themed_candidates={1: []},
        restaurants=[],
        cafes=[],
        breakfasts=[breakfast],
        dinners=[],
    )

    day = schedule.items_for_day(1)
    assert any(item.kind == "breakfast" and item.reference_id == "breakfast" for item in day)
    assert any("địa điểm tham quan buổi sáng" in adjustment for adjustment in schedule.adjustments)
    assert not any("điểm ăn sáng" in adjustment for adjustment in schedule.adjustments)


def test_opening_hours_are_enforced_but_unknown_hours_are_allowed() -> None:
    venue = place(
        "museum",
        "Late Museum",
        "Museums & culture",
        16.05,
        108.22,
        opening_time="13:00:00",
        closing_time="17:00:00",
    )
    unknown = replace(venue, id="unknown", opening_time=None, closing_time=None)

    assert not fits_opening_hours(venue, "08:00:00", 90)
    assert fits_opening_hours(venue, "14:00:00", 90)
    assert fits_opening_hours(unknown, "08:00:00", 90)


def test_travel_shift_cannot_push_lunch_past_closing_time() -> None:
    theme = DayTheme(1, "Culture", "culture")
    attraction = place(
        "a1",
        "Morning Culture Tour",
        "Sightseeing tours",
        16.060,
        108.220,
        is_tour=True,
        similarity=1.0,
    )
    second = place("a2", "Pagoda", "Museums & culture", 16.061, 108.221, similarity=0.1)
    closing_lunch = place(
        "lunch",
        "Early Restaurant",
        "Restaurants & cafes",
        16.170,
        108.220,
        opening_time="10:00:00",
        closing_time="12:48:00",
    )
    coffee = place("coffee", "Coffee Shop", "Restaurants & cafes", 16.061, 108.221)

    schedule = build_itinerary(HOTEL, [theme], {1: [attraction, second]}, [closing_lunch], [coffee])
    lunch = next(item for item in schedule.items if item.kind == "lunch")

    assert lunch.reference_type == "Hotel"
    assert lunch.reference_id == HOTEL.id


def test_lunch_moves_later_when_the_morning_activity_needs_more_time() -> None:
    theme = DayTheme(1, "Culture", "culture")
    long_morning = place(
        "a1",
        "Extended Museum Visit",
        "Museums & culture",
        16.055,
        108.203,
        estimated_duration_minutes=200,
        similarity=1.0,
    )
    second = place("a2", "Pagoda", "Museums & culture", 16.056, 108.204)
    lunch_venue = place("lunch", "Local Restaurant", "Restaurants & cafes", 16.056, 108.204)

    schedule = build_itinerary(HOTEL, [theme], {1: [long_morning, second]}, [lunch_venue], [])
    lunch = next(item for item in schedule.items if item.kind == "lunch")

    assert "11:30:00" < lunch.start_time <= "12:30:00"


def test_lunch_never_overlaps_the_fixed_rest_window() -> None:
    theme = DayTheme(1, "Culture", "culture")
    long_morning = place(
        "a1",
        "Extended Museum Visit",
        "Museums & culture",
        16.055,
        108.203,
        estimated_duration_minutes=225,
        similarity=1.0,
    )

    schedule = build_itinerary(HOTEL, [theme], {1: [long_morning]}, [], [])
    day = schedule.items_for_day(1)
    lunch = next(item for item in day if item.kind == "lunch")
    rest = next(item for item in day if item.kind == "rest")

    assert rest.start_time == "13:00:00"
    assert rest.end_time == "14:30:00"
    assert lunch.end_time <= rest.start_time


def test_category_duration_defaults_and_travel_time_are_deterministic() -> None:
    tour = place("tour", "Island Tour", "Sightseeing tours", 16.05, 108.22, is_tour=True)
    restaurant = place("food", "Local Restaurant", "Restaurants & cafes", 16.05, 108.22)
    explicit = replace(tour, estimated_duration_minutes=75)

    assert default_duration_minutes(tour) == 180
    assert default_duration_minutes(restaurant, kind="lunch") == 75
    assert default_duration_minutes(explicit) == 75
    assert 4.9 < haversine_distance_km((16.0544, 108.2022), (16.0994, 108.2022)) < 5.2


def test_same_day_places_prefer_five_kilometre_cluster_over_far_match() -> None:
    theme = DayTheme(1, "Văn hóa", "culture")
    anchor = place("anchor", "Culture Museum", "Museums & culture", 16.060, 108.220, similarity=0.95)
    nearby = place("nearby", "Old Pagoda", "Museums & culture", 16.065, 108.225, similarity=0.75)
    far = place("far", "Famous Far Temple", "Museums & culture", 16.200, 108.350, similarity=0.99)
    lunch = place("lunch", "Nearby Restaurant", "Restaurants & cafes", 16.061, 108.221)
    coffee = place("coffee", "Nearby Coffee", "Restaurants & cafes", 16.062, 108.222)

    schedule = build_itinerary(
        hotel=HOTEL,
        themes=[theme],
        themed_candidates={1: [anchor, nearby, far]},
        restaurants=[lunch],
        cafes=[coffee],
    )

    ids = {item.reference_id for item in schedule.items_for_day(1)}
    assert "anchor" in ids
    assert "nearby" in ids
    assert "far" not in ids


def test_scheduler_prefers_the_lowest_retrieval_tier_before_scoring() -> None:
    theme = DayTheme(1, "Culture", "culture")
    close_tier_one = place(
        "tier-one",
        "Nearby Museum",
        "Museums & culture",
        16.055,
        108.203,
        similarity=0.1,
        rating=3.0,
        retrieval_tier=1,
    )
    strong_tier_two = place(
        "tier-two",
        "High Rated Museum",
        "Museums & culture",
        16.056,
        108.204,
        similarity=1.0,
        rating=5.0,
        retrieval_tier=2,
    )

    schedule = build_itinerary(
        HOTEL,
        [theme],
        {1: [close_tier_one, strong_tier_two]},
        [],
        [],
    )

    morning = next(item for item in schedule.items_for_day(1) if item.order_index == 2)
    assert morning.reference_id == "tier-one"


def test_lunch_prefers_the_route_from_current_stop_back_to_hotel() -> None:
    hotel = place("hotel", "Route Hotel", "Hotel", 16.000, 108.000)
    theme = DayTheme(1, "Culture", "culture")
    morning = place("morning", "Morning Museum", "Museums & culture", 16.000, 108.040, similarity=1.0)
    afternoon = place("afternoon", "Afternoon Gallery", "Museums & culture", 16.001, 108.039, similarity=0.8)
    away_from_hotel = place(
        "lunch-away",
        "Popular Away Restaurant",
        "Restaurants & cafes",
        16.000,
        108.060,
        similarity=0.99,
    )
    on_the_route = place(
        "lunch-route",
        "Route Restaurant",
        "Restaurants & cafes",
        16.000,
        108.020,
        similarity=0.78,
    )

    schedule = build_itinerary(
        hotel,
        [theme],
        {1: [morning, afternoon]},
        [away_from_hotel, on_the_route],
        [],
    )

    lunch = next(item for item in schedule.items_for_day(1) if item.kind == "lunch")
    assert lunch.reference_id == "lunch-route"


def test_dinner_uses_current_coffee_position_instead_of_backtracking() -> None:
    hotel = place("hotel", "Route Hotel", "Hotel", 16.000, 108.000)
    theme = DayTheme(1, "Culture", "culture")
    morning = place("morning", "Morning Museum", "Museums & culture", 16.000, 108.010, similarity=1.0)
    afternoon = place("afternoon", "Afternoon Gallery", "Museums & culture", 16.000, 108.000, similarity=0.8)
    coffee = place("coffee", "Forward Coffee", "Restaurants & cafes", 16.000, 108.010)
    backtracking_dinner = place(
        "dinner-backtrack",
        "Famous Backtrack Restaurant",
        "Restaurants & cafes",
        16.000,
        107.990,
        similarity=0.99,
    )
    nearby_dinner = place(
        "dinner-nearby",
        "Coffee District Restaurant",
        "Restaurants & cafes",
        16.000,
        108.0105,
        similarity=0.90,
    )

    schedule = build_itinerary(
        hotel,
        [theme],
        {1: [morning, afternoon]},
        [],
        [coffee],
        dinners=[backtracking_dinner, nearby_dinner],
    )

    dinner = next(item for item in schedule.items_for_day(1) if item.kind == "dinner")
    assert dinner.reference_id == "dinner-nearby"


def test_reselects_hotel_when_primary_cannot_fill_core_attraction_slots() -> None:
    primary_hotel = place("hotel-far", "Outer Hotel", "Hotel", 16.000, 108.000)
    alternate_hotel = place("hotel-central", "Central Hotel", "Hotel", 16.100, 108.000)
    themes = [DayTheme(1, "City", "city"), DayTheme(2, "Culture", "culture")]
    primary_cluster = [
        place(
            "a1",
            "Outer Stop One",
            "Museums & culture",
            16.001,
            108.000,
            opening_time="07:00:00",
            closing_time="18:00:00",
        ),
        place(
            "a2",
            "Outer Stop Two",
            "Museums & culture",
            16.002,
            108.000,
            opening_time="07:00:00",
            closing_time="18:00:00",
        ),
    ]
    alternate_cluster = [
        place(
            "c1",
            "Central Stop One",
            "Museums & culture",
            16.101,
            108.000,
            opening_time="07:00:00",
            closing_time="18:00:00",
        ),
        place(
            "c2",
            "Central Stop Two",
            "Museums & culture",
            16.102,
            108.000,
            opening_time="07:00:00",
            closing_time="18:00:00",
        ),
    ]

    selected_hotel, schedule = build_itinerary_with_hotel_reselection(
        hotels=[primary_hotel, alternate_hotel],
        themes=themes,
        themed_candidates={
            1: [*primary_cluster, *alternate_cluster],
            2: primary_cluster,
        },
        restaurants=[],
        cafes=[],
    )

    assert selected_hotel.id == alternate_hotel.id
    assert all(
        sum(item.kind == "attraction" for item in schedule.items_for_day(day)) == 2
        for day in (1, 2)
    )
    assert any("Đã đổi khách sạn" in adjustment for adjustment in schedule.adjustments)


def test_playgrounds_are_capped_once_per_trip_unless_child_focused() -> None:
    themes = [DayTheme(1, "Family day", "family"), DayTheme(2, "City day", "city")]
    playgrounds = {
        1: [
            place("p1", "Happy Kid Playground", "Entertainment & tickets", 16.06, 108.22),
            place("a1", "City Museum", "Museums & culture", 16.061, 108.221),
        ],
        2: [
            place("p2", "Children Playground", "Entertainment & tickets", 16.062, 108.222),
            place("a2", "River Park", "Nature & outdoor", 16.063, 108.223),
        ],
    }
    food = [
        place("r1", "Restaurant One", "Restaurants & cafes", 16.061, 108.221),
        place("r2", "Restaurant Two", "Restaurants & cafes", 16.063, 108.223),
    ]
    cafes = [
        place("c1", "Coffee One", "Restaurants & cafes", 16.061, 108.221),
        place("c2", "Coffee Two", "Restaurants & cafes", 16.063, 108.223),
    ]

    default_schedule = build_itinerary(HOTEL, themes, playgrounds, food, cafes)
    child_schedule = build_itinerary(HOTEL, themes, playgrounds, food, cafes, child_focused=True)

    assert sum(item.is_playground for item in default_schedule.items) <= 1
    assert sum(item.is_playground for item in child_schedule.items) <= 2


def test_missing_meal_and_cafe_records_fall_back_to_hotel_not_random_attraction() -> None:
    theme = DayTheme(1, "Culture", "culture")
    attractions = [
        place("a1", "Museum", "Museums & culture", 16.06, 108.22),
        place("a2", "Pagoda", "Museums & culture", 16.061, 108.221),
    ]

    schedule = build_itinerary(HOTEL, [theme], {1: attractions}, [], [])
    day = schedule.items_for_day(1)

    lunch = next(item for item in day if item.kind == "lunch")
    coffee = next(item for item in day if item.kind == "coffee")
    breakfast = next(item for item in day if item.kind == "breakfast")
    dinner = next(item for item in day if item.kind == "dinner")
    assert lunch.reference_type == "Hotel" and lunch.reference_id == HOTEL.id
    assert coffee.reference_type == "Hotel" and coffee.reference_id == HOTEL.id
    assert breakfast.reference_type == "Hotel" and breakfast.reference_id == HOTEL.id
    assert dinner.reference_type == "Hotel" and dinner.reference_id == HOTEL.id


def test_failed_meal_fallbacks_do_not_claim_hotel_meal_inclusion() -> None:
    theme = DayTheme(1, "Culture", "culture")
    attractions = [
        place("a1", "Museum", "Museums & culture", 16.06, 108.22),
        place("a2", "Pagoda", "Museums & culture", 16.061, 108.221),
    ]

    schedule = build_itinerary(HOTEL, [theme], {1: attractions}, [], [])

    assert "Ngày 1: không tìm được địa điểm ăn sáng phù hợp; bạn có thể dùng bữa tại khách sạn hoặc tự chọn địa điểm gần đó." in schedule.adjustments
    assert "Ngày 1: không tìm được nhà hàng phù hợp; bạn có thể dùng bữa tại khách sạn hoặc tự chọn nhà hàng gần đó." in schedule.adjustments
    assert "Ngày 1: không tìm được địa điểm ăn tối phù hợp; bạn có thể dùng bữa tại khách sạn hoặc tự chọn nhà hàng gần đó." in schedule.adjustments


def test_empty_attraction_pools_create_one_fixed_rest_and_local_exploration_placeholders() -> None:
    schedule = build_itinerary(HOTEL, [DayTheme(1, "Culture", "culture")], {1: []}, [], [])
    day = schedule.items_for_day(1)

    rests = [item for item in day if item.kind == "rest"]
    assert len(rests) == 1
    assert rests[0].start_time == "13:00:00"
    assert rests[0].end_time == "14:30:00"

    activity_slots = [item for item in day if item.order_index in {2, 5}]
    assert all(item.kind == "attraction" for item in activity_slots)
    assert all(item.reference_type == "Hotel" and item.reference_id == HOTEL.id for item in activity_slots)
    assert all("Tự do khám phá" in item.activity for item in activity_slots)


def test_scheduler_limits_nature_attractions_to_one_per_day() -> None:
    theme = DayTheme(1, "Nature and culture", "nature culture")
    nature_one = place("nature-one", "City Park", "Nature & outdoor", 16.055, 108.203, similarity=0.95)
    nature_two = place("nature-two", "Riverside Walk", "Nature & outdoor", 16.056, 108.204, similarity=0.9)
    museum = place("museum", "History Museum", "Museums & culture", 16.057, 108.205, similarity=0.7)

    schedule = build_itinerary(HOTEL, [theme], {1: [nature_one, nature_two, museum]}, [], [])
    day = schedule.items_for_day(1)

    nature_items = [item for item in day if item.category == "Nature & outdoor"]
    assert len(nature_items) == 1
    assert any(item.reference_id == "museum" for item in day)


def test_explicit_hotel_meal_coverage_takes_priority_over_outside_venues() -> None:
    hotel = replace(HOTEL, covered_meals=frozenset({"breakfast", "dinner"}))
    theme = DayTheme(1, "Culture", "culture")
    attractions = [
        place("a1", "Museum", "Museums & culture", 16.06, 108.22),
        place("a2", "Pagoda", "Museums & culture", 16.061, 108.221),
    ]
    breakfast = place("b1", "Breakfast Cafe", "Restaurants & cafes", 16.06, 108.22)
    lunch = place("l1", "Lunch Restaurant", "Restaurants & cafes", 16.06, 108.22)
    dinner = place("d1", "Dinner Restaurant", "Restaurants & cafes", 16.06, 108.22)

    schedule = build_itinerary(
        hotel,
        [theme],
        {1: attractions},
        [lunch],
        [],
        breakfasts=[breakfast],
        dinners=[dinner],
    )
    day = schedule.items_for_day(1)

    assert next(item for item in day if item.kind == "breakfast").reference_type == "Hotel"
    assert next(item for item in day if item.kind == "lunch").reference_id == "l1"
    assert next(item for item in day if item.kind == "dinner").reference_type == "Hotel"


def test_hotel_meal_coverage_requires_explicit_inclusion_language() -> None:
    covered = detect_covered_hotel_meals(
        ["Free breakfast", "Restaurant"],
        {
            "Food and drink": ["Dinner included", "Breakfast available"],
            "Breakfast": ["Included"],
        },
    )

    assert covered == frozenset({"breakfast", "dinner"})

    not_covered = detect_covered_hotel_meals(
        ["Breakfast available", "Breakfast not included"],
        {"Lunch": {"Free": False}},
    )
    assert not_covered == frozenset()


def test_normalize_themes_deduplicates_invalid_llm_output_and_fills_days() -> None:
    themes = normalize_day_themes(
        [
            {"day_number": 1, "title": "Ngày 1: Biển", "query": "beach"},
            {"day_number": 2, "title": "Biển", "query": "beach"},
            {"day_number": 99, "title": "Invalid", "query": "invalid"},
        ],
        number_of_days=4,
        preferences=["ẩm thực"],
    )

    assert [theme.day_number for theme in themes] == [1, 2, 3, 4]
    assert themes[0].title.startswith("Trải nghiệm ẩm thực")
    assert len({theme.title.casefold() for theme in themes}) == 4
    assert all("ẩm thực" in f"{theme.title} {theme.query}".casefold() for theme in themes)


def test_user_theme_preference_constrains_every_day_theme() -> None:
    themes = normalize_day_themes(
        [
            {"day_number": 1, "title": "Biển", "query": "beach coast relaxation"},
            {"day_number": 2, "title": "Thiên nhiên", "query": "nature parks hiking"},
            {"day_number": 3, "title": "Mua sắm", "query": "shopping markets city"},
        ],
        number_of_days=3,
        preferences=["ẩm thực"],
    )

    assert len({theme.title.casefold() for theme in themes}) == 3
    assert all("ẩm thực" in theme.title.casefold() for theme in themes)
    assert all("ẩm thực" in theme.query.casefold() for theme in themes)
    assert not any(
        unrelated in theme.query.casefold()
        for theme in themes
        for unrelated in ("beach", "hiking", "shopping")
    )


def test_multiple_theme_preferences_are_applied_to_days_in_order() -> None:
    themes = normalize_day_themes(
        [
            {"day_number": 1, "title": "Unrelated", "query": "shopping city"},
            {"day_number": 2, "title": "Unrelated", "query": "beach coast"},
            {"day_number": 3, "title": "Unrelated", "query": "nightlife entertainment"},
            {"day_number": 4, "title": "Unrelated", "query": "food markets"},
        ],
        number_of_days=4,
        preferences=["văn hóa", "thiên nhiên"],
    )

    expected_preferences = ["văn hóa", "thiên nhiên", "văn hóa", "thiên nhiên"]
    assert [
        next(preference for preference in expected_preferences if preference in theme.title.casefold())
        for theme in themes
    ] == expected_preferences
    assert all(
        preference in theme.query.casefold()
        for preference, theme in zip(expected_preferences, themes, strict=True)
    )


def test_normalize_themes_replaces_malformed_llm_titles_but_keeps_valid_queries() -> None:
    themes = normalize_day_themes(
        [
            {
                "day_number": 1,
                "title": "Đài sưƣn Đông cùi",
                "query": "beach activities in Da Nang",
            },
            {
                "day_number": 2,
                "title": "Phong trên vệ tìch sư",
                "query": "Da Nang cultural experiences",
            },
            {
                "day_number": 3,
                "title": "Đài lôc đài sưƣn",
                "query": "Da Nang food and drink experiences",
            },
        ],
        number_of_days=3,
    )

    assert [theme.title for theme in themes] == [
        "Biển và thư giãn",
        "Văn hóa và di sản",
        "Ẩm thực địa phương",
    ]
    assert [theme.query for theme in themes] == [
        "beach activities in Da Nang",
        "Da Nang cultural experiences",
        "Da Nang food and drink experiences",
    ]


def test_normalize_themes_applies_a_single_preference_to_every_day() -> None:
    themes = normalize_day_themes(
        [
            {"day_number": 1, "title": "Beach day", "query": "beach coast relaxation"},
            {"day_number": 2, "title": "Museum day", "query": "museums culture heritage"},
            {"day_number": 3, "title": "Nature day", "query": "nature outdoor scenic"},
            {"day_number": 4, "title": "City day", "query": "markets city nightlife"},
        ],
        number_of_days=4,
        preferences=["street food"],
    )

    assert [theme.day_number for theme in themes] == [1, 2, 3, 4]
    assert all("street food" in theme.title.casefold() for theme in themes)
    assert all("street food" in theme.query.casefold() for theme in themes)
    assert not any(
        raw_query in theme.query.casefold()
        for theme in themes
        for raw_query in ("beach coast", "museums culture", "nature outdoor", "markets city")
    )


def test_normalize_themes_rotates_multiple_preferences_across_all_days() -> None:
    themes = normalize_day_themes(
        [
            {"day_number": day, "title": f"Unrelated theme {day}", "query": "shopping nightlife"}
            for day in range(1, 6)
        ],
        number_of_days=5,
        preferences=["culture", "nature"],
    )

    expected_preferences = ["culture", "nature", "culture", "nature", "culture"]
    for theme, preference in zip(themes, expected_preferences, strict=True):
        assert preference in theme.title.casefold()
        assert preference in theme.query.casefold()
        assert "shopping nightlife" not in theme.query.casefold()


def test_preference_based_day_themes_have_distinct_semantic_queries() -> None:
    themes = normalize_day_themes(
        [
            {"day_number": day, "title": "Culture", "query": "culture sightseeing"}
            for day in range(1, 4)
        ],
        number_of_days=3,
        preferences=["culture"],
    )

    assert len({theme.title.casefold() for theme in themes}) == 3
    assert len({theme.query.casefold() for theme in themes}) == 3
    assert all("culture" in theme.query.casefold() for theme in themes)


def test_normalize_themes_preserves_raw_semantic_queries_without_preferences() -> None:
    raw_queries = [
        "beach activities in Da Nang",
        "Da Nang cultural experiences",
        "Da Nang food and drink experiences",
    ]
    themes = normalize_day_themes(
        [
            {"day_number": day, "title": "Untrusted LLM title", "query": query}
            for day, query in enumerate(raw_queries, start=1)
        ],
        number_of_days=3,
        preferences=[],
    )

    assert [theme.query for theme in themes] == raw_queries
    assert all(theme.title != "Untrusted LLM title" for theme in themes)
    assert len({theme.title.casefold() for theme in themes}) == 3


def test_day_themes_have_a_database_safe_json_payload() -> None:
    payload = serialize_day_themes(
        [
            DayTheme(1, "Biển và thư giãn", "beach activities in Da Nang"),
            DayTheme(2, "Văn hóa và di sản", "Da Nang cultural experiences"),
        ]
    )

    assert payload == [
        {
            "day_number": 1,
            "title": "Biển và thư giãn",
            "query": "beach activities in Da Nang",
        },
        {
            "day_number": 2,
            "title": "Văn hóa và di sản",
            "query": "Da Nang cultural experiences",
        },
    ]


def test_itineraries_schema_has_an_additive_day_themes_jsonb_migration() -> None:
    root = Path(__file__).resolve().parents[1]
    schema = (root / "scripts" / "database_schema.sql").read_text(encoding="utf-8")
    migration = (root / "scripts" / "migrations" / "20260727_add_itinerary_day_themes.sql").read_text(
        encoding="utf-8"
    )

    assert "day_themes JSONB NOT NULL DEFAULT '[]'::jsonb" in schema
    assert "ALTER TABLE itineraries" in migration
    assert "ADD COLUMN IF NOT EXISTS day_themes JSONB NOT NULL DEFAULT '[]'::jsonb" in migration


def test_generated_trip_json_keeps_day_themes_only_with_the_itinerary_record() -> None:
    """This is the serialization shape in the relocated trip_planner.py, unaffected
    by the session-state rewrite — a genuine pure relocation, so repointing the
    path is enough."""
    root = Path(__file__).resolve().parents[1]
    svc = (root / "src" / "services" / "trip_planner.py").read_text(encoding="utf-8")

    assert svc.count('"day_themes": day_themes,') == 1


def test_validate_repairs_noon_beach_overlap_and_excess_playground() -> None:
    beach = place("beach", "City Beach", "Nature & outdoor", 16.06, 108.22)
    p1 = place("p1", "Kid Playground One", "Entertainment & tickets", 16.061, 108.221)
    p2 = place("p2", "Kid Playground Two", "Entertainment & tickets", 16.062, 108.222)
    items = [
        ScheduledItem.from_candidate(1, 1, beach, "attraction", "12:00:00", 120),
        ScheduledItem.from_candidate(1, 2, p1, "attraction", "12:30:00", 90),
        ScheduledItem.from_candidate(1, 3, p2, "attraction", "13:00:00", 90),
    ]

    repaired, adjustments = validate_or_repair_day(items, HOTEL, PlanningPolicy())

    repaired_beach = next(item for item in repaired if item.reference_id == "beach")
    assert repaired_beach.start_time >= "15:30:00"
    assert sum(item.is_playground for item in repaired) <= 1
    assert all(previous.end_time <= current.start_time for previous, current in zip(repaired, repaired[1:]))
    assert adjustments


def test_validate_replaces_a_venue_when_known_hours_cannot_fit() -> None:
    closed = place(
        "closed",
        "Morning-only Museum",
        "Museums & culture",
        16.06,
        108.22,
        opening_time="08:00:00",
        closing_time="09:00:00",
    )
    item = ScheduledItem.from_candidate(1, 1, closed, "attraction", "10:00:00", 90)

    repaired, adjustments = validate_or_repair_day([item], HOTEL)

    assert len(repaired) == 1
    assert repaired[0].reference_type == "Hotel"
    assert repaired[0].reference_id == HOTEL.id
    assert repaired[0].kind == "attraction"
    assert "Tự do khám phá" in repaired[0].activity
    assert adjustments


def test_day_repair_keeps_one_rest_at_the_fixed_daily_window() -> None:
    early_rest = ScheduledItem.from_candidate(1, 1, HOTEL, "rest", "11:00:00", 90)
    late_rest = ScheduledItem.from_candidate(1, 2, HOTEL, "rest", "17:00:00", 90)

    repaired, adjustments = validate_or_repair_day([early_rest, late_rest], HOTEL)

    rests = [item for item in repaired if item.kind == "rest"]
    assert len(rests) == 1
    assert rests[0].start_time == "13:00:00"
    assert rests[0].end_time == "14:30:00"
    assert adjustments


def test_obvious_edit_intents_are_classified_without_llm_guessing() -> None:
    hotel_change = infer_trip_change("đổi khách sạn gần biển")
    reschedule = infer_trip_change("chuyển hoạt động 2 ngày 3 sang 14h30")

    assert hotel_change.action == "change_hotel"
    assert reschedule.action == "reschedule"
    assert reschedule.day_number == 3
    assert reschedule.order_index == 2
    assert reschedule.requested_time == "14:30"


def test_negative_evening_request_sets_a_persistent_outing_cutoff() -> None:
    change = infer_trip_change("buổi tối sau 20h tôi không muốn đi đâu nữa")

    assert change is not None
    assert change.action == "set_latest_outing_start"
    assert change.requested_time == "20:00"
    assert change.day_numbers == ()


def test_evening_cutoff_extracts_multiple_explicit_days() -> None:
    change = infer_trip_change("ngày 1 và ngày 3 sau 20:00 không đi chơi nữa")

    assert change is not None
    assert change.action == "set_latest_outing_start"
    assert change.day_numbers == (1, 3)


def test_self_selected_breakfast_is_classified_as_a_trip_wide_meal_preference() -> None:
    change = infer_trip_change("tôi muốn tự chọn chỗ ăn sáng")

    assert change is not None
    assert change.action == "set_meal_self_selected"
    assert change.meal_kind == "breakfast"
    assert change.day_numbers == ()


def test_latest_outing_cutoff_removes_only_non_hotel_starts_at_or_after_cutoff() -> None:
    items = [
        {"id": "a", "day_number": 1, "order_index": 1, "start_time": "19:30:00", "reference_type": "Attraction"},
        {"id": "b", "day_number": 1, "order_index": 2, "start_time": "20:00:00", "reference_type": "Attraction"},
        {"id": "c", "day_number": 1, "order_index": 3, "start_time": "20:30:00", "reference_type": "Hotel"},
        {"id": "d", "day_number": 2, "order_index": 1, "start_time": "21:00:00", "reference_type": "Attraction"},
    ]

    repaired, removed = apply_latest_outing_start(items, (1,), "20:00")

    assert [item["id"] for item in repaired] == ["a", "c", "d"]
    assert removed == ("b",)
    assert [item["order_index"] for item in repaired if item["day_number"] == 1] == [1, 2]
