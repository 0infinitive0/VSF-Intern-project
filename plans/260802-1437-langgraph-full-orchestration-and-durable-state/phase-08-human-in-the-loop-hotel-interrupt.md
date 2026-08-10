---
phase: 8
title: "Human In The Loop Hotel Interrupt"
status: deferred
priority: P3
effort: "1d"
dependencies: [7]
---

# Phase 8: Human In The Loop Hotel Interrupt

> **DEFERRED — out of scope for this delivery** (validation session 1,
> 2026-08-02). Depends on Phase 7, which is itself deferred. Kept as designed
> work for after Demo Day.

<!-- Updated: Validation Session 1 - deferred out of scope -->

## Overview

Turn the hotel pick into a real LangGraph `interrupt()` — the graph pauses at a
checkpoint, the user answers, the graph resumes from exactly where it stopped.

Optional and last for a reason: it is the only phase that changes user-visible
behavior, and its value is demonstrative rather than functional. **Attempt only
if Phase 7 landed with calendar to spare.**

## Requirements

- Functional: the user-facing hotel-pick conversation is unchanged in wording and
  options.
- Functional: an interrupted turn resumes correctly after a process restart.
- Non-functional: the Phase 2 gate invariant still holds.

## Architecture

Today the pause is emulated: `recommend_hotels` writes
`pending_hotel_selection`, the turn ends, and the *next* turn's router sees the
pending flag and routes to `select_hotel`. State carries the pause across two
independent invocations.

With `interrupt()` the graph itself is suspended mid-run. The checkpoint records
the exact resume point; `Command(resume=...)` continues from there. Combined with
Phase 7's `PostgresSaver`, a paused conversation survives a restart at the pause
point — the thing that is genuinely hard to build without a graph framework, and
the honest answer to "why LangGraph?".

**Why this ordering.** `interrupt()` without a durable checkpointer is strictly
worse than the current flag: a restart loses the suspended run entirely. It must
follow Phase 7.

**Keep the gate.** Phase 4's explicit `pending_hotel_selection` precondition
stays. `interrupt()` changes *how* the pause is represented, not whether an
itinerary can be built without a hotel. Do not remove the check on the grounds
that the graph now enforces ordering.

**Scope discipline.** Convert the hotel pick only. Intake questions and edit
clarification look similar but are cheap already and add risk for no demo value.

## Related Code Files

- Modify: `src/agents/tools/recommend_hotels.py` — `interrupt()` instead of setting the pending flag
- Modify: `src/agents/graph.py` — resume handling
- Modify: `src/agents/session.py` — `process_chat_turn` detects a suspended thread and resumes with `Command(resume=...)` instead of a fresh invoke
- Modify: `src/agents/routing_decision.py` — the `select_hotel` route may become unreachable; delete it only if provably dead, otherwise leave it
- Create: `tests/test_hotel_interrupt_resume.py`
- Modify: `docs/architecture/chat-turn-graph.md`

## Implementation Steps

1. Confirm Phase 7 is complete and stable in the deployed environment. Do not
   start otherwise.
2. Branch separately so this is revertible without touching phases 1-7.
3. Replace the pending-flag write in `recommend_hotels` with `interrupt()`,
   carrying the same hotel options payload.
4. In `process_chat_turn`, check for a suspended thread first; resume with
   `Command(resume=user_input)` instead of invoking fresh.
5. Keep the explicit gate precondition in every itinerary-touching tool.
6. Decide the fate of the `select_hotel` route: if the router can still be
   reached with a pending pick, keep it; if provably unreachable, remove it from
   `Route` and `_IMPOSSIBLE` together.
7. Write the resume test, including resume-after-restart against Postgres.
8. Re-run Phase 2's characterization suite. The drop-pending-list case is the
   one most likely to change — a user who abandons the pick must not be trapped
   in a suspended graph.
9. Manual UI smoke on the full flow.
10. Update the architecture doc and diagram.

## Success Criteria

- [ ] Hotel pick suspends via `interrupt()` and resumes via `Command(resume=...)`
- [ ] Restart during a suspended pick, then resume successfully
- [ ] Abandoning the pick ("chốt lịch trình" while options are showing) still works — the user is not trapped
- [ ] Phase 2 gate invariant still passes
- [ ] Explicit `pending_hotel_selection` precondition retained in tools
- [ ] Hotel-pick wording and options unchanged for the user
- [ ] `select_hotel` route either retained with justification or removed from `Route` and `_IMPOSSIBLE` together
- [ ] Architecture doc and diagram updated
- [ ] Revertible as a single branch

## Risk Assessment

| Risk | Mitigation |
|---|---|
| The user abandons the pick and is trapped in a suspended graph — a regression of the exact bug `_is_hotel_choice_attempt` was written to fix (see `routing_decision.py` comments) | Step 8 re-runs the drop-pending-list characterization test; it has its own success criterion |
| The gate is dropped because "the graph enforces ordering now" | Explicitly forbidden in the architecture note and pinned by the retained criterion |
| `Route`/`_IMPOSSIBLE` left half-updated, so `validate_route` rejects a valid label | Step 6 requires both to change together or neither |
| Scope creep into intake and edit-clarification interrupts | Non-goal stated in the architecture section |
| Phase 8 destabilizes a working Phase 7 build close to Demo Day | Separate branch, revertible in one operation; gated on Phase 7 being stable in deployment |
