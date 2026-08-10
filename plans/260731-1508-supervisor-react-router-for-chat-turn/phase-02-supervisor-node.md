---
phase: 2
title: "Supervisor node"
status: complete
priority: P1
effort: "1d"
dependencies: [1]
---

# Phase 2: Supervisor node

## Overview

Build the LLM supervisor that picks the route, plus the pure validator and the
fallback to Phase 1's `decide_route_by_rules`. Built and unit-tested in
isolation this phase; **not yet wired** into `process_chat_turn` — that is
Phase 3.

## Requirements

**Functional**
- A `create_react_agent` supervisor whose tools return only a route label (D2).
- `validate_route()` rejects routes impossible for the current `RouteContext`.
- Any LLM failure, timeout, or invalid label falls back to
  `decide_route_by_rules` (D3).
- Supervisor prompt receives session state, including whether a hotel list is
  pending and what its options are (needed for D1).

**Non-functional**
- Supervisor never receives or emits venue records, hotel IDs, or itinerary items.
- One LLM call per turn maximum; the supervisor must not loop over tools.

## Architecture

```python
# src/agents/supervisor.py  (new)

SUPERVISOR_ROUTER_PROMPT = """..."""   # Vietnamese-aware, classification only

def build_supervisor(session) -> Any:
    """create_react_agent bound to six label-only tools."""
```

**Label-only tools.** Each tool takes no arguments and returns its own name:

```python
@tool
def route_select_hotel() -> str:
    """Người dùng đang chọn khách sạn từ danh sách vừa hiển thị."""
    return "select_hotel"
```

…and equivalents for `finalize`, `new_trip`, `edit_draft`, `intake`, `chat`.
Zero-argument tools are the structural guarantee behind the non-goal "supervisor
cannot emit a fact" — there is no parameter for a destination or venue to travel
through. Do **not** add arguments to these tools.

**Validation.** The supervisor's label is a proposal, validated like every other
LLM output in this codebase:

```python
_IMPOSSIBLE = {
    "edit_draft":    lambda ctx: not ctx.has_trip_data,
    "finalize":      lambda ctx: not ctx.has_trip_data or ctx.is_trip_finalized,
    "select_hotel":  lambda ctx: not ctx.has_pending_hotel_selection,
}

def validate_route(proposed: str, context: RouteContext) -> Route | None:
    """None means unusable — caller falls back to decide_route_by_rules."""
```

**Prompt contents.** State summary only — never venue data:
destination/duration/people known so far (as booleans, not values, to keep facts
out of the router), whether a hotel list is pending and its option count and
names, whether a draft exists, whether it is finalized, whether an edit
clarification is outstanding.

**Model.** Reuse `get_llm()` from `src/services/llm.py` at `temperature=0` —
classification wants determinism, unlike the planner's `0.3` in `graph.py:41`.

**Naming.** The existing `SUPERVISOR_PROMPT` in `src/agents/prompts.py` belongs
to the *planner* agent, not this router. Do not overwrite it. Add the new prompt
under a distinct name to avoid confusion between the two "supervisors".

## Related Code Files

- Create: `src/agents/supervisor.py`
- Create: `tests/test_agents/test_supervisor.py`
- Modify: `src/agents/routing_decision.py` (add `validate_route`, `_IMPOSSIBLE`)
- Modify: `src/agents/prompts.py` (add router prompt under a new name)
- Do not modify: `src/agents/graph.py` planner agent, `src/agents/session.py`

## Implementation Steps

1. Add the six zero-argument label tools in `src/agents/supervisor.py`.
2. Write `SUPERVISOR_ROUTER_PROMPT`: Vietnamese input, one tool call, no prose,
   explicit instruction never to guess trip facts.
3. Add `build_supervisor(session)` using `create_react_agent` at
   `temperature=0`.
4. Add `decide_route_by_llm(session, user_input) -> str | None` that runs the
   supervisor and extracts the tool name actually called; returns `None` on any
   exception, timeout, or no-tool-call.
5. Add `validate_route()` and the `_IMPOSSIBLE` table to `routing_decision.py`.
6. Unit tests with a stubbed LLM — no live Ollama:
   - each of the six labels round-trips through validation
   - `edit_draft` with `has_trip_data=False` → rejected
   - `finalize` on an already-finalized trip → rejected
   - `select_hotel` with no pending list → rejected
   - LLM raises → `decide_route_by_llm` returns `None`
   - LLM returns an unknown label → rejected
   - LLM returns prose with no tool call → `None`
7. Add a test asserting every supervisor tool has an empty signature — this is
   the executable form of the "cannot emit a fact" guarantee.

## Success Criteria

- [ ] Six label-only tools, all zero-argument, enforced by a test
- [ ] `validate_route` is pure and covers all three impossible-route rules
- [ ] Stubbed-LLM tests pass without Ollama running
- [ ] LLM failure path returns `None` rather than raising
- [ ] `src/agents/graph.py` and `src/agents/session.py` have zero diff this phase
- [ ] Planner's existing `SUPERVISOR_PROMPT` is untouched

## Risk Assessment

**Risk (R1 from plan.md):** D1 removes the deterministic pre-gate on a pending
hotel list, so a supervisor misread can bypass the hotel-pick gate.
**Mitigation:** `validate_route` rejects `select_hotel` when no list is pending,
and the prompt states the pending list verbatim. This constrains the *false
positive* direction. The *false negative* — supervisor routing away from a
genuinely pending list — is exactly the behavior D1 asked for (it is how a user
escapes the trap documented at `session.py:470-477`), so it is not rejected
here. Phase 4 measures how often it happens.

**Risk:** `create_react_agent` may loop, calling several label tools in one turn.
**Mitigation:** Take the **first** tool call and stop consuming the stream.
Prompt forbids multiple calls. Test asserts single-label extraction when the
stub emits two.

**Risk:** A local `llama3.1` may be weak at six-way Vietnamese classification.
**Mitigation:** Phase 4 measures accuracy against the harness scenarios. If it
underperforms the regex layer, D2's cheaper structured-call variant or a reduced
route set is the fallback — report to the user rather than quietly widening the
prompt.

**Rollback:** Phase is additive; nothing calls the new module until Phase 3.
