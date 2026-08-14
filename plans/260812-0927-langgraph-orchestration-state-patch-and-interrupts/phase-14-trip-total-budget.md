---
phase: 14
title: "Trip-total budget constraint"
status: done
priority: P2
effort: "2.5d"
dependencies: [9, 11]
---

# Phase 14: Trip-total budget constraint

## Overview

Support "tổng ngân sách dưới 3tr" — a constraint on the whole trip, which is a different
quantity from every budget the system handles today.

## Problem

All existing budget handling is **per-night hotel price**: `_BUDGET_TIER_RANGE_VND`,
`_parse_free_text_price`, `min_price`/`max_price`/`target_price` on the search RPC,
`_budget_bonus` ranking. Every one of them is VND-per-night.

`_calculate_trip_budget` (`trip_planner.py:458`) does compute a trip total — hotel stay total
plus known item costs — and writes it to `itinerary["budget"]` (`:750`). But it is **purely
descriptive**. Nothing reads it back as a bound, and nothing re-plans when it is exceeded.

So "tổng ngân sách dưới 3tr" currently has no representation at all, and the closest thing
(`budget.max`) means something different enough that mapping it there would be wrong: 3tr
total across 3 nights is 1tr/night, not 3tr/night.

## Requirements

- Functional: a stated trip total becomes a constraint that hotel selection and itinerary
  cost must jointly satisfy.
- Functional: exceeding the total triggers a re-plan of the unlocked parts, honoring Phase 9's
  `locked_days`.
- Functional: when the total cannot be met, say so and name what dominates the cost — never
  silently return an over-budget plan or a silently degraded one.
- Functional: trip-total and per-night budgets coexist; stating one does not erase the other.
- Non-functional: cost honesty is preserved. `_calculate_trip_budget` deliberately *"returns
  the known trip total without inventing meal or missing activity prices"* — the constraint
  must reason over known costs and state its coverage, not fabricate the unknown ones.

## Architecture

Path `budget.trip_total` added to `ALLOWED_PATHS` in Phase 3, distinct from `budget.max`.

Extraction must disambiguate, since Vietnamese phrasing is close:

| Utterance | Path |
|---|---|
| "phòng dưới 1 triệu", "1 triệu/đêm" | `budget.max` (per night) |
| "tổng ngân sách 3 triệu", "cả chuyến 3 triệu", "budget của tôi còn 8 triệu" | `budget.trip_total` |

Ambiguous phrasing with no "tổng"/"cả chuyến"/"/đêm" marker resolves by the Phase 7 rule:
ask, do not guess.

The constraint→re-plan loop is the doc §18 shape, and Phases 3 and 9 already supply both halves it
needs — `IMPACT_MAP` routes `budget.trip_total → (hotel, itinerary)`, and `locked_days` says
what may not be touched:

```
trip_total set / changed
   → detect_impact → {hotel, itinerary}
   → derive a per-night hotel ceiling from the remaining allowance
   → re-run hotel search under that ceiling
   → rebuild unlocked days
   → recompute _calculate_trip_budget
   → still over? report the dominant cost, do not silently degrade
```

**Bounded iteration.** One re-plan pass, then report. An unbounded optimise loop is out of
scope and would be the kind of unbounded LLM planning doc §38 warns against.

**Coverage honesty.** `_calculate_trip_budget` returns `None` when no cost is known and skips
items with unknown prices. The constraint reports what fraction of the plan carries known
costs, so "dưới 3tr" is never asserted over data that does not exist.

## Related Code Files

- Modify: `backend/src/domain/travel_state.py` — `budget.trip_total` path, validator, `IMPACT_MAP` entry
- Modify: `backend/src/services/trip_planner.py` — read `_calculate_trip_budget` as a bound; re-plan pass
- Modify: `backend/src/agents/nodes/extract_patch.py` — per-night vs total disambiguation
- Modify: `backend/src/services/trip_formatter.py` — surface total vs budget and coverage
- Create: `backend/tests/test_trip_total_budget.py`

## Implementation Steps

1. Add `budget.trip_total` with a validator; confirm it never collides with `budget.max`.
2. Add extraction disambiguation plus the ask-when-ambiguous path; table-test both phrasings.
3. Add the `IMPACT_MAP` entry routing to hotel + itinerary.
4. Derive a per-night hotel ceiling from the trip total and the night count.
5. Implement the single bounded re-plan pass honoring `locked_days`.
6. Implement the over-budget report naming the dominant cost component.
7. Add cost-coverage reporting so an unknown-price plan never claims to satisfy the bound.
8. Test the doc §37 case: "Budget còn 8 triệu, nhưng giữ nguyên ngày 1."

## Success Criteria

- [ ] "tổng ngân sách dưới 3tr" constrains hotel choice and itinerary cost together
- [ ] "phòng dưới 1 triệu" still maps to per-night, not total
- [ ] Ambiguous budget phrasing asks instead of guessing
- [ ] "8 triệu nhưng giữ nguyên ngày 1" leaves day 1 untouched and reflows the rest
- [ ] An unmeetable total is reported with the dominant cost named
- [ ] A plan with unknown item prices reports coverage rather than claiming compliance
- [ ] Per-night and trip-total budgets coexist without overwriting each other
- [ ] Re-plan runs at most one pass
- [ ] `make test` green

## Risk Assessment

| Risk | Mitigation |
|---|---|
| Extraction confuses per-night with total | Marker-word disambiguation plus ask-when-ambiguous; table test is the gate. This is the highest-value test in the phase |
| Re-plan loop does not terminate | Exactly one bounded pass, then report. Asserted by test |
| Unknown item prices make the bound meaningless | Report coverage explicitly; never claim compliance over unknown costs. Preserves `_calculate_trip_budget`'s existing honesty contract |
| Interacts with `locked_days` in surprising ways | Phase 9 dependency is hard; the doc §37 case is a required test |
| Derived per-night ceiling over-constrains and finds no hotel | Report the binding constraint (same contract as Phases 7 and 10) rather than dropping the bound |
