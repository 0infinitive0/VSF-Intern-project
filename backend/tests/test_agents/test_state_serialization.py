"""Phase 3 serialization guarantees for TripState
(260802-1437-langgraph-full-orchestration-and-durable-state).

TripState is the schema a checkpointer will eventually own (Phase 7). These
tests pin the two non-functional requirements that make that possible:
round-trips through json.dumps/json.loads with no custom encoder, and no
field type that could ever hold a Callable, BaseTool, compiled graph, or
threading.Lock.
"""

from __future__ import annotations

import json
from typing import get_type_hints

from src.agents.state import TripState, initial_state
from src.services.hotel_selection import HotelPreferenceState
from src.services.trip_intake import TripIntakeState


def test_trip_state_round_trips_through_json_with_no_custom_encoder():
    """A fully populated, FINALIZED trip_data — not an empty one. The plan's
    risk is that a partially-populated state hides a non-JSON value
    (datetime, Decimal) that only shows up once real data flows through, so
    this uses a shape close to what select_hotel/finalize actually produce."""
    state = initial_state("json-roundtrip-session")
    state["intake"] = TripIntakeState(
        destination="Đà Nẵng", duration="3 ngày", people="2 người", preferences=("biển", "ẩm thực")
    ).to_dict()
    state["hotel_prefs"] = HotelPreferenceState(
        stage="done", target_price=4_000_000.0, min_price=800_000.0, max_price=2_500_000.0
    ).to_dict()
    state["trip_data"] = {
        "hotel": {"id": "hotel-1", "name": "Muong Thanh Grand", "star_rating": 4},
        "itineraries": [
            {
                "id": "itinerary-1",
                "destination_id": "dest-1",
                "duration_days": 3,
                "number_of_adults": 2,
                "preferences": ["Đà Nẵng"],
                "status": "Finalized",
                "day_themes": [{"day_number": 1, "title": "Beach day", "query": "beach"}],
            }
        ],
        "itinerary_items": [
            {
                "id": "item-1",
                "day_number": 1,
                "order_index": 1,
                "start_time": "08:00:00",
                "end_time": "09:00:00",
                "activity": "Ăn sáng",
                "kind": "breakfast",
                "reference_type": "Attraction",
                "reference_id": "attr-1",
            }
        ],
        "adjustments": [],
    }
    state["pending_hotel_selection"] = None
    state["initial_plan_complete"] = True
    state["planning_new_trip"] = False
    state["pending_trip_edit_request"] = None
    state["route"] = "finalize"
    state["reroute_count"] = 1
    state["reply"] = "Đã chốt lịch trình."
    state["tool_ran"] = "finalize_trip_plan"

    round_tripped = json.loads(json.dumps(state))

    assert round_tripped == state


def test_trip_state_intake_and_hotel_prefs_reconstruct_after_json_round_trip():
    """The dataclasses embedded in TripState must also survive the trip through
    JSON, not just the raw dict — pins that `from_dict` handles what
    `json.loads` actually hands back (list, not tuple)."""
    state = initial_state("json-roundtrip-session-2")
    state["intake"] = TripIntakeState(
        destination="Huế", duration="4 ngày", people="3 người", preferences=("văn hóa",)
    ).to_dict()
    state["hotel_prefs"] = HotelPreferenceState(stage="done", target_price=2_000_000.0).to_dict()

    round_tripped = json.loads(json.dumps(state))

    intake = TripIntakeState.from_dict(round_tripped["intake"])
    hotel_prefs = HotelPreferenceState.from_dict(round_tripped["hotel_prefs"])

    assert intake == TripIntakeState(
        destination="Huế", duration="4 ngày", people="3 người", preferences=("văn hóa",)
    )
    assert hotel_prefs == HotelPreferenceState(stage="done", target_price=2_000_000.0)


def test_trip_state_schema_has_no_non_serializable_field_types():
    """Static schema check: no annotated field type in TripState references a
    Callable, BaseTool, compiled graph, or threading.Lock — those stay on the
    runtime TripSession wrapper, never in the checkpointable state. Guards
    Phases 4-5 from accidentally widening TripState to hold one."""
    hints = get_type_hints(TripState)
    forbidden_names = {"Callable", "BaseTool", "Lock", "StateGraph", "CompiledGraph"}
    for field_name, hint in hints.items():
        hint_str = str(hint)
        assert not any(name in hint_str for name in forbidden_names), (
            f"TripState.{field_name} annotation {hint_str!r} references a non-serializable type"
        )
