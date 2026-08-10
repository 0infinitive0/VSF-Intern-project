from src.services.trip_planner import _calculate_trip_budget, _serialize_schedule_item
from src.services.trip_scheduler import ScheduledItem


def test_calculate_trip_budget_includes_quoted_hotel_stay_and_known_item_costs():
    budget = _calculate_trip_budget(
        {"total_stay_price": 2_000_000, "currency": "VND"},
        [
            {"estimated_cost": 150_000},
            {"estimated_cost": 100_000},
            {"estimated_cost": None},
        ],
    )

    assert budget == 2_250_000


def test_calculate_trip_budget_returns_none_without_any_known_cost():
    assert _calculate_trip_budget({}, [{"estimated_cost": None}]) is None


def test_serialized_attraction_cost_scales_with_number_of_adults():
    item = ScheduledItem(
        day_number=1,
        order_index=1,
        start_time="09:00:00",
        end_time="10:00:00",
        reference_type="Attraction",
        reference_id="attraction-1",
        activity="Museum visit",
        kind="attraction",
        place_name="Museum",
        coordinates=None,
        duration_minutes=60,
        ticket_price_adult=75_000,
    )

    serialized = _serialize_schedule_item(item, "itinerary-1", "2026-08-10T00:00:00", 2)

    assert serialized["estimated_cost"] == 150_000
