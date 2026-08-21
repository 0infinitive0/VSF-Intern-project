"""Phase 3 read-through conversions: `TripIntakeState`/`HotelPreferenceState`
<-> `TravelState`. These are additive methods — the existing `with_message`/
`next_question`/etc. behavior is untouched and covered by
`test_trip_intake.py`/`test_hotel_selection.py`, which this file deliberately
does not modify."""

from __future__ import annotations

from datetime import date, timedelta

from src.domain.travel_state import Presence, Slot, TravelState
from src.services.hotel_selection import HotelPreferenceState
from src.services.trip_intake import TripIntakeState

# Anchored to the run date, not a literal frozen at authoring time, so these
# keep standing in for a realistic upcoming trip. Not a validator
# requirement: the `dates.start`/`dates.end` validators `to_travel_state()`
# routes through do NOT reject a past date today.
_TRIP_START = (date.today() + timedelta(days=30)).isoformat()
_TRIP_END = (date.today() + timedelta(days=35)).isoformat()


def test_trip_intake_state_to_travel_state_maps_set_facts() -> None:
    intake = TripIntakeState(
        destination="Đà Nẵng",
        duration="5 ngày",
        start_date=_TRIP_START,
        stay_end_date=_TRIP_END,
        people="2 người",
        preferences=("biển", "ẩm thực"),
        companions="đi cùng người yêu hoặc vợ chồng",
        pace="thư thái",
        day_rhythm=("bắt đầu sớm",),
        notes="thích yên tĩnh",
    )

    travel_state = intake.to_travel_state()

    assert travel_state.get("destination") == Slot(Presence.SET, "Đà Nẵng")
    assert travel_state.get("dates.start") == Slot(Presence.SET, _TRIP_START)
    assert travel_state.get("dates.end") == Slot(Presence.SET, _TRIP_END)
    assert travel_state.get("people") == Slot(Presence.SET, 2)
    assert travel_state.get("preferences.themes") == Slot(Presence.SET, ["biển", "ẩm thực"])
    assert travel_state.get("preferences.companions") == Slot(Presence.SET, "đi cùng người yêu hoặc vợ chồng")
    assert travel_state.get("preferences.pace") == Slot(Presence.SET, "thư thái")
    assert travel_state.get("preferences.day_rhythm") == Slot(Presence.SET, ["bắt đầu sớm"])
    assert travel_state.get("preferences.notes") == Slot(Presence.SET, "thích yên tĩnh")


def test_trip_intake_state_to_travel_state_leaves_unanswered_facts_unknown() -> None:
    travel_state = TripIntakeState().to_travel_state()

    assert travel_state.get("destination").presence is Presence.UNKNOWN
    assert travel_state.get("people").presence is Presence.UNKNOWN
    assert travel_state.to_dict() == {}


def test_trip_intake_state_from_travel_state_round_trips() -> None:
    original = TripIntakeState(
        destination="Huế",
        start_date="2026-09-01",
        stay_end_date="2026-09-04",
        people="3 người",
        preferences=("văn hóa",),
        companions="đi cùng gia đình",
        pace="vừa phải",
        day_rhythm=("về khuya",),
        notes="cần phòng gia đình",
    )

    restored = TripIntakeState.from_travel_state(original.to_travel_state())

    assert restored.destination == original.destination
    assert restored.start_date == original.start_date
    assert restored.stay_end_date == original.stay_end_date
    assert restored.people == original.people
    assert restored.duration == "3 ngày"  # derived from the 3-night date span
    assert restored.preferences == original.preferences
    assert restored.companions == original.companions
    assert restored.pace == original.pace
    assert restored.day_rhythm == original.day_rhythm
    assert restored.notes == original.notes


def test_hotel_preference_state_pending_budget_maps_to_unknown() -> None:
    travel_state = HotelPreferenceState().to_travel_state()

    assert travel_state.get("budget.max").presence is Presence.UNKNOWN
    assert travel_state.to_dict() == {}


def test_hotel_preference_state_no_preference_maps_to_not_applicable_not_set() -> None:
    """`with_message`'s "bao nhiêu cũng được" branch: stage done, all three
    prices None. This must stay distinguishable from never having asked —
    the entire point of the tri-state model."""
    state = HotelPreferenceState(stage="done", target_price=None, min_price=None, max_price=None)

    travel_state = state.to_travel_state()

    assert travel_state.get("budget.max") == Slot(Presence.NOT_APPLICABLE, None)
    assert travel_state.get("budget.min") == Slot(Presence.NOT_APPLICABLE, None)
    assert travel_state.get("budget.target") == Slot(Presence.NOT_APPLICABLE, None)


def test_hotel_preference_state_resolved_budget_round_trips() -> None:
    original = HotelPreferenceState(stage="done", target_price=2_000_000.0, min_price=1_000_000.0, max_price=3_000_000.0)

    restored = HotelPreferenceState.from_travel_state(original.to_travel_state())

    assert restored == original


def test_hotel_preference_state_from_travel_state_treats_not_applicable_as_no_preference() -> None:
    travel_state = TravelState(
        slots={
            "budget.max": Slot(Presence.NOT_APPLICABLE, None),
            "budget.min": Slot(Presence.NOT_APPLICABLE, None),
            "budget.target": Slot(Presence.NOT_APPLICABLE, None),
        }
    )

    restored = HotelPreferenceState.from_travel_state(travel_state)

    assert restored == HotelPreferenceState(stage="done", target_price=None, min_price=None, max_price=None)


def test_hotel_preference_state_from_travel_state_unknown_stays_pending() -> None:
    restored = HotelPreferenceState.from_travel_state(TravelState())

    assert restored == HotelPreferenceState()


def test_trip_intake_state_to_travel_state_never_fabricates_an_end_date_from_duration() -> None:
    """A state with only `duration` + `start_date` (no explicit `stay_end_date`)
    has NOT confirmed a real checkout date — `has_explicit_stay_dates` is
    False. The canonical view must not promote the derived `end_date` to a
    confirmed `dates.end` SET, or a round trip would silently skip the
    end-date question `next_question` still needs to ask."""
    intake = TripIntakeState(destination="Huế", duration="3 ngày", start_date="2026-09-01", people="2 người")
    assert intake.has_explicit_stay_dates is False
    assert intake.next_question() == "Bạn dự định kết thúc chuyến đi vào ngày nào?"

    travel_state = intake.to_travel_state()
    assert travel_state.get("dates.end").presence is Presence.UNKNOWN

    restored = TripIntakeState.from_travel_state(travel_state)
    assert restored.has_explicit_stay_dates is False
    assert restored.next_question() == "Bạn dự định kết thúc chuyến đi vào ngày nào?"


def test_hotel_preference_state_mixed_set_and_not_applicable_keeps_the_set_value() -> None:
    """Per-slot precedence: a NOT_APPLICABLE `budget.max` ("no upper limit")
    must not blank out a SET `budget.min` ("at least 1tr/night") — the two
    answer different questions and can coexist."""
    travel_state = TravelState(
        slots={
            "budget.min": Slot(Presence.SET, 1_000_000.0),
            "budget.max": Slot(Presence.NOT_APPLICABLE, None),
        }
    )

    restored = HotelPreferenceState.from_travel_state(travel_state)

    assert restored == HotelPreferenceState(stage="done", target_price=None, min_price=1_000_000.0, max_price=None)


def test_trip_intake_state_to_travel_state_drops_out_of_range_people_instead_of_storing_it() -> None:
    """Routed through `apply_patch`: a value this dataclass could hold but no
    real patch could ever produce (`people` outside 1-50) must not surface as
    a canonical SET slot no patch actually validated."""
    intake = TripIntakeState(people="0 người")

    travel_state = intake.to_travel_state()

    assert travel_state.get("people").presence is Presence.UNKNOWN


def test_live_session_amenity_strings_upgrade_to_bound_record_shape_on_read() -> None:
    restored = TravelState.from_dict({
        "hotel_preferences.amenities": {
            "presence": "set",
            "value": ["swimming_pool"],
        }
    })

    assert restored.get("hotel_preferences.amenities").value == [{
        "id": "swimming_pool",
        "label": "swimming_pool",
        "polarity": "require",
        "source_phrase": "swimming_pool",
        "confidence": 0.0,
    }]
