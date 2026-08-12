---
phase: 6
title: "Impact map, locked days, day-level regeneration"
status: pending
priority: P2
effort: "3d"
dependencies: [2]
---

# Phase 6: Impact map, locked days, day-level regeneration

## Overview

Make "which workflows does this change affect" explicit data, add day locking, and stop
rebuilding the whole trip to edit one day.

## Problem

**Impact is implicit and hand-rolled.** `requires_candidate_rebuild` (`session.py:554`) is a
one-off inline version of an impact map, covering exactly four fields. Every other state
change has its consequences hard-coded at whatever call site happens to make it — so a new
field silently affects nothing until someone remembers to wire it.

**Editing one day rebuilds everything.** `_apply_day_replan:1378` calls `_build_trip_data`
for the entire trip, then discards all but one day (`:1388`). Consequences:

- Every unaffected day is re-searched and re-scheduled — cost and latency for no benefit.
- `exclude_attraction_ids=_scheduled_attraction_ids(current_data)` (`:1386`) excludes every
  currently scheduled attraction across **all** days, so a thin destination can yield an
  empty or degraded day 1.
- A failure anywhere in the trip fails the single-day edit.
- Directly contradicts the architecture doc §17: *"Do not regenerate unaffected days."*

**No lock concept.** "Budget còn 8 triệu nhưng giữ nguyên ngày 1" (doc §18) has no
representation — `locked_days` does not exist.

## Requirements

- Functional: each state path declares which workflows it affects; adding a path without an
  impact entry fails a test.
- Functional: a single-day edit regenerates only that day.
- Functional: `locked_days` prevents regeneration of listed days; other days absorb the change.
- Functional: a day-scoped edit only excludes attractions scheduled on *that* day, not all days.
- Non-functional: multi-day and whole-trip edits keep working — this narrows scope, it does
  not remove the wide path.

## Architecture

Impact map in `travel_state.py`, next to `ALLOWED_PATHS` so the two cannot drift:

```python
IMPACT_MAP = {
    "destination":                   ("hotel", "itinerary"),
    "dates.start": ("hotel", "itinerary"), "dates.end": ("hotel", "itinerary"),
    "people":                        ("hotel", "itinerary"),
    "budget.max":                    ("hotel", "itinerary"),
    "hotel_preferences.amenities":   ("hotel",),
    "hotel_preferences.radius_km":   ("hotel",),
    "preferences.themes":            ("itinerary",),
    "daily_preferences.*.theme":     ("itinerary_day",),   # narrowest scope
    "locked_days":                   (),
}
```

`detect_impact(applied_changes) -> set[Workflow]` becomes the single decision point that
`requires_candidate_rebuild` currently approximates.

Day-level regeneration: extract the per-day path out of `_build_trip_data` as
`rebuild_day(current_data, day_number, theme, *, locked_days)`. Both the existing
whole-trip builder and the new single-day path call the same scheduling primitives, so
there is no second scheduler to keep in sync — the shared code is
`_search_attraction_candidates` + `build_itinerary`, unchanged.

`locked_days` lives on `itinerary.planning_constraints`, which already carries per-day
policy (`latest_outing_start_by_day`, `meal_preferences_by_day`) — same shape, same
persistence, no schema change.

## Related Code Files

- Modify: `backend/src/services/travel_state.py` — `IMPACT_MAP`, `detect_impact`
- Modify: `backend/src/services/trip_planner.py` — `_apply_day_replan` (:1354-1392), extract `rebuild_day`, `_scheduled_attraction_ids` day scoping (:1386)
- Modify: `backend/src/agents/session.py` — replace `requires_candidate_rebuild` (:554) with `detect_impact`
- Modify: `backend/src/services/trip_scheduler.py` — honor `locked_days` in repair passes
- Create: `backend/tests/test_impact_map.py`, `backend/tests/test_rebuild_day.py`

## Implementation Steps

1. Run `impact` on `_apply_day_replan` and `_build_trip_data` before touching them.
2. Add `IMPACT_MAP` + `detect_impact`; test that every `ALLOWED_PATHS` entry has an impact entry.
3. Replace `requires_candidate_rebuild` with `detect_impact`; its existing tests are the gate.
4. Extract `rebuild_day` from `_build_trip_data`, reusing the same scheduling primitives.
5. Scope `exclude_attraction_ids` to the target day.
6. Point `_apply_day_replan` at `rebuild_day`.
7. Add `locked_days` to `planning_constraints`; honor it in `rebuild_day` and repair passes.
8. Benchmark a single-day edit before and after; record both numbers in the PR.

## Success Criteria

- [ ] Editing day 1 leaves days 2..N byte-identical
- [ ] A single-day edit issues no attraction search for other days
- [ ] `locked_days: [1]` keeps day 1 unchanged while a budget change reflows days 2..N
- [ ] A day-scoped edit can reuse an attraction scheduled on a different day
- [ ] Every `ALLOWED_PATHS` entry has an `IMPACT_MAP` entry, enforced by test
- [ ] Single-day edit latency measurably lower than the current full rebuild
- [ ] `make test` green

## Risk Assessment

| Risk | Mitigation |
|---|---|
| `_build_trip_data` is load-bearing for new-trip creation | `rebuild_day` is extracted, not rewritten — both paths call the same primitives. New-trip tests are the gate |
| Day-level rebuild diverges from whole-trip rebuild over time | Shared primitives, plus a test asserting a 1-day trip produces the same result through both paths |
| `locked_days` interacts with existing `planning_constraints` repair | Reuses the established per-day constraint shape; `_reapply_planning_constraints` already scopes by day |
| Narrowing `exclude_attraction_ids` allows a duplicate across days | Intended — an attraction reused on a different day is acceptable and previously impossible. Assert it explicitly so it reads as a decision, not a regression |
