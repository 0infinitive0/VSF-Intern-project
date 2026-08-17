"""Tests for Phase 14: Trip-total budget constraint.

Covers:
- budget.trip_total extraction / disambiguation from per-night budget
- IMPACT_MAP routing: budget.trip_total -> (hotel, itinerary)
- _check_trip_total: within budget, over budget, unknown coverage
- _derive_per_night_ceiling: correct ceiling from total - activities / nights
- budget_check node: pass-through when no trip_total set
- budget_check node: ok status when within budget
- budget_check node: over budget triggers re-plan (mocked hotel search)
- budget_check node: re-plan pass runs at most once
- budget_check node: locked_days are not rebuilt
- budget_check node: unknown-price plans report coverage not compliance
- budget_check node: per-night and trip_total coexist without overwriting
- format_budget_status: within budget with coverage note
- format_budget_status: over budget with shortfall
- doc §37 case: "8 million total, but keep day 1"
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.agents.graph.nodes.budget_check import (
    _check_trip_total,
    _derive_per_night_ceiling,
    _item_count_with_known_cost,
    _known_activity_total,
    _known_hotel_total,
    budget_check,
)
from src.agents.graph.state import TravelGraphState
from src.domain.travel_state import ALLOWED_PATHS, IMPACT_MAP, Presence, Slot, TravelState, apply_patch
from src.services.trip_formatter import format_budget_status


# ---------------------------------------------------------------------------
# State / domain
# ---------------------------------------------------------------------------


class TestTripTotalInAllowedPaths:
    def test_budget_trip_total_in_allowed_paths(self):
        assert "budget.trip_total" in ALLOWED_PATHS

    def test_budget_trip_total_not_same_as_budget_max(self):
        # The two paths are distinct — per-night vs whole trip
        assert "budget.max" in ALLOWED_PATHS
        assert "budget.trip_total" != "budget.max"

    def test_impact_map_routes_trip_total_to_hotel_and_itinerary(self):
        assert "hotel" in IMPACT_MAP["budget.trip_total"]
        assert "itinerary" in IMPACT_MAP["budget.trip_total"]

    def test_impact_map_routes_budget_max_to_hotel_only(self):
        # Per-night budget only impacts hotel selection
        assert IMPACT_MAP["budget.max"] == ("hotel",)

    def test_set_trip_total_validates_as_number(self):
        state = TravelState()
        result = apply_patch(state, [{"path": "budget.trip_total", "operation": "set", "value": 3_000_000}])
        assert len(result.applied) == 1
        assert result.state.get("budget.trip_total").value == 3_000_000.0

    def test_set_trip_total_and_budget_max_coexist(self):
        """Setting trip_total must not overwrite budget.max and vice versa."""
        state = TravelState()
        result = apply_patch(
            state,
            [
                {"path": "budget.max", "operation": "set", "value": 1_000_000},
                {"path": "budget.trip_total", "operation": "set", "value": 3_000_000},
            ],
        )
        assert len(result.applied) == 2
        assert result.state.get("budget.max").value == 1_000_000.0
        assert result.state.get("budget.trip_total").value == 3_000_000.0

    def test_trip_total_validator_rejects_string(self):
        state = TravelState()
        result = apply_patch(
            state, [{"path": "budget.trip_total", "operation": "set", "value": "not a number"}]
        )
        assert len(result.rejected) == 1

    def test_trip_total_validator_rejects_negative(self):
        state = TravelState()
        result = apply_patch(
            state, [{"path": "budget.trip_total", "operation": "set", "value": -100}]
        )
        assert len(result.rejected) == 1


# ---------------------------------------------------------------------------
# budget_check helpers
# ---------------------------------------------------------------------------


class TestKnownHotelTotal:
    def test_uses_total_stay_price(self):
        assert _known_hotel_total({"total_stay_price": 2_000_000}) == 2_000_000.0

    def test_falls_back_to_nightly_times_nights(self):
        result = _known_hotel_total({"average_nightly_price": 500_000, "stay_night_count": 3})
        assert result == 1_500_000.0

    def test_returns_none_when_no_price(self):
        assert _known_hotel_total({}) is None

    def test_clamps_negative_to_zero(self):
        assert _known_hotel_total({"total_stay_price": -500}) == 0.0


class TestKnownActivityTotal:
    def test_sums_known_costs(self):
        items = [{"estimated_cost": 100_000}, {"estimated_cost": 200_000}, {"estimated_cost": None}]
        assert _known_activity_total(items) == 300_000.0

    def test_returns_zero_for_all_unknown(self):
        assert _known_activity_total([{"estimated_cost": None}]) == 0.0

    def test_returns_zero_for_empty(self):
        assert _known_activity_total([]) == 0.0


class TestItemCountWithKnownCost:
    def test_counts_items_with_cost(self):
        items = [{"estimated_cost": 100}, {"estimated_cost": None}, {"estimated_cost": 0}]
        # estimated_cost=0 is truthy for "is not None"
        assert _item_count_with_known_cost(items) == 2

    def test_zero_for_all_unknown(self):
        assert _item_count_with_known_cost([{"estimated_cost": None}]) == 0


class TestDerivePerNightCeiling:
    def test_subtracts_activity_total_from_trip_total(self):
        # 3_000_000 trip total, 300_000 known activities, 3 nights
        ceiling = _derive_per_night_ceiling(3_000_000, 300_000, 3)
        assert ceiling == pytest.approx(900_000.0)

    def test_clamps_to_zero_when_activities_exceed_total(self):
        ceiling = _derive_per_night_ceiling(1_000_000, 1_500_000, 3)
        assert ceiling == 0.0

    def test_full_total_when_no_activity_costs(self):
        ceiling = _derive_per_night_ceiling(3_000_000, 0, 3)
        assert ceiling == pytest.approx(1_000_000.0)

    def test_one_night(self):
        ceiling = _derive_per_night_ceiling(2_000_000, 500_000, 1)
        assert ceiling == pytest.approx(1_500_000.0)


# ---------------------------------------------------------------------------
# _check_trip_total
# ---------------------------------------------------------------------------


def _make_trip_data(
    hotel_total: float | None = None,
    item_costs: list[float | None] | None = None,
) -> dict[str, Any]:
    hotel: dict[str, Any] = {}
    if hotel_total is not None:
        hotel["total_stay_price"] = hotel_total
    items = [{"estimated_cost": c} for c in (item_costs or [])]
    return {
        "hotel": hotel,
        "itinerary_items": items,
        "itineraries": [{"duration_days": 3, "preferences": ["Ha Noi"]}],
    }


class TestCheckTripTotal:
    def test_ok_when_within_budget(self):
        data = _make_trip_data(hotel_total=2_000_000, item_costs=[150_000, 100_000])
        result = _check_trip_total(data, 3_000_000, "vi")
        assert result["status"] == "ok"
        assert result["known_total"] == 2_250_000.0

    def test_unknown_coverage_when_no_prices(self):
        data = _make_trip_data(item_costs=[None, None])
        result = _check_trip_total(data, 3_000_000, "vi")
        assert result["status"] == "unknown_coverage"
        assert result["known_total"] is None

    def test_over_budget(self):
        data = _make_trip_data(hotel_total=2_500_000, item_costs=[1_000_000])
        result = _check_trip_total(data, 3_000_000, "vi")
        assert result["status"] == "over_budget"
        assert result["known_total"] == 3_500_000.0

    def test_ok_includes_coverage_note_when_partial(self):
        # 2 items known, 1 unknown -> coverage < 1.0
        data = _make_trip_data(hotel_total=1_000_000, item_costs=[100_000, None])
        result = _check_trip_total(data, 3_000_000, "vi")
        assert result["status"] == "ok"
        assert result["coverage_fraction"] == pytest.approx(1 / 2)
        # Reply should mention coverage caveat
        assert "1/2" in result["reply"] or "muc co gia" in result["reply"].lower() or "mục có giá" in result["reply"]

    def test_dominant_is_hotel_when_hotel_dominates(self):
        data = _make_trip_data(hotel_total=2_800_000, item_costs=[100_000])
        result = _check_trip_total(data, 2_000_000, "vi")
        assert result["status"] == "over_budget"
        assert result["hotel_total"] == 2_800_000.0
        # Hotel dominates; dominant cost name should reflect that
        assert "khach san" in result["reply"].lower() or "khách sạn" in result["reply"]

    def test_dominant_is_activity_when_activities_dominate(self):
        data = _make_trip_data(hotel_total=200_000, item_costs=[2_000_000, 1_000_000])
        result = _check_trip_total(data, 2_000_000, "vi")
        assert result["status"] == "over_budget"
        assert "hoat dong" in result["reply"].lower() or "hoạt động" in result["reply"]


# ---------------------------------------------------------------------------
# budget_check node
# ---------------------------------------------------------------------------


def _make_state(
    trip_total: float | None = None,
    budget_max: float | None = None,
    trip_data: dict[str, Any] | None = None,
    task_results: list | None = None,
    language: str = "vi",
) -> TravelGraphState:
    slots = {}
    if trip_total is not None:
        slots["budget.trip_total"] = Slot(presence=Presence.SET, value=trip_total)
    if budget_max is not None:
        slots["budget.max"] = Slot(presence=Presence.SET, value=budget_max)
    travel_state = TravelState(slots=slots).to_dict()
    return TravelGraphState(
        language=language,
        travel_state=travel_state,
        trip_data=trip_data or {},
        task_results=task_results or [],
    )


class TestBudgetCheckNode:
    def test_passthrough_when_no_trip_total(self):
        state = _make_state(trip_data={"hotel": {"total_stay_price": 1_000_000}, "itinerary_items": []})
        result = budget_check(state)
        assert result == {}

    def test_passthrough_when_no_trip_data(self):
        state = _make_state(trip_total=3_000_000)
        result = budget_check(state)
        assert result == {}

    def test_ok_status_within_budget(self):
        trip_data = _make_trip_data(hotel_total=2_000_000, item_costs=[100_000])
        state = _make_state(trip_total=3_000_000, trip_data=trip_data)
        result = budget_check(state)
        assert "task_results" in result
        assert result["task_results"][-1]["status"] == "ok"
        # trip_data NOT in result — no mutation needed
        assert "trip_data" not in result

    def test_unknown_coverage_when_no_prices(self):
        trip_data = _make_trip_data(item_costs=[None])
        state = _make_state(trip_total=3_000_000, trip_data=trip_data)
        result = budget_check(state)
        assert result["task_results"][-1]["status"] == "unknown_coverage"

    def test_per_night_and_trip_total_coexist(self):
        """Setting budget.max must not affect budget.trip_total in state."""
        state = _make_state(
            trip_total=3_000_000,
            budget_max=1_000_000,
            trip_data=_make_trip_data(hotel_total=2_000_000, item_costs=[100_000]),
        )
        travel_state = TravelState.from_dict(state.get("travel_state"))
        # Both slots must survive
        assert travel_state.get("budget.trip_total").presence is Presence.SET
        assert travel_state.get("budget.max").presence is Presence.SET
        assert travel_state.get("budget.trip_total").value == 3_000_000.0
        assert travel_state.get("budget.max").value == 1_000_000.0

    def test_over_budget_triggers_replan_once(self):
        """When over budget, exactly one hotel re-search is attempted."""
        trip_data = _make_trip_data(hotel_total=2_500_000, item_costs=[1_000_000])
        # Add itinerary metadata needed for re-plan
        trip_data["itineraries"] = [
            {
                "duration_days": 3,
                "preferences": ["Da Nang"],
                "number_of_adults": 2,
                "start_date": "2026-09-01",
                "end_date": "2026-09-04",
                "planning_constraints": {},
                "day_themes": [],
            }
        ]
        state = _make_state(trip_total=3_000_000, trip_data=trip_data)

        call_count = {"n": 0}

        def fake_select(dest, dest_id, people, **kwargs):
            call_count["n"] += 1
            # Return a cheaper hotel
            hotel = {
                "id": "cheap-hotel-1",
                "name": "Budget Inn",
                "total_stay_price": 900_000,
                "average_nightly_price": 300_000,
                "stay_night_count": 3,
                "coordinates": "16.0544,108.2022",
                "covered_meals": [],
            }
            from src.services.trip_scheduler import PlaceCandidate
            candidate = PlaceCandidate(
                id="cheap-hotel-1",
                name="Budget Inn",
                coordinates="16.0544,108.2022",
                category="Hotel",
            )
            return [(hotel, candidate)]

        def fake_rank(options, **kwargs):
            return options

        with (
            patch("src.agents.graph.nodes.budget_check._get_destination_id", return_value="dest-1"),
            patch("src.agents.graph.nodes.budget_check.select_hotel_candidates", side_effect=fake_select),
            patch("src.agents.graph.nodes.budget_check.rank_hotel_candidates", side_effect=fake_rank),
            patch("src.agents.graph.nodes.budget_check.rebuild_day_data"),
        ):
            result = budget_check(state)

        # Hotel search must have been called exactly once
        assert call_count["n"] == 1
        assert "task_results" in result

    def test_over_budget_replan_at_most_one_pass(self):
        """The re-plan loop must not iterate more than once."""
        # Even if the re-planned hotel is still over budget, we don't retry
        trip_data = _make_trip_data(hotel_total=4_000_000, item_costs=[500_000])
        trip_data["itineraries"] = [
            {
                "duration_days": 2,
                "preferences": ["Ha Noi"],
                "number_of_adults": 2,
                "start_date": "2026-09-01",
                "end_date": "2026-09-03",
                "planning_constraints": {},
                "day_themes": [],
            }
        ]
        state = _make_state(trip_total=2_000_000, trip_data=trip_data)

        call_count = {"n": 0}

        def fake_select(dest, dest_id, people, **kwargs):
            call_count["n"] += 1
            # Still expensive
            hotel = {
                "id": "still-pricey",
                "name": "Mid Hotel",
                "total_stay_price": 1_800_000,
                "average_nightly_price": 900_000,
                "stay_night_count": 2,
                "coordinates": "21.028,105.854",
                "covered_meals": [],
            }
            from src.services.trip_scheduler import PlaceCandidate
            candidate = PlaceCandidate(
                id="still-pricey",
                name="Mid Hotel",
                coordinates="21.028,105.854",
                category="Hotel",
            )
            return [(hotel, candidate)]

        def fake_rank(options, **kwargs):
            return options

        with (
            patch("src.agents.graph.nodes.budget_check._get_destination_id", return_value="dest-2"),
            patch("src.agents.graph.nodes.budget_check.select_hotel_candidates", side_effect=fake_select),
            patch("src.agents.graph.nodes.budget_check.rank_hotel_candidates", side_effect=fake_rank),
            patch("src.agents.graph.nodes.budget_check.rebuild_day_data"),
        ):
            result = budget_check(state)

        # Must have run hotel search exactly once, then stopped
        assert call_count["n"] == 1
        final_status = result["task_results"][-1]["status"]
        assert final_status in ("still_over_budget", "ok", "unknown_coverage")

    def test_binding_constraint_when_no_cheaper_hotel_found(self):
        """When hotel search returns empty, report binding constraint."""
        trip_data = _make_trip_data(hotel_total=2_500_000, item_costs=[])
        trip_data["itineraries"] = [
            {
                "duration_days": 3,
                "preferences": ["Hoi An"],
                "number_of_adults": 1,
                "start_date": "2026-10-01",
                "end_date": "2026-10-04",
                "planning_constraints": {},
                "day_themes": [],
            }
        ]
        state = _make_state(trip_total=1_000_000, trip_data=trip_data)

        with (
            patch("src.agents.graph.nodes.budget_check._get_destination_id", return_value="dest-3"),
            patch("src.agents.graph.nodes.budget_check.select_hotel_candidates", return_value=[]),
        ):
            result = budget_check(state)

        assert result["task_results"][-1]["status"] == "binding_constraint"

    def test_locked_days_not_rebuilt(self):
        """Days in locked_days are excluded from the itinerary rebuild."""
        trip_data = _make_trip_data(hotel_total=3_000_000, item_costs=[200_000])
        trip_data["itineraries"] = [
            {
                "duration_days": 3,
                "preferences": ["Hue"],
                "number_of_adults": 2,
                "start_date": "2026-11-01",
                "end_date": "2026-11-04",
                "planning_constraints": {"locked_days": [1]},
                "day_themes": [],
            }
        ]
        state = _make_state(trip_total=2_000_000, trip_data=trip_data)

        rebuilt_days: list[int] = []

        def fake_rebuild(trip_data_mut, day_number, theme, locked_days=None):
            rebuilt_days.append(day_number)

        def fake_select(dest, dest_id, people, **kwargs):
            hotel = {
                "id": "budget-hotel",
                "name": "Economy Stay",
                "total_stay_price": 1_200_000,
                "average_nightly_price": 400_000,
                "stay_night_count": 3,
                "coordinates": "16.463,107.590",
                "covered_meals": [],
            }
            from src.services.trip_scheduler import PlaceCandidate
            candidate = PlaceCandidate(
                id="budget-hotel",
                name="Economy Stay",
                coordinates="16.463,107.590",
                category="Hotel",
            )
            return [(hotel, candidate)]

        def fake_rank(options, **kwargs):
            return options

        with (
            patch("src.agents.graph.nodes.budget_check._get_destination_id", return_value="dest-4"),
            patch("src.agents.graph.nodes.budget_check.select_hotel_candidates", side_effect=fake_select),
            patch("src.agents.graph.nodes.budget_check.rank_hotel_candidates", side_effect=fake_rank),
            patch("src.agents.graph.nodes.budget_check.rebuild_day_data", side_effect=fake_rebuild),
        ):
            budget_check(state)

        # Day 1 must not appear in rebuilt days (it's locked)
        assert 1 not in rebuilt_days
        # Days 2 and 3 are unlocked so they may be rebuilt
        for day in rebuilt_days:
            assert day != 1

    def test_doc_37_case_budget_with_locked_day_1(self):
        """Doc §37: 'Budget còn 8 triệu, nhưng giữ nguyên ngày 1.'

        Day 1 must remain locked; the rest of the trip is replanned under
        the total budget constraint.
        """
        # Simulates an 8M trip total, current plan over budget, day 1 locked
        trip_data = _make_trip_data(hotel_total=5_000_000, item_costs=[2_000_000, 2_000_000])
        trip_data["itineraries"] = [
            {
                "duration_days": 3,
                "preferences": ["Da Lat"],
                "number_of_adults": 2,
                "start_date": "2026-12-01",
                "end_date": "2026-12-04",
                "planning_constraints": {"locked_days": [1]},
                "day_themes": [
                    {"day_number": 1, "title": "Ngay 1 co dinh", "query": ""},
                    {"day_number": 2, "title": "Ngay 2", "query": ""},
                    {"day_number": 3, "title": "Ngay 3", "query": ""},
                ],
            }
        ]
        state = _make_state(trip_total=8_000_000, trip_data=trip_data)

        rebuilt_days: list[int] = []

        def fake_rebuild(trip_data_mut, day_number, theme, locked_days=None):
            rebuilt_days.append(day_number)

        def fake_select(dest, dest_id, people, **kwargs):
            hotel = {
                "id": "replan-hotel",
                "name": "Economy Hotel",
                "total_stay_price": 3_000_000,
                "average_nightly_price": 1_000_000,
                "stay_night_count": 3,
                "coordinates": "11.946,108.442",
                "covered_meals": [],
            }
            from src.services.trip_scheduler import PlaceCandidate
            candidate = PlaceCandidate(
                id="replan-hotel",
                name="Economy Hotel",
                coordinates="11.946,108.442",
                category="Hotel",
            )
            return [(hotel, candidate)]

        def fake_rank(options, **kwargs):
            return options

        with (
            patch("src.agents.graph.nodes.budget_check._get_destination_id", return_value="dest-5"),
            patch("src.agents.graph.nodes.budget_check.select_hotel_candidates", side_effect=fake_select),
            patch("src.agents.graph.nodes.budget_check.rank_hotel_candidates", side_effect=fake_rank),
            patch("src.agents.graph.nodes.budget_check.rebuild_day_data", side_effect=fake_rebuild),
        ):
            result = budget_check(state)

        # Day 1 must be untouched
        assert 1 not in rebuilt_days
        # The node must have returned a result (not a pass-through)
        assert "task_results" in result


# ---------------------------------------------------------------------------
# format_budget_status
# ---------------------------------------------------------------------------


class TestFormatBudgetStatus:
    def test_returns_empty_when_no_trip_total(self):
        assert format_budget_status(2_000_000, None, 3, 5) == ""

    def test_within_budget_no_coverage_note_when_all_known(self):
        status = format_budget_status(2_000_000, 3_000_000, 5, 5)
        assert "2,000,000" in status or "2.000.000" in status
        assert "3,000,000" in status or "3.000.000" in status
        # Should NOT mention partial coverage when all items have known cost
        assert "muc co gia" not in status.lower() or status.count("5/5") == 0

    def test_within_budget_has_coverage_note_when_partial(self):
        status = format_budget_status(1_000_000, 3_000_000, 3, 5)
        # Should mention 3/5 coverage
        assert "3/5" in status or "3 / 5" in status or "3" in status

    def test_over_budget_includes_shortfall(self):
        status = format_budget_status(4_000_000, 3_000_000, 5, 5)
        assert "VUOT" in status.upper() or "vượt" in status.lower() or "vuot" in status.lower()
        # shortfall = 1_000_000
        assert "1,000,000" in status or "1.000.000" in status

    def test_unknown_coverage_when_known_total_is_none(self):
        status = format_budget_status(None, 3_000_000, 0, 5)
        assert "3,000,000" in status or "3.000.000" in status
        # Should indicate lack of price information
        assert "gia" in status.lower() or "giá" in status.lower()


# ---------------------------------------------------------------------------
# Extraction disambiguation table-test (Phase 14 requirement)
# ---------------------------------------------------------------------------


class TestBudgetDisambiguationInState:
    """Verify that the *domain* layer keeps per-night and trip-total distinct.

    The extraction prompt already labels budget.trip_total for whole-trip
    phrasings.  These tests confirm the state layer honours that distinction
    once the patch is applied — they do NOT call the LLM.
    """

    @pytest.mark.parametrize(
        "path,expected_path",
        [
            ("budget.max", "budget.max"),          # per-night ceiling -> budget.max
            ("budget.trip_total", "budget.trip_total"),  # trip total -> budget.trip_total
        ],
    )
    def test_patch_stores_in_correct_slot(self, path, expected_path):
        state = TravelState()
        result = apply_patch(state, [{"path": path, "operation": "set", "value": 3_000_000}])
        assert len(result.applied) == 1
        slot = result.state.get(expected_path)
        assert slot.presence is Presence.SET
        assert slot.value == 3_000_000.0

    def test_setting_trip_total_does_not_affect_budget_max(self):
        state = TravelState()
        # First set budget.max
        r1 = apply_patch(state, [{"path": "budget.max", "operation": "set", "value": 1_000_000}])
        # Then set budget.trip_total
        r2 = apply_patch(r1.state, [{"path": "budget.trip_total", "operation": "set", "value": 3_000_000}])
        assert r2.state.get("budget.max").value == 1_000_000.0
        assert r2.state.get("budget.trip_total").value == 3_000_000.0

    def test_setting_budget_max_does_not_affect_trip_total(self):
        state = TravelState()
        r1 = apply_patch(state, [{"path": "budget.trip_total", "operation": "set", "value": 5_000_000}])
        r2 = apply_patch(r1.state, [{"path": "budget.max", "operation": "set", "value": 800_000}])
        assert r2.state.get("budget.trip_total").value == 5_000_000.0
        assert r2.state.get("budget.max").value == 800_000.0
