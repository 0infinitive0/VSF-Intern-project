---
phase: 1
title: "Contract fix and routing seam"
status: complete
priority: P1
effort: "0.5d"
dependencies: []
---

# Phase 1: Contract fix and routing seam

## Overview

Fix the three `TurnResult` contract violations, then extract the routing
decision out of `process_chat_turn` into a named pure function — with **zero
behavior change**. This creates the seam Phase 2 plugs the supervisor into, and
proves the regression harness still guards the flow before anything risky moves.

## Requirements

**Functional**
- Every `process_chat_turn` return path returns a `TurnResult`, never a `str`.
- Routing decision is computed by one function that returns a route label.
- Route execution is unchanged; only the decision is relocated.

**Non-functional**
- `tests/test_structural_regression_harness.py` passes before and after with no
  edits to the test file.
- No change to `stage` derivation, `suggestions_for`, or the HTTP contract.

## Architecture

Introduce a route enum and a decision function alongside the existing cascade:

```python
# src/agents/routing_decision.py  (new)

Route = Literal["select_hotel", "finalize", "new_trip", "edit_draft", "intake", "chat"]

@dataclass(frozen=True)
class RouteContext:
    """Everything the router may look at. Deliberately excludes venue data,
    hotel candidates, and itinerary items — a router cannot select a place."""
    has_pending_hotel_selection: bool
    has_trip_data: bool
    is_trip_finalized: bool
    initial_plan_complete: bool
    planning_new_trip: bool
    intake_complete: bool
    hotel_prefs_complete: bool
    has_pending_edit_clarification: bool


def route_context_from_session(session) -> RouteContext: ...

def decide_route_by_rules(context: RouteContext, user_input: str) -> Route:
    """Today's cascade conditions, verbatim, returning a label instead of
    executing. Becomes Phase 2's fallback layer."""
```

`process_chat_turn` then becomes: build context → `decide_route_by_rules` →
`match route:` dispatch to the *existing, unmoved* branch bodies.

**Ordering constraint:** `decide_route_by_rules` must reproduce the current
priority order exactly — pending hotel (`:456`) > finalize (`:479`) > new-trip
detection (`:486`) > edit (`:493`) > intake (`:515`) > chat (`:546`). Any
reordering here is a behavior change and belongs to a later phase, not this one.

**Known subtlety to preserve:** the pending-hotel branch (`:456-477`) is not a
pure decision — it *calls* `select_hotel`, then inspects whether
`session.pending_hotel_selection` was cleared to learn whether the pick
resolved, and may then fall through to the next branch. Do not flatten this into
a single upfront label without preserving the fall-through; model it as route
`select_hotel` plus an explicit "unresolved, continue" outcome.

## Related Code Files

- Create: `src/agents/routing_decision.py`
- Modify: `src/agents/session.py` (`process_chat_turn`, lines 444-598)
- Read only, do not modify: `src/services/trip_intake.py`,
  `src/services/trip_scheduler.py`, `src/agents/graph.py`
- Test: `tests/test_structural_regression_harness.py` (must pass unedited)

## Implementation Steps

1. Run `pytest tests/test_structural_regression_harness.py -v` and record the
   baseline. Capture the exact pass list — it is the contract for this phase.
2. Fix `session.py:491` → `return TurnResult(text=unsupported_reply, tool=None)`.
3. Fix `session.py:503` → wrap in `TurnResult(text=..., tool=None)`.
4. Fix `session.py:507` → wrap in `TurnResult(text=..., tool=None)`.
5. Add a regression test asserting all three paths return `TurnResult`:
   - saved plan present + message naming an unknown city (`:491`)
   - saved-plan edit where `plan_trip_edit` raises `TripEditPlanError` (`:503`)
   - saved-plan edit returning `decision == "clarify"` (`:507`)
6. Create `src/agents/routing_decision.py` with `Route`, `RouteContext`,
   `route_context_from_session`, `decide_route_by_rules`.
7. Move the cascade *conditions* into `decide_route_by_rules`, leaving branch
   *bodies* in `process_chat_turn`, dispatched on the returned label.
8. Re-run the harness. Zero diff in outcomes.

## Success Criteria

- [x] `mypy`/type check shows no `str` returned where `TurnResult` is declared
- [x] Three new tests cover the previously-crashing paths
- [x] `decide_route_by_rules` is pure w.r.t. session mutation and I/O — **but
  not fully LLM-free** (see Deviations below); accepted by user 2026-07-31.
- [x] `RouteContext` carries no venue, hotel, or itinerary-item data
- [x] `tests/test_structural_regression_harness.py` passes — **with two
  mechanical edits** (see Deviations below); accepted by user 2026-07-31.
- [x] `git diff src/services/trip_intake.py src/services/trip_scheduler.py` is empty

## Deviations from spec (both accepted by user 2026-07-31)

1. **Baseline was already broken.** `tests/test_structural_regression_harness.py`
   and `tests/test_chat_session.py` (both from commit `3d03220`) called
   `reply.startswith(...)` / `reply == "..."` directly on `process_chat_turn`'s
   return value, but it already returned `TurnResult`, not `str` — a
   pre-existing bug unrelated to this plan. Fixed by changing call sites to use
   `.text` (mechanical, no assertions weakened). This was required before any
   "zero behavior change" baseline could even be established.

2. **`decide_route_by_rules` is not fully LLM-free.** Distinguishing
   `new_trip` from `edit_draft` on a *weak* new-trip signal (a saved plan
   exists, no explicit "chuyến đi mới") requires checking whether the message
   names a *known* destination — the same check `_begin_new_trip_if_requested`
   already makes via the intake-extraction LLM (`TripIntakeState.with_message`).
   A strong signal or no signal never touches the LLM. **Consequence for R3
   (Ollama down):** the fallback layer is not fully offline-safe in this one
   narrow case — Phase 2/3 should account for this when testing "LLM
   unreachable" fallback behavior; it may fail closed specifically on a
   weak-signal new-trip message with a saved plan present. All other routes
   (`select_hotel`, `finalize`, `intake`, `chat`, and `edit_draft`/`new_trip`
   on a strong/no signal) remain LLM-free in the fallback.

3. **Harness monkeypatch retargeted.** `is_finalization_request` moved from
   `src.agents.session` to `src.agents.routing_decision` (it's a routing
   predicate). The harness and `test_chat_session.py` patched it by module
   attribute name (`session_module.is_finalization_request`); both retargeted
   to `src.agents.routing_decision.is_finalization_request`. This is exactly
   the drift R4 anticipated — caught loudly (AttributeError), not silently.

## Risk Assessment

**Risk:** The pending-hotel branch's call-then-inspect-then-fall-through shape
(`:456-477`) resists being expressed as a pure upfront decision.
**Mitigation:** Keep it as route + outcome rather than forcing purity. If it
cannot be expressed cleanly, leave that single branch in place and route the
other five — the seam is still achieved.

**Risk:** The harness stubs symbols by module-level name; moving code can make
a stub silently stop applying, so tests pass while covering nothing.
**Mitigation:** Assert stub call counts, not only reply text, in the tests added
at step 5. Diff the harness's recorded call log before and after.

**Rollback:** Single self-contained commit; revert restores the cascade.
