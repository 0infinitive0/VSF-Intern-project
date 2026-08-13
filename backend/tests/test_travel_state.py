from __future__ import annotations

import json
from datetime import date, timedelta

from src.domain.travel_state import (
    _VALIDATORS,  # noqa: PLC2701 — parity check, same module
    ALLOWED_PATHS,
    IMPACT_MAP,
    PatchChange,
    Presence,
    Slot,
    TravelState,
    apply_patch,
    detect_impact,
)

# Phase 7 added a past-date rejection to dates.start/dates.end — these must
# stay in the future relative to whenever the suite actually runs.
_TRIP_START = (date.today() + timedelta(days=30)).isoformat()
_TRIP_END = (date.today() + timedelta(days=35)).isoformat()  # 5-day trip


def test_apply_patch_rejects_a_path_outside_allowed_paths() -> None:
    result = apply_patch(TravelState(), [{"path": "not.a.real.path", "operation": "set", "value": "x"}])

    assert result.applied == ()
    assert len(result.rejected) == 1
    assert result.rejected[0].path == "not.a.real.path"
    assert "ALLOWED_PATHS" in result.rejected[0].reason
    assert result.state.get("not.a.real.path").presence is Presence.UNKNOWN


def test_a_rejected_change_does_not_discard_valid_changes_in_the_same_patch() -> None:
    result = apply_patch(
        TravelState(),
        [
            {"path": "destination", "operation": "set", "value": "Đà Nẵng"},
            {"path": "not.allowed", "operation": "set", "value": "x"},
            {"path": "people", "operation": "set", "value": 2},
        ],
    )

    assert len(result.applied) == 2
    assert len(result.rejected) == 1
    assert result.state.get("destination") == Slot(Presence.SET, "Đà Nẵng")
    assert result.state.get("people") == Slot(Presence.SET, 2)
    assert result.state.get("not.allowed").presence is Presence.UNKNOWN


def test_malformed_change_is_rejected_without_raising() -> None:
    result = apply_patch(
        TravelState(),
        [
            {"path": "destination"},  # missing operation
            {"operation": "set", "value": "x"},  # missing path
            "not-a-dict",  # not even a mapping
        ],
    )

    assert result.applied == ()
    assert len(result.rejected) == 3


def test_budget_unknown_vs_not_applicable_are_distinguishable() -> None:
    never_asked = TravelState()
    assert never_asked.get("budget.max").presence is Presence.UNKNOWN

    opted_out = apply_patch(never_asked, [{"path": "budget.max", "operation": "set", "value": None}]).state
    assert opted_out.get("budget.max").presence is Presence.NOT_APPLICABLE
    assert opted_out.get("budget.max").value is None

    assert opted_out.get("budget.max") != never_asked.get("budget.max")


def test_a_set_slot_can_be_overwritten_by_a_later_patch() -> None:
    first = apply_patch(TravelState(), [{"path": "budget.max", "operation": "set", "value": 500000}]).state
    assert first.get("budget.max").value == 500000

    second = apply_patch(first, [{"path": "budget.max", "operation": "set", "value": 800000}]).state
    assert second.get("budget.max").value == 800000
    assert second.get("budget.max").presence is Presence.SET


def test_unset_resets_a_slot_to_unknown() -> None:
    state = apply_patch(TravelState(), [{"path": "destination", "operation": "set", "value": "Huế"}]).state
    reset = apply_patch(state, [{"path": "destination", "operation": "unset"}]).state

    assert reset.get("destination").presence is Presence.UNKNOWN
    assert reset.get("destination").value is None
    # UNKNOWN is stored as absence, not an explicit entry
    assert "destination" not in reset.to_dict()


def test_daily_preferences_wildcard_day_within_trip_length_validates() -> None:
    state = apply_patch(
        TravelState(),
        [
            {"path": "dates.start", "operation": "set", "value": _TRIP_START},
            {"path": "dates.end", "operation": "set", "value": _TRIP_END},
        ],
    ).state

    result = apply_patch(state, [{"path": "daily_preferences.3.theme", "operation": "set", "value": "biển"}])

    assert len(result.applied) == 1
    assert result.state.get("daily_preferences.3.theme").value == "biển"


def test_daily_preferences_wildcard_day_beyond_trip_length_rejects() -> None:
    state = apply_patch(
        TravelState(),
        [
            {"path": "dates.start", "operation": "set", "value": _TRIP_START},
            {"path": "dates.end", "operation": "set", "value": _TRIP_END},
        ],
    ).state

    result = apply_patch(state, [{"path": "daily_preferences.99.theme", "operation": "set", "value": "biển"}])

    assert result.applied == ()
    assert len(result.rejected) == 1
    assert "exceeds trip length" in result.rejected[0].reason


def test_daily_preferences_wildcard_matches_the_allow_list_pattern() -> None:
    result = apply_patch(TravelState(), [{"path": "daily_preferences.2.theme", "operation": "set", "value": "ẩm thực"}])

    assert len(result.applied) == 1
    result_other_leaf = apply_patch(
        TravelState(), [{"path": "daily_preferences.2.color", "operation": "set", "value": "blue"}]
    )
    assert result_other_leaf.applied == ()
    assert "ALLOWED_PATHS" in result_other_leaf.rejected[0].reason


def test_list_path_append_and_remove() -> None:
    added = apply_patch(
        TravelState(),
        [
            {"path": "hotel_preferences.amenities", "operation": "append", "value": "pool"},
            {"path": "hotel_preferences.amenities", "operation": "append", "value": "wifi"},
        ],
    ).state
    assert added.get("hotel_preferences.amenities").value == ["pool", "wifi"]

    removed = apply_patch(added, [{"path": "hotel_preferences.amenities", "operation": "remove", "value": "pool"}]).state
    assert removed.get("hotel_preferences.amenities").value == ["wifi"]


def test_append_is_idempotent_for_a_duplicate_item() -> None:
    state = apply_patch(TravelState(), [{"path": "locked_days", "operation": "append", "value": 1}]).state
    state = apply_patch(state, [{"path": "locked_days", "operation": "append", "value": 1}]).state

    assert state.get("locked_days").value == [1]


def test_append_remove_rejected_on_a_scalar_path() -> None:
    result = apply_patch(TravelState(), [{"path": "destination", "operation": "append", "value": "Huế"}])

    assert result.applied == ()
    assert "list path" in result.rejected[0].reason


def test_set_on_a_list_path_requires_a_list_value() -> None:
    result = apply_patch(TravelState(), [{"path": "preferences.themes", "operation": "set", "value": "biển"}])

    assert result.applied == ()
    assert "list value" in result.rejected[0].reason


def test_every_allowed_path_has_an_impact_map_entry() -> None:
    assert set(IMPACT_MAP.keys()) == ALLOWED_PATHS


def test_every_allowed_path_has_a_validator() -> None:
    assert set(_VALIDATORS.keys()) == ALLOWED_PATHS


def test_detect_impact_returns_itinerary_day_not_itinerary_for_daily_theme_change() -> None:
    applied = (PatchChange(path="daily_preferences.1.theme", operation="set", value="biển"),)

    impacted = detect_impact(applied)

    assert impacted == {"itinerary_day"}
    assert "itinerary" not in impacted


def test_detect_impact_unions_workflows_across_changes() -> None:
    applied = (
        PatchChange(path="hotel_preferences.amenities", operation="append", value="pool"),
        PatchChange(path="preferences.themes", operation="append", value="biển"),
    )

    assert detect_impact(applied) == {"hotel", "itinerary"}


def test_travel_state_round_trips_through_to_dict_and_from_dict() -> None:
    state = apply_patch(
        TravelState(),
        [
            {"path": "destination", "operation": "set", "value": "Đà Nẵng"},
            {"path": "budget.max", "operation": "set", "value": None},  # NOT_APPLICABLE
            {"path": "hotel_preferences.amenities", "operation": "append", "value": "pool"},
        ],
    ).state

    restored = TravelState.from_dict(state.to_dict())

    assert restored == state


def test_to_dict_is_plain_json_serializable_without_a_custom_encoder() -> None:
    state = apply_patch(
        TravelState(),
        [
            {"path": "destination", "operation": "set", "value": "Đà Nẵng"},
            {"path": "people", "operation": "set", "value": 4},
        ],
    ).state

    encoded = json.dumps(state.to_dict())
    restored = TravelState.from_dict(json.loads(encoded))

    assert restored == state


def test_to_dict_omits_unknown_slots() -> None:
    state = apply_patch(TravelState(), [{"path": "destination", "operation": "set", "value": "Huế"}]).state

    as_dict = state.to_dict()

    assert set(as_dict.keys()) == {"destination"}


def test_set_missing_value_key_is_rejected_not_not_applicable() -> None:
    """A patch item that omits `"value"` entirely (a malformed LLM emission)
    must not be read as the user's deliberate opt-out signal."""
    result = apply_patch(TravelState(), [{"path": "destination", "operation": "set"}])

    assert result.applied == ()
    assert len(result.rejected) == 1
    assert result.state.get("destination").presence is Presence.UNKNOWN


def test_set_explicit_null_value_is_still_not_applicable() -> None:
    result = apply_patch(TravelState(), [{"path": "budget.max", "operation": "set", "value": None}])

    assert len(result.applied) == 1
    assert result.state.get("budget.max").presence is Presence.NOT_APPLICABLE


def test_string_path_rejects_a_non_string_value() -> None:
    result = apply_patch(TravelState(), [{"path": "destination", "operation": "set", "value": ["Đà Nẵng"]}])

    assert result.applied == ()
    assert "string" in result.rejected[0].reason


def test_remove_against_a_never_set_slot_is_rejected_not_fabricated_empty() -> None:
    result = apply_patch(
        TravelState(), [{"path": "preferences.themes", "operation": "remove", "value": "biển"}]
    )

    assert result.applied == ()
    assert result.state.get("preferences.themes").presence is Presence.UNKNOWN


def test_inverted_date_range_in_the_same_patch_is_rejected() -> None:
    result = apply_patch(
        TravelState(),
        [
            {"path": "dates.start", "operation": "set", "value": _TRIP_END},
            {"path": "dates.end", "operation": "set", "value": _TRIP_START},
        ],
    )

    assert len(result.applied) == 1
    assert len(result.rejected) == 1
    assert "end date" in result.rejected[0].reason


# --- Phase 7: date validators — past-date rejection + ambiguity -----------


def test_past_start_date_is_rejected_with_a_date_specific_message() -> None:
    past = (date.today() - timedelta(days=1)).isoformat()

    result = apply_patch(TravelState(), [{"path": "dates.start", "operation": "set", "value": past}])

    assert result.applied == ()
    assert len(result.rejected) == 1
    assert "past" in result.rejected[0].reason


def test_past_end_date_is_rejected_with_a_date_specific_message() -> None:
    past = (date.today() - timedelta(days=1)).isoformat()

    result = apply_patch(TravelState(), [{"path": "dates.end", "operation": "set", "value": past}])

    assert result.applied == ()
    assert len(result.rejected) == 1
    assert "past" in result.rejected[0].reason


def test_bare_numeric_date_with_no_year_is_ambiguous_not_rejected() -> None:
    result = apply_patch(TravelState(), [{"path": "dates.start", "operation": "set", "value": "01/07"}])

    assert result.applied == ()
    assert result.rejected == ()
    assert len(result.ambiguous) == 1
    assert result.ambiguous[0].kind == "missing_year"
    assert result.ambiguous[0].path == "dates.start"


def test_bare_numeric_date_with_both_components_under_13_is_day_month_ambiguous() -> None:
    future_year = date.today().year + 1

    result = apply_patch(
        TravelState(), [{"path": "dates.start", "operation": "set", "value": f"1-2-{future_year}"}]
    )

    assert result.applied == ()
    assert result.rejected == ()
    assert len(result.ambiguous) == 1
    ambiguity = result.ambiguous[0]
    assert ambiguity.kind == "day_month_order"
    # DD-MM reading (1 Feb) first, MM-DD reading (2 Jan) second.
    assert ambiguity.candidates == (f"{future_year}-02-01", f"{future_year}-01-02")


def test_bare_numeric_date_where_one_reading_already_passed_resolves_to_the_other_silently(monkeypatch) -> None:
    """Both `x<=12` and `y<=12` is not enough to ask -- if one calendar-valid
    reading already passed, it was never a real option, so the other
    resolves silently instead of offering an impossible choice. "Today" is
    frozen (rather than derived from the live clock) so this is correct on
    every day of the year, not just ones where day != month."""
    import src.domain.travel_state as travel_state_module

    class _FixedDate(date):
        @classmethod
        def today(cls):
            return date(2026, 8, 13)

    monkeypatch.setattr(travel_state_module, "date", _FixedDate)

    # "12-08-2026" reads as either 12 Aug (yesterday relative to the frozen
    # "today") or 8 Dec (still upcoming) -- only the latter is a real option.
    result = apply_patch(TravelState(), [{"path": "dates.start", "operation": "set", "value": "12-08-2026"}])

    assert result.ambiguous == ()
    assert len(result.applied) == 1
    assert result.state.get("dates.start").value == "2026-12-08"


def test_bare_numeric_date_where_both_readings_already_passed_is_rejected_as_past() -> None:
    result = apply_patch(TravelState(), [{"path": "dates.start", "operation": "set", "value": "1-1-2020"}])

    assert result.applied == ()
    assert result.ambiguous == ()
    assert len(result.rejected) == 1
    assert "past" in result.rejected[0].reason


def test_bare_numeric_date_with_one_component_over_12_resolves_silently() -> None:
    future_year = date.today().year + 1

    result = apply_patch(
        TravelState(), [{"path": "dates.start", "operation": "set", "value": f"31-07-{future_year}"}]
    )

    assert result.rejected == ()
    assert result.ambiguous == ()
    assert len(result.applied) == 1
    assert result.state.get("dates.start").value == f"{future_year}-07-31"


def test_bare_numeric_date_with_equal_day_and_month_is_unambiguous() -> None:
    future_year = date.today().year + 1

    result = apply_patch(
        TravelState(), [{"path": "dates.start", "operation": "set", "value": f"5-5-{future_year}"}]
    )

    assert result.ambiguous == ()
    assert len(result.applied) == 1
    assert result.state.get("dates.start").value == f"{future_year}-05-05"


def test_bare_numeric_date_with_neither_reading_valid_is_rejected_not_ambiguous() -> None:
    future_year = date.today().year + 1

    result = apply_patch(
        TravelState(), [{"path": "dates.start", "operation": "set", "value": f"35-13-{future_year}"}]
    )

    assert result.applied == ()
    assert result.ambiguous == ()
    assert len(result.rejected) == 1
    assert "not a valid calendar date" in result.rejected[0].reason


def test_ambiguity_resolution_via_a_candidate_iso_value_applies_cleanly() -> None:
    """The interrupt-resolution shape `validate_patch` (the graph node) relies
    on: re-running `apply_patch` with the chosen candidate as the new value
    resolves cleanly, no second ambiguity."""
    future_year = date.today().year + 1
    first = apply_patch(TravelState(), [{"path": "dates.start", "operation": "set", "value": f"1-2-{future_year}"}])
    chosen = first.ambiguous[0].candidates[0]

    resolved = apply_patch(TravelState(), [{"path": "dates.start", "operation": "set", "value": chosen}])

    assert resolved.ambiguous == ()
    assert resolved.rejected == ()
    assert resolved.state.get("dates.start").value == chosen


def test_wildcard_day_key_normalizes_equivalent_forms_to_one_slot() -> None:
    result = apply_patch(
        TravelState(),
        [
            {"path": "daily_preferences.5.theme", "operation": "set", "value": "biển"},
            {"path": "daily_preferences.05.theme", "operation": "set", "value": "ẩm thực"},
        ],
    )

    assert len(result.applied) == 2
    as_dict = result.state.to_dict()
    assert [key for key in as_dict if key.startswith("daily_preferences.")] == ["daily_preferences.5.theme"]
    assert result.state.get("daily_preferences.5.theme").value == "ẩm thực"


def test_from_dict_drops_paths_outside_the_current_allow_list() -> None:
    restored = TravelState.from_dict(
        {
            "destination": {"presence": "set", "value": "Huế"},
            "totally.unknown.path": {"presence": "set", "value": "x"},
        }
    )

    assert set(restored.to_dict().keys()) == {"destination"}
