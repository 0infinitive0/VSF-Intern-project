---
phase: 12
title: "Per-day itinerary constraints"
status: completed
priority: P2
effort: "2.5d"
dependencies: [9, 11]
---

# Phase 12: Per-day itinerary constraints

## Overview

Add two new constraint families to the scheduler: how many places a day may hold, and how far
apart consecutive places may be. Covers "1 địa điểm 1 ngày", "10 địa điểm 1 ngày", and
"các địa điểm gần nhau dưới 1km".

## Problem

`planning_constraints` supports exactly four keys today:
`latest_outing_start_by_day`, `latest_outing_end_by_day`, `meal_preferences`,
`meal_preferences_by_day`. There is **no** per-day item count and **no** inter-item distance
constraint anywhere in the scheduler.

Radius exists only for hotel search (`supabase_search.py` root/radius params). Nothing
constrains how far apart two consecutive itinerary items are — the scheduler clusters by
distance heuristically but accepts no explicit bound.

Related, and worth deciding rather than discovering: `MINIMUM_ITEMS_PER_DAY = 7`
(`itinerary_reuse.py:19`) is a *reuse-template quality gate*, not a scheduling rule. It does
not block a 1-item day, but such a day can never qualify as a reusable template. That
interaction must be explicit, not accidental.

## Requirements

- Functional: "mỗi ngày 1 địa điểm" and "mỗi ngày 10 địa điểm" both produce a schedule
  honoring the count, or explain precisely why they cannot.
- Functional: "các địa điểm gần nhau dưới 1km" bounds the distance between consecutive
  attraction items on a day.
- Functional: constraints can be per-day or whole-trip, matching the existing
  `*_by_day` + global shape already used by meal preferences.
- Functional: an unsatisfiable constraint reports the binding reason — "chỉ tìm được 4 địa
  điểm trong bán kính 1km" — rather than silently producing fewer items.
- Non-functional: meal and rest items are not counted toward the place limit; the user means
  attractions. State this explicitly in the constraint's definition.
- Non-functional: existing `latest_outing_*` and meal constraints keep working unchanged.

## Architecture

Extend `planning_constraints` with the established shape — no schema change, since it is a
JSONB column already carrying per-day maps:

```python
"max_items_per_day": 10,                    # whole trip default
"max_items_by_day": {"1": 1, "3": 6},       # per-day override
"max_item_distance_km": 1.0,                # consecutive attractions on a day
```

Paths added to `ALLOWED_PATHS` in Phase 3: `constraints.max_items_per_day`,
`constraints.max_item_distance_km`. Per-day overrides use the wildcard form already
established for `daily_preferences.*.theme`.

Enforcement belongs in the scheduler, not the orchestrator:

- **Count** is applied at day assembly in `build_itinerary` — take the top-N ranked candidates
  for the day instead of filling all slots.
- **Distance** reuses the existing haversine helper the data pipeline already has
  (`attraction_utils.py:44-50`) rather than adding a second implementation. Applied as a
  chain constraint between consecutive attractions, evaluated during candidate ordering.

Both are *bounds*, not targets: a day may hold fewer items when the destination cannot supply
enough candidates within the distance bound. That case must report, not silently degrade —
this is the same contract as Phase 8's "name the binding constraint".

## Related Code Files

- Modify: `backend/src/services/trip_scheduler.py` — `build_itinerary`, candidate ordering
- Modify: `backend/src/services/trip_planner.py` — thread constraints through `_build_trip_data` / `rebuild_day`
- Modify: `backend/src/domain/travel_state.py` — validators (count ≥ 1 and bounded; distance > 0 and bounded)
- Modify: `backend/src/services/itinerary_reuse.py` — make the `MINIMUM_ITEMS_PER_DAY` interaction explicit
- Create: `backend/tests/test_per_day_constraints.py`

## Implementation Steps

1. Run `impact` on `build_itinerary` before touching it — it is the shared primitive Phase 9's
   `rebuild_day` also depends on.
2. Add the three constraint keys plus validators.
3. Enforce the count bound at day assembly, excluding meal/rest items from the count.
4. Enforce the distance bound between consecutive attractions, reusing the existing haversine helper.
5. Add the unsatisfiable-constraint reporting path.
6. Decide and document the `MINIMUM_ITEMS_PER_DAY` interaction: a sparse day is valid but is
   not template-reusable. Assert it in a test so it reads as a decision.
7. Verify Phase 9's `rebuild_day` honors the same constraints on a single-day rebuild.

## Success Criteria

- [ ] "mỗi ngày chỉ 1 địa điểm" yields exactly one attraction per day
- [ ] "10 địa điểm 1 ngày" yields up to 10, or reports why fewer
- [ ] "các địa điểm gần nhau dưới 1km" — every consecutive attraction pair is within 1km
- [ ] Meal and rest items are not counted toward the place limit
- [ ] An unsatisfiable constraint names the binding reason instead of silently degrading
- [ ] Per-day override beats the whole-trip default
- [ ] Existing `latest_outing_*` and meal-preference constraints unchanged
- [ ] A single-day rebuild (Phase 9) honors the same constraints
- [ ] `make test` green

## Risk Assessment

| Risk | Mitigation |
|---|---|
| `build_itinerary` is the shared scheduling primitive for both whole-trip and single-day paths | Run `impact` first; constraints default to unset so every existing call is unchanged |
| Distance bound over-constrains a sparse destination into empty days | Report the binding constraint and the count actually achievable — never silently return an empty day |
| Two haversine implementations drift | Reuse `attraction_utils.py:44-50`; do not write a second one |
| Count bound interacts with meal slots and `latest_outing_*` | Count excludes meals/rest by definition; add a combined test with both families active |
| Sparse days silently stop being reusable templates | Made explicit in step 6 with an asserting test, rather than left as emergent behavior |
