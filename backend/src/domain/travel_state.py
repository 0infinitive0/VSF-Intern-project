"""Canonical travel state: validated `{path, operation, value}` patch API.

Replaces four rival mutation mechanisms (`TripIntakeState.with_message`,
`HotelPreferenceState.with_message`, `TripPreferenceUpdate`, `TripEditPlan`)
with one writer, one allow-list, and one tri-state slot model. `UNKNOWN` means
"never asked/answered"; `NOT_APPLICABLE` means the user explicitly opted out
(e.g. "bao nhiêu cũng được" for budget) — the two must stay distinguishable so
a skip is never confused with a parse failure.

Pure module: no `services`, no I/O, no LLM client, no Supabase. See
`ARCHITECTURE.md` § Layer Architecture & Import Rules.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any, Literal

Operation = Literal["set", "unset", "append", "remove"]
Workflow = Literal["hotel", "itinerary", "itinerary_day"]

_OPERATIONS: frozenset[str] = frozenset({"set", "unset", "append", "remove"})

# Trip length is unknown until both dates.start and dates.end are SET; day-bound
# validators fall back to this generous ceiling so an early "ngày 5 biển" isn't
# rejected just because the dates question hasn't been answered yet.
_MAX_DAY_NUMBER_FALLBACK = 90


class Presence(StrEnum):
    UNKNOWN = "unknown"
    SET = "set"
    NOT_APPLICABLE = "n/a"


@dataclass(frozen=True)
class Slot:
    presence: Presence = Presence.UNKNOWN
    value: Any = None


class PatchValidationError(ValueError):
    """A single change's value failed its path's validator."""


ALLOWED_PATHS: frozenset[str] = frozenset(
    {
        "destination",
        "dates.start",
        "dates.end",
        "people",
        "budget.min",
        "budget.max",
        "budget.target",  # per NIGHT
        "budget.trip_total",  # WHOLE TRIP — different quantity (Phase 14)
        "preferences.themes",
        "preferences.companions",
        "preferences.pace",
        "preferences.day_rhythm",
        "preferences.notes",
        "hotel_preferences.amenities",
        "hotel_preferences.radius_km",
        "hotel_preferences.center",
        "hotel_preferences.min_star_rating",  # 1-5 stars (Phase 8)
        "hotel_preferences.min_review_score",  # 0-10 score — a DIFFERENT column
        "constraints.max_items_per_day",  # Phase 12
        "constraints.max_item_distance_km",  # Phase 12
        "daily_preferences.*.theme",  # wildcard segment — day number
        "locked_days",
    }
)

# Every path's workflow fan-out, kept beside ALLOWED_PATHS so the two cannot
# drift. detect_impact() is the graph's routing input for
# detect_impact -> hotel_flow | itinerary_flow | general_qa | none.
IMPACT_MAP: dict[str, tuple[Workflow, ...]] = {
    "destination": ("hotel", "itinerary"),
    "dates.start": ("hotel", "itinerary"),
    "dates.end": ("hotel", "itinerary"),
    "people": ("hotel", "itinerary"),
    "budget.min": ("hotel",),
    "budget.max": ("hotel",),  # per night
    "budget.target": ("hotel",),
    "budget.trip_total": ("hotel", "itinerary"),  # whole trip — Phase 14
    "preferences.themes": ("itinerary",),
    "preferences.companions": ("itinerary",),
    "preferences.pace": ("itinerary",),
    "preferences.day_rhythm": ("itinerary",),
    "preferences.notes": ("hotel", "itinerary"),  # free text — content unknown, so both
    "hotel_preferences.amenities": ("hotel",),
    "hotel_preferences.radius_km": ("hotel",),
    "hotel_preferences.center": ("hotel",),
    "hotel_preferences.min_star_rating": ("hotel",),
    "hotel_preferences.min_review_score": ("hotel",),
    "constraints.max_items_per_day": ("itinerary",),
    "constraints.max_item_distance_km": ("itinerary",),
    "daily_preferences.*.theme": ("itinerary_day",),  # narrowest scope
    "locked_days": (),
}

# Paths whose value is a list, mutable one item at a time via append/remove.
# Every other path is scalar: only set/unset apply to it.
_LIST_PATHS: frozenset[str] = frozenset(
    {
        "preferences.themes",
        "preferences.day_rhythm",
        "hotel_preferences.amenities",
        "locked_days",
    }
)


@dataclass(frozen=True)
class TravelState:
    """Canonical state: every ALLOWED_PATHS entry maps to a Slot. A path absent
    from `slots` is UNKNOWN — the same thing `to_dict`/`from_dict` assume, so
    apply_patch never stores an explicit UNKNOWN entry (see `apply_patch`)."""

    slots: Mapping[str, Slot] = field(default_factory=dict)

    def get(self, path: str) -> Slot:
        return self.slots.get(path, Slot())

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe representation for `TripState` / Supabase — no custom
        encoder needed since Presence collapses to its plain string `.value`.
        UNKNOWN slots are never stored (they are the absence of a key), which
        keeps `sessions.context_data` from growing for facts nobody has
        answered yet."""
        return {
            path: {"presence": slot.presence.value, "value": slot.value}
            for path, slot in self.slots.items()
            if slot.presence is not Presence.UNKNOWN
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> TravelState:
        """Inverse of `to_dict`. Values are trusted as-is (already validated
        when they were written) — but the path itself is re-checked against
        `ALLOWED_PATHS`, so a path removed from the allow-list after this
        state was persisted doesn't resurrect on load."""
        slots: dict[str, Slot] = {}
        for path, raw in (data or {}).items():
            if _pattern_for_path(path) is None or not isinstance(raw, Mapping):
                continue
            presence_value = raw.get("presence")
            if not isinstance(presence_value, str):
                continue
            try:
                presence = Presence(presence_value)
            except ValueError:
                continue
            if presence is Presence.UNKNOWN:
                continue
            slots[path] = Slot(presence=presence, value=raw.get("value"))
        return cls(slots=slots)


@dataclass(frozen=True)
class PatchChange:
    path: str
    operation: Operation
    value: Any = None


@dataclass(frozen=True)
class RejectedChange:
    path: str
    operation: str
    value: Any
    reason: str


@dataclass(frozen=True)
class PatchResult:
    state: TravelState
    applied: tuple[PatchChange, ...]
    rejected: tuple[RejectedChange, ...]


def apply_patch(
    state: TravelState, changes: Sequence[Mapping[str, Any] | PatchChange]
) -> PatchResult:
    """Validate each change against `ALLOWED_PATHS` and its per-path validator.
    One bad change is rejected on its own — it never discards the good changes
    in the same patch, and never raises."""
    slots: dict[str, Slot] = dict(state.slots)
    applied: list[PatchChange] = []
    rejected: list[RejectedChange] = []

    for raw_change in changes:
        change = _coerce_change(raw_change)
        if change is None:
            rejected.append(_reject_malformed(raw_change))
            continue

        pattern = _pattern_for_path(change.path)
        if pattern is None:
            rejected.append(
                RejectedChange(change.path, change.operation, change.value, "path is not in ALLOWED_PATHS")
            )
            continue

        try:
            storage_key = _canonical_key(pattern, change.path)
        except PatchValidationError as exc:
            rejected.append(RejectedChange(change.path, change.operation, change.value, str(exc)))
            continue

        if change.operation == "unset":
            slots.pop(storage_key, None)
            applied.append(change)
            continue

        working_state = TravelState(slots=dict(slots))
        try:
            slots[storage_key] = _apply_single(pattern, change, slots.get(storage_key, Slot()), working_state)
        except PatchValidationError as exc:
            rejected.append(RejectedChange(change.path, change.operation, change.value, str(exc)))
            continue

        applied.append(change)

    return PatchResult(state=TravelState(slots=slots), applied=tuple(applied), rejected=tuple(rejected))


def detect_impact(applied_changes: Sequence[PatchChange]) -> set[Workflow]:
    """Union of workflows touched by an already-applied set of changes. The
    graph's routing input for detect_impact -> hotel_flow | itinerary_flow |
    general_qa | none; replaces the hand-rolled `requires_candidate_rebuild`."""
    impacted: set[Workflow] = set()
    for change in applied_changes:
        pattern = _pattern_for_path(change.path)
        if pattern is None:
            continue
        impacted.update(IMPACT_MAP.get(pattern, ()))
    return impacted


def _coerce_change(raw: Any) -> PatchChange | None:
    """`raw` is nominally `Mapping[str, Any] | PatchChange`, but this also
    guards untrusted input (e.g. a malformed LLM-emitted patch item) that
    doesn't actually match either shape at runtime."""
    if isinstance(raw, PatchChange):
        return raw
    if not isinstance(raw, Mapping):
        return None
    path = raw.get("path")
    operation = raw.get("operation")
    if not isinstance(path, str) or not path or operation not in _OPERATIONS:
        return None
    # "set" with an explicit `"value": null` is the NOT_APPLICABLE signal (see
    # _apply_single) — but a `"value"` key that is simply MISSING is a malformed
    # emission, not an opt-out, and must not be silently read as one.
    if operation == "set" and "value" not in raw:
        return None
    return PatchChange(path=path, operation=operation, value=raw.get("value"))


def _reject_malformed(raw: Any) -> RejectedChange:
    if isinstance(raw, Mapping):
        path = str(raw.get("path", ""))
        operation = str(raw.get("operation", ""))
        value = raw.get("value")
    else:
        path, operation, value = "", "", None
    return RejectedChange(
        path=path,
        operation=operation,
        value=value,
        reason="malformed change: path must be a non-empty string and operation "
        "must be one of set/unset/append/remove",
    )


def _apply_single(pattern: str, change: PatchChange, current: Slot, working_state: TravelState) -> Slot:
    is_list = pattern in _LIST_PATHS
    validator = _VALIDATORS[pattern]

    if change.operation == "set":
        if change.value is None:
            # The user answered explicitly with "no preference" — distinct from
            # never having asked, which is why this is NOT_APPLICABLE, not unset.
            return Slot(presence=Presence.NOT_APPLICABLE, value=None)
        if is_list:
            if not isinstance(change.value, list):
                raise PatchValidationError(f"{change.path}: 'set' on a list path requires a list value")
            normalized = [validator(item, change.path, working_state) for item in change.value]
            return Slot(presence=Presence.SET, value=normalized)
        return Slot(presence=Presence.SET, value=validator(change.value, change.path, working_state))

    if change.operation in ("append", "remove"):
        if not is_list:
            raise PatchValidationError(f"{change.path}: operation {change.operation!r} is only valid for list paths")
        if change.value is None:
            raise PatchValidationError(f"{change.path}: operation {change.operation!r} requires a value")
        item = validator(change.value, change.path, working_state)
        if change.operation == "remove":
            # Removing from a slot with nothing SET is not "the user chose an
            # empty list" — it must reject, not fabricate that explicit answer.
            if current.presence is not Presence.SET or not isinstance(current.value, list):
                raise PatchValidationError(f"{change.path}: cannot remove from a slot with no value")
            existing = [entry for entry in current.value if entry != item]
            return Slot(presence=Presence.SET, value=existing)
        existing = list(current.value) if current.presence is Presence.SET and isinstance(current.value, list) else []
        if item not in existing:
            existing.append(item)
        return Slot(presence=Presence.SET, value=existing)

    raise PatchValidationError(f"{change.path}: unsupported operation {change.operation!r}")


def _pattern_for_path(path: str) -> str | None:
    if path in ALLOWED_PATHS:
        return path
    segments = path.split(".")
    for pattern in ALLOWED_PATHS:
        if "*" not in pattern:
            continue
        pattern_segments = pattern.split(".")
        if len(pattern_segments) != len(segments):
            continue
        if all(p == "*" or p == s for p, s in zip(pattern_segments, segments)):
            return pattern
    return None


def _extract_wildcard_day(path: str) -> int | None:
    parts = path.split(".")
    if len(parts) != 3:
        return None
    try:
        return int(parts[1])
    except ValueError:
        return None


def _canonical_key(pattern: str, path: str) -> str:
    """The dict key a change is actually stored under. For the wildcard
    pattern this normalizes the day segment ("05", " 5", "+5" all resolve to
    the same slot as "5") so equivalent paths never fork into separate,
    conflicting entries. Every other pattern already equals `path` exactly
    (no wildcard segment), so it passes through unchanged."""
    if pattern != "daily_preferences.*.theme":
        return path
    day_number = _extract_wildcard_day(path)
    if day_number is None or day_number < 1:
        raise PatchValidationError(f"{path}: invalid day number")
    return f"daily_preferences.{day_number}.theme"


def _trip_duration_days(state: TravelState) -> int | None:
    start_slot = state.get("dates.start")
    end_slot = state.get("dates.end")
    if start_slot.presence is not Presence.SET or end_slot.presence is not Presence.SET:
        return None
    try:
        start = date.fromisoformat(str(start_slot.value))
        end = date.fromisoformat(str(end_slot.value))
    except (TypeError, ValueError):
        return None
    delta = (end - start).days
    return delta if delta > 0 else None


# --- per-path validators -----------------------------------------------
# Each takes (value, path, state) and either returns the normalized value or
# raises PatchValidationError. Kept beside ALLOWED_PATHS/IMPACT_MAP so a path
# cannot be added without one — see the parity test in test_travel_state.py.

_Validator = Callable[[Any, str, TravelState], Any]


def _nonempty_str(max_len: int) -> _Validator:
    def _validate(value: Any, path: str, _state: TravelState) -> str:
        if not isinstance(value, str):
            raise PatchValidationError(f"{path}: expected a string, got {type(value).__name__}")
        text = value.strip()
        if not text or len(text) > max_len:
            raise PatchValidationError(f"{path}: expected a non-empty string up to {max_len} characters")
        return text

    return _validate


def _optional_str(max_len: int) -> _Validator:
    def _validate(value: Any, path: str, _state: TravelState) -> str:
        if not isinstance(value, str):
            raise PatchValidationError(f"{path}: expected a string, got {type(value).__name__}")
        text = value.strip()
        if len(text) > max_len:
            raise PatchValidationError(f"{path}: string exceeds {max_len} characters")
        return text

    return _validate


def _number_range(min_value: float, max_value: float, *, inclusive_min: bool = True) -> _Validator:
    def _validate(value: Any, path: str, _state: TravelState) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise PatchValidationError(f"{path}: expected a number") from None
        lower_ok = number >= min_value if inclusive_min else number > min_value
        if not lower_ok or number > max_value:
            raise PatchValidationError(f"{path}: expected a number in range ({min_value}, {max_value}]")
        return number

    return _validate


def _int_range(min_value: int, max_value: int) -> _Validator:
    def _validate(value: Any, path: str, _state: TravelState) -> int:
        try:
            number = int(value)
        except (TypeError, ValueError):
            raise PatchValidationError(f"{path}: expected an integer") from None
        if not min_value <= number <= max_value:
            raise PatchValidationError(f"{path}: expected an integer in [{min_value}, {max_value}]")
        return number

    return _validate


def _iso_date(value: Any, path: str, _state: TravelState) -> date:
    if not isinstance(value, str):
        raise PatchValidationError(f"{path}: expected a string, got {type(value).__name__}")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise PatchValidationError(f"{path}: expected an ISO 8601 date (YYYY-MM-DD)") from None


def _validate_date_start(value: Any, path: str, state: TravelState) -> str:
    """The temporal check `dates.start` didn't have before this phase: valid
    ISO format, plus — when `dates.end` is already known in this same working
    state — must fall strictly before it. Order-dependent within one patch
    (only the date applied second sees the other), which is enough to catch
    the actual failure mode: an inverted range submitted together."""
    start = _iso_date(value, path, state)
    end_slot = state.get("dates.end")
    if end_slot.presence is Presence.SET and start >= date.fromisoformat(str(end_slot.value)):
        raise PatchValidationError(f"{path}: start date must be before the trip's end date")
    return start.isoformat()


def _validate_date_end(value: Any, path: str, state: TravelState) -> str:
    end = _iso_date(value, path, state)
    start_slot = state.get("dates.start")
    if start_slot.presence is Presence.SET and end <= date.fromisoformat(str(start_slot.value)):
        raise PatchValidationError(f"{path}: end date must be after the trip's start date")
    return end.isoformat()


_COORDINATE_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")


def _coordinate_string(value: Any, path: str, _state: TravelState) -> str:
    match = _COORDINATE_RE.match(str(value))
    if not match:
        raise PatchValidationError(f"{path}: expected 'lat,lng'")
    lat, lng = float(match.group(1)), float(match.group(2))
    if not -90.0 <= lat <= 90.0 or not -180.0 <= lng <= 180.0:
        raise PatchValidationError(f"{path}: coordinate out of range")
    return f"{lat},{lng}"


def _validate_daily_theme(value: Any, path: str, state: TravelState) -> str:
    day_number = _extract_wildcard_day(path)
    if day_number is None or day_number < 1:
        raise PatchValidationError(f"{path}: invalid day number")
    max_day = _trip_duration_days(state) or _MAX_DAY_NUMBER_FALLBACK
    if day_number > max_day:
        raise PatchValidationError(f"{path}: day {day_number} exceeds trip length ({max_day} days)")
    if not isinstance(value, str):
        raise PatchValidationError(f"{path}: expected a string, got {type(value).__name__}")
    text = value.strip()
    if not text or len(text) > 200:
        raise PatchValidationError(f"{path}: theme must be a non-empty string up to 200 characters")
    return text


def _validate_locked_day(value: Any, path: str, state: TravelState) -> int:
    try:
        day_number = int(value)
    except (TypeError, ValueError):
        raise PatchValidationError(f"{path}: expected an integer day number") from None
    if day_number < 1:
        raise PatchValidationError(f"{path}: day number must be >= 1")
    max_day = _trip_duration_days(state) or _MAX_DAY_NUMBER_FALLBACK
    if day_number > max_day:
        raise PatchValidationError(f"{path}: day {day_number} exceeds trip length ({max_day} days)")
    return day_number


_VALIDATORS: dict[str, _Validator] = {
    "destination": _nonempty_str(200),
    "dates.start": _validate_date_start,
    "dates.end": _validate_date_end,
    "people": _int_range(1, 50),
    "budget.min": _number_range(0, 1_000_000_000),
    "budget.max": _number_range(0, 1_000_000_000),
    "budget.target": _number_range(0, 1_000_000_000),
    "budget.trip_total": _number_range(0, 1_000_000_000),
    "preferences.themes": _nonempty_str(100),
    "preferences.companions": _nonempty_str(200),
    "preferences.pace": _nonempty_str(100),
    "preferences.day_rhythm": _nonempty_str(100),
    "preferences.notes": _optional_str(1000),
    "hotel_preferences.amenities": _nonempty_str(100),
    "hotel_preferences.radius_km": _number_range(0, 50, inclusive_min=False),
    "hotel_preferences.center": _coordinate_string,
    "hotel_preferences.min_star_rating": _number_range(1, 5),
    "hotel_preferences.min_review_score": _number_range(0, 10),
    "constraints.max_items_per_day": _int_range(1, 20),
    "constraints.max_item_distance_km": _number_range(0, 50, inclusive_min=False),
    "daily_preferences.*.theme": _validate_daily_theme,
    "locked_days": _validate_locked_day,
}
