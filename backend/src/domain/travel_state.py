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
_AMENITY_ID_PATTERN = re.compile(r"^[a-z0-9_]{1,64}$")
_AMENITY_POLARITIES = frozenset({"require", "exclude", "prefer"})
TRAVEL_STATE_SCHEMA_VERSION = 2


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
        "constraints.max_items_by_day.*",  # Phase 12
        "daily_preferences.*.theme",  # wildcard segment — day number
        "locked_days",
    }
)

# Every path's workflow fan-out, kept beside ALLOWED_PATHS so the two cannot
# drift. detect_impact() is the graph's routing input; the orchestration layer
# maps these workflow labels onto worker nodes. That mapping deliberately lives
# outside this module -- this layer stays ignorant of graph node names.
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
    "constraints.max_items_by_day.*": ("itinerary_day",),
    "daily_preferences.*.theme": ("itinerary_day",),  # narrowest scope
    # Review finding F4: was `()` -- a patch that only touched `locked_days`
    # never delegated to any worker, so the validated slot had zero effect
    # on which days actually got locked (itinerary_node only read the
    # separate, LLM-parsed `lock_days` action's copy inside trip_data).
    # `itinerary_node` now syncs this slot into trip_data on every run.
    "locked_days": ("itinerary",),
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
            value = raw.get("value")
            if (
                path == "hotel_preferences.amenities"
                and presence is Presence.SET
                and isinstance(value, list)
            ):
                upgraded = []
                for item in value:
                    try:
                        upgraded.append(_validate_amenity_preference(item, path, cls(slots=slots)))
                    except PatchValidationError:
                        continue
                value = upgraded
            slots[path] = Slot(presence=presence, value=value)
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

    return PatchResult(
        state=TravelState(slots=slots),
        applied=tuple(applied),
        rejected=tuple(rejected),
    )


def detect_impact(applied_changes: Sequence[PatchChange]) -> set[Workflow]:
    """Union of workflows touched by an already-applied set of changes. The
    graph's routing input; the orchestration layer maps these labels onto worker
    nodes (that mapping deliberately lives outside this pure layer). Replaces
    the hand-rolled `requires_candidate_rebuild`."""
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
            if pattern == "hotel_preferences.amenities" and isinstance(item, Mapping):
                item_id = item.get("id")
                existing = [
                    entry for entry in current.value
                    if not isinstance(entry, Mapping) or entry.get("id") != item_id
                ]
            else:
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
    if pattern not in ("daily_preferences.*.theme", "constraints.max_items_by_day.*"):
        return path
    day_number = _extract_wildcard_day(path)
    if day_number is None or day_number < 1:
        raise PatchValidationError(f"{path}: invalid day number")
    if pattern == "constraints.max_items_by_day.*":
        return f"constraints.max_items_by_day.{day_number}"
    return f"daily_preferences.{day_number}.theme"


def trip_duration_days(state: TravelState) -> int | None:
    """Public: reused by `extract_patch` (Phase 6) for deterministic
    day-scope resolution before a patch reaches this module's own
    validators."""
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


def _validate_amenity_preference(value: Any, path: str, _state: TravelState) -> dict[str, Any]:
    """Validate the persisted, write-time-bound hotel preference record.

    A string is the read-through compatibility shape from schema v1. It is
    wrapped with confidence 0 so the orchestration layer can rebind it through
    the live catalog once, while every new write supplies a canonical record.
    """
    if isinstance(value, str):
        raw = value.strip()
        if not raw or len(raw) > 100:
            raise PatchValidationError(f"{path}: expected a non-empty amenity string up to 100 characters")
        return {
            "id": raw,
            "label": raw,
            "polarity": "require",
            "source_phrase": raw,
            "confidence": 0.0,
        }
    if not isinstance(value, Mapping):
        raise PatchValidationError(f"{path}: expected a bound amenity record")

    amenity_id = value.get("id")
    label = value.get("label")
    polarity = value.get("polarity")
    source_phrase = value.get("source_phrase")
    confidence = value.get("confidence")
    if not isinstance(amenity_id, str) or not _AMENITY_ID_PATTERN.fullmatch(amenity_id):
        raise PatchValidationError(f"{path}: amenity id must be a canonical catalog ID")
    if not isinstance(label, str) or not label.strip() or len(label.strip()) > 100:
        raise PatchValidationError(f"{path}: amenity label must be a non-empty string up to 100 characters")
    if polarity not in _AMENITY_POLARITIES:
        raise PatchValidationError(f"{path}: amenity polarity must be require, exclude, or prefer")
    if not isinstance(source_phrase, str) or not source_phrase.strip() or len(source_phrase.strip()) > 100:
        raise PatchValidationError(f"{path}: amenity source_phrase must be non-empty up to 100 characters")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1:
        raise PatchValidationError(f"{path}: amenity confidence must be between 0 and 1")
    return {
        "id": amenity_id,
        "label": label.strip(),
        "polarity": polarity,
        "source_phrase": source_phrase.strip(),
        "confidence": float(confidence),
    }


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


# Bare numeric date, day/month order and year deliberately unresolved —
# extract_patch's prompt now copies a bare-numeric date exactly as typed
# ("01/07", "1-2-2026") instead of guessing, precisely so this validator (not
# the model) is what decides whether it is ambiguous. Year, when present, may
# be 2 or 4 digits ("26" or "2026").
_RAW_NUMERIC_DATE_RE = re.compile(r"^\s*(\d{1,2})[-/.](\d{1,2})(?:[-/.](\d{2,4}))?\s*$")


def _normalize_year(raw: str) -> int:
    year = int(raw)
    return year + 2000 if year < 100 else year


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _resolve_numeric_date(x: int, y: int, year: int) -> date | None:
    """Two raw numbers `x-y` plus a year have two candidate calendar
    readings: day=x/month=y (the DD-MM reading, Vietnamese convention), or
    day=y/month=x (MM-DD). The DD-MM reading always wins when it's a real
    calendar date, even if MM-DD would also be valid -- e.g. "1-2" always
    means 1 Feb, never 2 Jan. MM-DD is only used as a fallback when DD-MM
    itself is impossible (e.g. "31-07": day=31/month=7 is valid, so that
    wins outright -- there's no real MM-DD reading to fall back to anyway
    since month=31 doesn't exist). Returns None when neither reading is a
    real calendar date at all."""
    reading_dd_mm = _safe_date(year, y, x)
    if reading_dd_mm is not None:
        return reading_dd_mm
    return _safe_date(year, x, y) if x != y else None


def parse_date_value(value: Any, path: str) -> date:
    """Accepts either a clean ISO string (already unambiguous — a relative
    date like "ngày mai" that extract_patch resolved itself) or a raw numeric
    `D[-/.]M[-/.][Y]` fragment it deliberately left untouched. A missing year
    defaults to today's year, and an ambiguous day/month order always
    resolves to the DD-MM (Vietnamese) reading -- never asks."""
    if not isinstance(value, str):
        raise PatchValidationError(f"{path}: expected a string, got {type(value).__name__}")
    text = value.strip()

    try:
        return date.fromisoformat(text)
    except ValueError:
        pass

    match = _RAW_NUMERIC_DATE_RE.match(text)
    if not match:
        raise PatchValidationError(f"{path}: expected an ISO 8601 date (YYYY-MM-DD)")

    x, y, year_raw = match.groups()
    x, y = int(x), int(y)
    year = _normalize_year(year_raw) if year_raw is not None else date.today().year

    resolved = _resolve_numeric_date(x, y, year)
    if resolved is None:
        raise PatchValidationError(f"{path}: not a valid calendar date")
    return resolved


def _validate_date_start(value: Any, path: str, state: TravelState) -> str:
    """Valid date (ISO or unambiguous raw numeric), plus one temporal check:
    when `dates.end` is already known in this same working state, the start
    must fall strictly before it. Order-dependent within one patch (only the
    date applied second sees the other), which is enough to catch the actual
    failure mode: an inverted range submitted together.

    Deliberately does NOT reject a date already in the past, despite what
    earlier revisions of this docstring claimed. A bare `D-M` carrying no
    year resolves against the CURRENT year (`parse_date_value`), so through
    the back half of any year that routinely lands on a date that has
    already passed — "3-1" answered in August resolves to 3 January of this
    year, and both readings of it are past. Rejecting here without also
    rolling such a date forward a year would turn a perfectly reasonable
    answer into a dead end, so the pair is left open as one decision rather
    than half-applied."""
    start = parse_date_value(value, path)
    end_slot = state.get("dates.end")
    if end_slot.presence is Presence.SET and start >= date.fromisoformat(str(end_slot.value)):
        raise PatchValidationError(f"{path}: start date must be before the trip's end date")
    return start.isoformat()


#: The one rejection on `dates.end` that is an ordinary user request rather than a
#: malformed value: a same-day trip. `ask_slot` matches on this to explain it in the
#: user's language instead of echoing this English sentence into the chat — matched
#: against the constant, never a copy of the literal, so the two cannot drift.
END_NOT_AFTER_START_REASON = "end date must be after the trip's start date"


def _validate_date_end(value: Any, path: str, state: TravelState) -> str:
    end = parse_date_value(value, path)
    start_slot = state.get("dates.start")
    if start_slot.presence is Presence.SET and end <= date.fromisoformat(str(start_slot.value)):
        raise PatchValidationError(f"{path}: {END_NOT_AFTER_START_REASON}")
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
    max_day = trip_duration_days(state) or _MAX_DAY_NUMBER_FALLBACK
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
    max_day = trip_duration_days(state) or _MAX_DAY_NUMBER_FALLBACK
    if day_number > max_day:
        raise PatchValidationError(f"{path}: day {day_number} exceeds trip length ({max_day} days)")
    return day_number


_daily_max_items_validator = _int_range(1, 20)

def _validate_daily_max_items(value: Any, path: str, state: TravelState) -> int:
    day_number = _extract_wildcard_day(path)
    if day_number is None or day_number < 1:
        raise PatchValidationError(f"{path}: invalid day number")
    max_day = trip_duration_days(state) or _MAX_DAY_NUMBER_FALLBACK
    if day_number > max_day:
        raise PatchValidationError(f"{path}: day {day_number} exceeds trip length ({max_day} days)")
    return _daily_max_items_validator(value, path, state)


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
    "hotel_preferences.amenities": _validate_amenity_preference,
    "hotel_preferences.radius_km": _number_range(0, 50, inclusive_min=False),
    "hotel_preferences.center": _coordinate_string,
    "hotel_preferences.min_star_rating": _number_range(1, 5),
    "hotel_preferences.min_review_score": _number_range(0, 10),
    "constraints.max_items_per_day": _int_range(1, 20),
    "constraints.max_item_distance_km": _number_range(0, 50, inclusive_min=False),
    "constraints.max_items_by_day.*": _validate_daily_max_items,
    "daily_preferences.*.theme": _validate_daily_theme,
    "locked_days": _validate_locked_day,
}
