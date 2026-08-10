---
phase: 1
title: "Safety-net characterization tests"
status: completed
priority: P1
effort: "0.5d"
dependencies: []
---

# Phase 1: Safety-net characterization tests

## Overview

Lock today's intake behavior with tests before changing it, mirroring this repo's own
precedent (`plans/260802-1437-langgraph-full-orchestration-and-durable-state/phase-02-safety-net-characterization-tests.md`).
No behavior changes in this phase.

## Requirements

- Functional: characterize the exact current sequencing across
  `TripIntakeState.next_question()` → `HotelPreferenceState.next_question()` →
  `recommend_hotels` invocation, so Phase 3's same-turn-carry-through fix has a
  before/after diff to point at.
- Functional: characterize `derive_stage()` (`session.py:84-92`) returning `"intake"`
  for every turn in that sequence (including the hotel-budget question), so a
  regression that accidentally changes the reported `stage` is caught.
- Functional: characterize the existing chip-generation function around
  `session.py:340-369` (find its exact name/signature first) for both the pending
  hotel-list case and the budget-tier-suggestion case.
- Non-functional: no production code edited in this phase — tests only.

## Architecture

None — test-only phase.

## Related Code Files

- Create: `tests/test_intake_form_characterization.py`
- Read (no edit): `src/agents/session.py`, `src/services/trip_intake.py`,
  `src/services/hotel_selection.py`

## Implementation Steps

1. Read `src/agents/session.py` in full around `_run_intake` (736-765) and the chip
   function at 340-369 to get exact current signatures/names.
2. Write a characterization test that drives a fresh `TripSession` through: destination
   → duration → start_date → people → budget tier pick, asserting the exact `stage`
   and chip/suggestion values at each turn, and that `recommend_hotels` only fires on
   the turn after the budget question is answered (today's two-turn behavior).
3. Write a characterization test for `TripIntakeState.is_complete` excluding
   `preferences` (already covered in `tests/test_trip_intake.py` — confirm it still
   passes, don't duplicate if redundant).
4. Run `pytest tests/test_intake_form_characterization.py -v` and confirm green
   against current code.

## Success Criteria

- [ ] New characterization test file exists and passes against unmodified code.
- [ ] Test explicitly asserts the two-turn (not one-turn) budget resolution — this
      assertion is expected to need updating in Phase 3, and that diff is the point.

## Risk Assessment

- **Risk:** characterization test is too loose and doesn't actually catch the Phase 3
  behavior change. **Mitigation:** assert on turn count / exact tool invoked per turn,
  not just final state.
