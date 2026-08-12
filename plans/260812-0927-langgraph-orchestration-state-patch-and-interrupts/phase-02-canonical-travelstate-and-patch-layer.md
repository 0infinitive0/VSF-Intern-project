---
phase: 2
title: "Canonical TravelState and patch layer"
status: pending
priority: P1
effort: "2d"
dependencies: []
---

# Phase 2: Canonical TravelState and patch layer

## Overview

Introduce one canonical travel state with a validated `{path, operation, value}` patch API
and an `ALLOWED_PATHS` allow-list. This is the keystone: Phases 3-8 all consume it. No
behavior changes in this phase — it is pure foundation plus a parallel representation.

## Problem

Four rival mutation mechanisms, no shared contract:

| Mechanism | Location | Scope | Merge rule |
|---|---|---|---|
| `TripIntakeState.with_message` | `trip_intake.py:272` | 10 trip facts | first-non-null-wins — **a set value can never be corrected** (`:296`) |
| `HotelPreferenceState.with_message` | `hotel_selection.py:696` | budget only | returns `self` unchanged when unparsed → silent no-op |
| `TripPreferenceUpdate` | `trip_intake.py:79` | 5 fields | explicit `changed_fields` — closest to a patch |
| `TripEditPlan` | `trip_edit_planner.py:101` | 9 operations | post-plan only |

Consequences already observed: a mistyped date is permanently uncorrectable; an unparsed
budget reply loops forever; "ngày 1 thiên nhiên" has no representable path at all.

Tri-state is the second half of the problem. `None` currently means both "never asked"
and "user said they don't care", which is exactly why the budget gate cannot distinguish
a skip from a parse failure.

## Requirements

- Functional: `apply_patch` accepts a list of changes, validates each against
  `ALLOWED_PATHS`, and returns the new state plus an explicit list of rejected changes.
- Functional: unknown, malformed, or out-of-allow-list paths are rejected individually —
  one bad change never discards the good ones in the same patch.
- Functional: every slot distinguishes `UNKNOWN` / `SET(value)` / `NOT_APPLICABLE`.
- Functional: a `SET` value can be replaced by a later patch (removes the first-non-null-wins trap).
- Non-functional: `TripIntakeState` and `HotelPreferenceState` keep their exact public API.
  Existing call sites and tests must not change in this phase.
- Non-functional: state serializes to JSON for `TripState` / Supabase without custom encoders.

## Architecture

New module `backend/src/services/travel_state.py`:

```python
class Presence(str, Enum):
    UNKNOWN = "unknown"            # never asked / never answered
    SET = "set"                    # user supplied a value
    NOT_APPLICABLE = "n/a"         # user explicitly opted out ("bao nhiêu cũng được")

@dataclass(frozen=True)
class Slot:
    presence: Presence = Presence.UNKNOWN
    value: Any = None

ALLOWED_PATHS = {
    "destination",
    "dates.start", "dates.end",
    "people",
    "budget.min", "budget.max", "budget.target",
    "preferences.themes", "preferences.companions",
    "preferences.pace", "preferences.day_rhythm", "preferences.notes",
    "hotel_preferences.amenities",
    "hotel_preferences.radius_km", "hotel_preferences.center",
    "daily_preferences.*.theme",       # wildcard segment — day number
    "locked_days",
}
```

`apply_patch(state, changes) -> PatchResult(state, applied, rejected)` where each change is
`{"path": str, "operation": "set"|"unset"|"append"|"remove", "value": Any}`.

Per-path validators live beside the allow-list so a path cannot be added without one —
`dates.start` gets the temporal check that does not exist today (Phase 3 consumes it),
`hotel_preferences.radius_km` gets the positive/max bound the doc requires.

### Views, not replacements

`TripIntakeState.from_dict` / `to_dict` gain a canonical-state adapter. The dataclass keeps
its fields and methods; it reads through to the canonical state. This is why the MEDIUM
blast radius (17 symbols, 5 direct callers) does not turn into 17 edits.

The four legacy mechanisms stay wired and authoritative in this phase. Phase 3 makes the
patch layer the writer; Phase 4 removes the ladder that depends on the old merge rules.

## Related Code Files

- Create: `backend/src/services/travel_state.py`
- Create: `backend/tests/test_travel_state.py`
- Modify: `backend/src/agents/state.py` — carry canonical state on `TripState`
- Modify: `backend/src/services/trip_intake.py` — `TripIntakeState` reads through (public API unchanged)
- Modify: `backend/src/services/hotel_selection.py` — `HotelPreferenceState` reads through (public API unchanged)

## Implementation Steps

1. Run `impact` on `TripIntakeState` and `HotelPreferenceState`; record direct callers in the PR.
2. Write `travel_state.py`: `Presence`, `Slot`, `ALLOWED_PATHS`, per-path validators, `apply_patch`.
3. Unit-test the patch layer standalone with hand-built dicts — the same convention
   `_ground_extracted_facts` and `normalize_day_themes` already follow in this repo.
4. Add the canonical state to `TripState` alongside the existing `intake` / `hotel_prefs` keys.
5. Make `TripIntakeState` / `HotelPreferenceState` read through, keeping their public API byte-identical.
6. Add a round-trip test: canonical state → `to_dict` → `from_dict` → canonical state.
7. Run the full suite; **zero test file changes are expected in this phase** — if a test
   needs editing, the view adapter is wrong, not the test.

## Success Criteria

- [ ] `apply_patch` rejects every path outside `ALLOWED_PATHS`, proven by test
- [ ] A rejected change does not discard valid changes in the same patch
- [ ] `UNKNOWN` vs `NOT_APPLICABLE` are distinguishable for budget
- [ ] A `SET` slot can be overwritten by a later patch
- [ ] `daily_preferences.3.theme` validates; `daily_preferences.99.theme` rejects against trip length
- [ ] Existing test suite passes with **no test file modified**
- [ ] `make test` green

## Risk Assessment

| Risk | Mitigation |
|---|---|
| `TripIntakeState` MEDIUM blast radius, 5 direct callers | Read-through view keeps the public API; no call-site edits. "No test file changed" is the pass/fail signal |
| Two sources of truth during transition | Deliberate and time-boxed to Phases 2-3. Canonical state is write-through-only here; legacy remains authoritative until Phase 4 |
| Wildcard path `daily_preferences.*.theme` widens the allow-list | Wildcard resolves to an integer day bounded by the trip's `duration_days`; anything else rejects |
| Slot serialization bloats `sessions.context_data` | Store `presence` only when not `UNKNOWN`; measure the row size delta in the round-trip test |
