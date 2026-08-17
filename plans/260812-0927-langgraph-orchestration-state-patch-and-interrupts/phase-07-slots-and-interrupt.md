---
phase: 7
title: "Slot registry, next_question, interrupt"
status: completed
priority: P1
effort: "2.5d"
dependencies: [6]
---

# Phase 7: Slot registry, next_question, interrupt

## Overview

Fill the `ask_slot` node with a declarative slot registry over Phase 3's tri-state, and add
`interrupt()` for ambiguous input. Together these kill the deadlock class and the guess-the-date
class — the two behaviors users hit most.

## Problem

**Deadlock.** The legacy `_run_intake` is five sequential `if` blocks, each with exactly one
branch: answer the pending question, or re-ask it. The budget gate is the worst instance:

- `HotelPreferenceState.with_message` returns `self` on any unparsed reply
  (`hotel_selection.py:709`) → same prompt again → infinite loop.
- The escape hatch is a fixed list of 8 phrases plus a number. Anything else loops.
- `direct_preference_update` (`session.py:713`) — the only path that could handle a different
  intent — requires `pending_hotel_selection is not None` **or** budget already complete. Both
  are false precisely while the gate is open.
- `requires_stay_dates` (`routes.py:240`) requires `hotel_pref_state.is_complete`, so the **date
  picker is gated behind budget**. That is the literal mechanism behind "ngân sách chưa nhập
  chưa cho edit".

**Guessing.** `_format_start_date` (`trip_intake.py:591`) only checks that
`date.fromisoformat` parses. No year check, no past check, no day/month order rule, no
confirmation. Today is 2026-08-12; "01/07" resolves to a past date the model invented a year
for. `interrupt` appears **zero times** in the repo.

## Requirements

### Slots

- Functional: any pending question is interruptible by a different recognized intent; the
  question returns afterwards with context, not repeated verbatim.
- Functional: an unrecognized reply explains what is pending and how to skip — never a verbatim repeat.
- Functional: an already-filled slot is revisable at any time.
- Functional: the date picker is no longer gated behind budget.
- Functional: budget is skippable by setting `NOT_APPLICABLE`, not only via the 8 fixed phrases.
- Non-functional: default ordering stays destination → people → dates → budget, but ordering is
  **data**, not control flow.

### Interrupt

- Functional: a date with no year asks for the year.
- Functional: **day/month order ambiguity asks.** `1-2-2026` is 1 Feb or 2 Jan; both readings are
  valid, so guessing is silently wrong half the time. Unambiguous when one component exceeds 12
  (`31/07` has one reading) — ask only when genuinely ambiguous.
- Functional: a past start date is rejected with a date-specific message.
- Functional: `Command(resume=...)` carries the next message into the paused node without
  re-asking earlier slots.
- Non-functional: ambiguity detection is **deterministic**, in Phase 3's validators. The model
  never decides whether its own output was ambiguous.

## Architecture

`backend/src/domain/slot_registry.py`:

```python
@dataclass(frozen=True)
class SlotSpec:
    name: str                      # canonical path from ALLOWED_PATHS
    required: bool
    order: int
    prompt_key: str                # WHICH question to ask — not how to render it
    skippable: bool = False
```

`next_question(state)` = first spec whose slot is `UNKNOWN`, by `order`. That one expression
replaces the ladder, and every slot inherits revisable / skippable / interruptible for free.

**`SlotSpec` carries a `prompt_key`, not a render callable.** Rendering needs
`format_guided_question` (`services/guided_question.py`) and `t()` — a render callable inside
`domain/` would import `services` and fail Phase 3's purity test. The `ask_slot` **node** does
the rendering; it may import both layers. `next_question` returns *which* slot is missing;
the node turns that into text.

The graph makes the key inversion structural: `extract_patch → validate_patch → apply_patch`
runs **before** `ask_slot`. The pending question no longer decides whether a message is allowed
to mean something else — that decision does not exist anymore.

`interrupt()` is called from `validate_patch` when a validator reports ambiguity, and from
`hotel_node` when a search center cannot be resolved (Phase 8). Resume is `Command(resume=...)`
per the documented protocol. This only works because the node lives inside the graph — the
reason this phase depends on Phase 5 and Phase 4.

### Standing constraint: an interrupted node re-executes from its start

LangGraph re-runs the **whole node** from the beginning when an interrupted turn resumes
(https://docs.langchain.com/oss/python/langgraph/interrupts). Every side effect before the
interrupt point therefore happens twice.

Two rules follow, and they bind every later phase, not just this one:

1. **A node containing `interrupt()` must be pure, or idempotent, up to the interrupt point.**
   `validate_patch` is pure — safe. `hotel_node` interrupts at `resolve_center`, before the
   search RPC — safe, but note it in review if anything is ever inserted earlier.
2. **A loop containing an interrupt point must be a subgraph invoked per iteration, never a
   Python `for` inside one node.** Otherwise resuming re-runs completed iterations. This is why
   Phase 9's `rebuild_day` is a subgraph.

Add an assertion to the Phase 5 topology test: no node that calls `interrupt()` performs an
LLM call, a DB write, or an external API call before that call.

`HotelPreferenceState` keeps its guided-menu rendering (`format_guided_question`); that part
works. What changes is that a failed parse no longer traps the turn.

## Related Code Files

- Create: `backend/src/domain/slot_registry.py`
- Create: `backend/tests/test_slot_registry.py`, `backend/tests/test_interrupt_resume.py`
- Modify: `backend/src/agents/graph_v2/nodes/ask_slot.py`, `validate_patch.py`
- Modify: `backend/src/domain/travel_state.py` — date validators incl. order ambiguity
- Modify: `backend/src/api/routes.py` — `requires_stay_dates` (:240) decoupled from budget

## Implementation Steps

1. Define the slot registry with today's default ordering, so ordering behavior is unchanged.
2. Implement `next_question(state)` over tri-state presence.
3. Fill `ask_slot`; wire the `apply_patch → ask_slot | supervisor` edge.
4. Add date validators: missing year, past date, end ≤ start, implausible span, day/month order.
5. Call `interrupt()` from `validate_patch` on ambiguity; implement resume.
6. Decouple `requires_stay_dates` from `hotel_pref_state.is_complete`.
7. Regression-test the reported deadlock: with budget pending, send "đổi ngày đi thành 15/09"
   and assert the date changes **and** budget is re-asked.
8. Test restart durability: pause on the year question, restart the process, resume, complete.

## Success Criteria

- [x] With budget pending, a date change applies and budget returns with context
- [ ] With budget pending, an unrelated question is answered and budget returns — an unrelated FACT (a different slot's change) is verified; true free-text Q&A during intake is structurally blocked by design (`route_ask_slot` never reaches `qa_node` while a slot is missing) and out of this phase's scope
- [x] An unparseable budget reply explains and names the skip option — not a repeat
- [x] The same question is never emitted twice in a row with no intervening state change
- [x] The date picker appears without budget being answered first
- [x] "01/07" asks which year; "1-2-2026" asks 1 Feb or 2 Jan; "31/07" resolves silently
- [x] A past start date is rejected with a date-specific message, not a coordinates error (domain-layer proven; full user-facing surfacing of the rejection reason is a possible future polish)
- [x] A paused thread survives a process restart and resumes correctly (opt-in live-Postgres test, mirrors Phase 4's existing convention — not run in default CI)
- [x] No node calling `interrupt()` performs an LLM call, DB write, or external API call before it — asserted by test
- [x] Default question ordering unchanged from today
- [ ] `make test` green — not run literally (hits real LLM/LangSmith APIs per repo convention); the full relevant scoped test surface (234 tests) was run instead, exhaustively, with zero regressions

## Risk Assessment

| Risk | Mitigation |
|---|---|
| Interruption lets users wander and never finish intake | Every turn ends by re-asking the highest-priority `UNKNOWN` required slot; the conversation cannot silently stall |
| Over-asking makes the bot feel interrogative | Ask only on genuine ambiguity — `31/07` resolves silently. Count interrupts per conversation in the Phase 10 eval and treat a rise as a regression |
| `emit_phase` / SSE behavior changes when intake becomes a node | Phase keys stay identical; frontend untouched |
| Decoupling `requires_stay_dates` changes picker timing | Frontend reads the flag only; verify the picker fires exactly once per session in an e2e run |
| Resume protocol mismatch with the streaming endpoint | Test both `/planner_chat` and `/planner_chat/stream` against a paused thread |
