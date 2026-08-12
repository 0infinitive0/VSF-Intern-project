---
phase: 4
title: "Slot-driven interruptible intake"
status: pending
priority: P1
effort: "2d"
dependencies: [2, 3]
---

# Phase 4: Slot-driven interruptible intake

## Overview

Replace the hard-coded `if` ladder in `_run_intake` with a declarative slot registry over
the Phase 2 tri-state. Kills the entire "X chưa nhập chưa cho Y" deadlock class, not just
the reported budget instance.

## Problem

`_run_intake` (`session.py:1166-1206`) is five sequential `if` blocks. Each has exactly one
branch: answer the pending question, or re-ask it. There is no "the user said something
else" path.

The budget gate at step 2 is the worst instance:

- `HotelPreferenceState.with_message` returns `self` on any unparsed reply
  (`hotel_selection.py:709`) → `next_question` returns the same prompt → infinite loop.
- The escape hatch is a **fixed phrase list** (`_NO_BUDGET_PREFERENCE_PHRASES`, 8 strings)
  plus a number. Anything else loops.
- `direct_preference_update` (`session.py:713`) — the one path that could handle a different
  intent — requires `pending_hotel_selection is not None` **or** budget already complete.
  Both are false precisely while the budget gate is open. It is unreachable exactly when needed.
- `requires_stay_dates` (`routes.py:240`) requires `hotel_pref_state.is_complete`, so the
  **date picker is gated behind budget**. This is the literal mechanism behind the reported
  "ngân sách chưa nhập chưa cho edit".

## Requirements

- Functional: any pending question can be interrupted by a different recognized intent; the
  question is re-asked afterwards with context, not repeated verbatim.
- Functional: an unrecognized reply produces an explanation of what is being waited on and
  how to skip — never a verbatim repeat.
- Functional: an already-filled slot can be revised at any time.
- Functional: the date picker is no longer gated behind budget.
- Functional: budget is skippable via patch (`NOT_APPLICABLE`), not only via the 8 fixed phrases.
- Non-functional: question ordering stays destination → people → dates → budget by default,
  but ordering is data, not control flow.

## Architecture

New `backend/src/services/slot_registry.py`:

```python
@dataclass(frozen=True)
class SlotSpec:
    name: str                      # canonical path from ALLOWED_PATHS
    required: bool
    order: int
    ask: Callable[[TravelState, str], str]
    skippable: bool = False
```

`next_question(state)` = first spec whose slot is `UNKNOWN`, ordered by `order`. That single
expression replaces the ladder, and every slot inherits revisable / skippable / interruptible
behavior for free.

Turn flow becomes:

```
message → extract_patch (Phase 3) → apply_patch
        → did the patch fill or change anything?
            yes → acknowledge, then next_question(state)
            no  → explain what is pending + how to skip → next_question(state)
```

The key inversion: **the patch is attempted first, unconditionally.** The pending question
no longer decides whether the message is allowed to mean something else.

`_run_intake` becomes a graph node so Phase 5 can call `interrupt()` inside it — `interrupt()`
only works within a node, and intake is currently plain Python outside the graph. That
sequencing is why Phase 5 depends on this phase.

`HotelPreferenceState` keeps its guided-menu rendering (`format_guided_question`) — that
part works. What changes is that failing to parse a reply no longer traps the turn.

## Related Code Files

- Create: `backend/src/services/slot_registry.py`
- Create: `backend/tests/test_slot_registry.py`
- Modify: `backend/src/agents/session.py` — `_run_intake` (:1166-1206), `direct_preference_update` (:708-753), `suggestions_for` (:392-414)
- Modify: `backend/src/api/routes.py` — `requires_stay_dates` (:240-245), decouple from budget
- Modify: `backend/src/services/hotel_selection.py` — `HotelPreferenceState.with_message` returns an explicit unresolved signal instead of silent `self`

## Implementation Steps

1. Run `impact` on `_run_intake` and `HotelPreferenceState`.
2. Define the slot registry with today's default ordering, so ordering behavior is unchanged.
3. Implement `next_question(state)` over tri-state presence.
4. Rewrite `_run_intake` as patch-first, then ask — as a graph node.
5. Make unresolved budget replies return an explicit signal; the caller explains and re-asks
   with context instead of repeating.
6. Decouple `requires_stay_dates` from `hotel_pref_state.is_complete`.
7. Delete the `direct_preference_update` reachability conditions — interruption is now the
   default, so the special case is obsolete.
8. Regression-test the reported deadlock: with budget pending, send "đổi ngày đi thành 15/09"
   and assert the date changes **and** the budget question returns.

## Success Criteria

- [ ] With budget pending, a date change is applied and budget is re-asked with context
- [ ] With budget pending, an unrelated question is answered and budget is re-asked
- [ ] An unparseable budget reply produces an explanation naming the skip option, not a repeat
- [ ] The same question is never emitted twice in a row with no intervening state change
- [ ] The date picker appears without budget being answered first
- [ ] Default question ordering is unchanged from today
- [ ] `make test` green

## Risk Assessment

| Risk | Mitigation |
|---|---|
| Interruption lets users wander and never complete intake | Every turn ends by re-asking the highest-priority `UNKNOWN` required slot; the conversation cannot silently stall |
| `_run_intake` becoming a node changes streaming/`emit_phase` behavior | `emit_phase("intake_check")` moves into the node; SSE key names stay identical so the frontend is untouched |
| Removing `direct_preference_update` conditions regresses mid-hotel-list edits | That path's tests are the acceptance gate — they must pass unchanged |
| Decoupling `requires_stay_dates` changes frontend picker timing | Frontend reads the flag only; verify the picker still fires exactly once per session in an e2e run |
