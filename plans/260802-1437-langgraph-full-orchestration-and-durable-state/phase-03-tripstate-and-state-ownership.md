---
phase: 3
title: "TripState And State Ownership"
status: completed
priority: P1
effort: "2-3d"
dependencies: [2]
---

# Phase 3: TripState And State Ownership

## Overview

Split `TripSession` into a **serializable** `TripState` (everything a
checkpointer must own) and a **process-local runtime** (compiled agent, tools,
lock, persist hook — all rebuildable). This is the phase the whole plan exists
for; phases 4, 5, and 7 are consequences of it.

## Requirements

- Functional: behavior unchanged; Phase 2's characterization suite stays green
  throughout.
- Non-functional: `TripState` round-trips through `json.dumps` / `json.loads`
  with no custom encoder.
- Non-functional: no non-serializable object (compiled graph, `BaseTool`,
  `Callable`, `threading.Lock`) appears in `TripState`.

## Architecture

Current `TripSession` (`src/agents/session.py:100-126`) mixes both kinds of
field:

| Field | Destination |
|---|---|
| `intake_state`, `hotel_pref_state`, `trip_data`, `pending_hotel_selection`, `initial_plan_complete`, `planning_new_trip`, `pending_trip_edit_request` | `TripState` |
| `agent`, `tools`, `persist_hook`, `lock` | runtime |
| `session_id` | both (`thread_id` in graph config; key in the runtime map) |
| `created_at`, `last_seen_at` | runtime for now; the checkpointer owns timestamps from Phase 7 |
| `config` | runtime — it is just `{"configurable": {"thread_id": session_id}}` |

Target schema:

```python
class TripState(TypedDict):
    messages: Annotated[list, add_messages]
    intake: dict                        # TripIntakeState -> asdict
    hotel_prefs: dict                   # HotelPreferenceState -> asdict
    trip_data: dict | None
    pending_hotel_selection: dict | None
    initial_plan_complete: bool
    planning_new_trip: bool
    pending_trip_edit_request: str | None
    route: str | None                   # written by the router node (Phase 5)
    reroute_count: int                  # loop guard (Phase 5)
    reply: str                          # what the HTTP layer returns
    tool_ran: str | None                # feeds derive_stage
```

`reply` and `tool_ran` replace `TurnResult`'s two fields, so `derive_stage` and
`_STAGE_MAP` carry over unchanged.

**Serialization.** Verified: `TripIntakeState` is `str | None` ×3 plus
`tuple[str, ...]`; `HotelPreferenceState` is a `Literal` stage plus three
`float | None`. Both are fully primitive. The single wrinkle is
`TripIntakeState.preferences`: `asdict` yields a `tuple`, JSON yields a `list`,
and `replace()`-based code expects a `tuple`. Coerce in `from_dict`.

Give each dataclass an explicit `to_dict()` / `from_dict()` rather than calling
`asdict` at call sites — one place to fix when a field is added.

**Routing.** `route_context_from_session(session)`
(`src/agents/routing_decision.py:50`) reads exactly the 8 booleans now in
`TripState`. Rename to `route_context_from_state(state)` and change the field
reads. `RouteContext` itself is untouched. `decide_route_by_rules` and
`validate_route` are pure and need no change at all.

Complete consumer list (verified 2026-08-02) — **3 production call sites, not 2**:

| File:line | Kind |
|---|---|
| `src/agents/session.py:31` | import |
| `src/agents/session.py:436` | call — initial route decision |
| `src/agents/session.py:445` | call — re-decision after a dropped hotel list |
| `src/agents/supervisor.py:24` | import |
| `src/agents/supervisor.py:88` | call |
| `tests/test_agents/test_supervisor_routing_accuracy.py:22` | import |
| `tests/test_agents/test_supervisor_routing_accuracy.py:146` | call |
| `tests/test_agents/test_supervisor.py:79` | docstring reference only |

This phase keeps `TripSession` alive as a thin adapter so nothing else breaks
yet; Phase 5 removes it.

## Related Code Files

- Modify: `src/agents/state.py` — add `TripState`
- Modify: `src/services/trip_intake.py` — add `TripIntakeState.to_dict` / `from_dict`
- Modify: `src/services/hotel_selection.py` — add `HotelPreferenceState.to_dict` / `from_dict`
- Modify: `src/agents/routing_decision.py` — `route_context_from_session` → `route_context_from_state`
- Modify: `src/agents/session.py` — `TripSession` becomes a runtime holder wrapping a `TripState` dict
- Modify: `src/agents/supervisor.py` — `route_context_from_session` call site
- Modify: `tests/test_routing.py`, `tests/test_agents/test_supervisor*.py` — construct state dicts

## Implementation Steps

1. `findReferences` on `route_context_from_session` before renaming; per
   `CLAUDE.md`, use `rename` rather than find-and-replace.
2. Add `to_dict` / `from_dict` to both state dataclasses. Coerce `preferences`
   back to `tuple` in `from_dict`. Phase 2's round-trip test must pass.
3. Define `TripState` in `src/agents/state.py`.
4. Add `initial_state(session_id) -> TripState` producing the documented defaults
   (`reroute_count: 0`, `route: None`, empty intake/prefs).
5. Change `TripSession` to hold `state: TripState` plus the runtime fields, with
   temporary properties (`session.trip_data` → `session.state["trip_data"]`) so
   existing call sites keep working during the transition.
6. Rename `route_context_from_session` → `route_context_from_state`; read from
   the state dict. Update **all 3 production call sites** (`session.py:436`,
   `session.py:445`, `supervisor.py:88`) plus both imports and the two test
   consumers listed above. `session.py` has two calls, not one — the second is
   the re-decision after a dropped hotel list.
7. Run the full suite. Any failure here is a real behavior change — fix the code,
   never the characterization test.
8. Assert serializability in a test: `json.loads(json.dumps(state))` equals the
   original for a fully-populated state including a finalized `trip_data`.

## Success Criteria

- [ ] `TripState` defined and JSON round-trips with no custom encoder
- [ ] `TripIntakeState` / `HotelPreferenceState` have `to_dict` / `from_dict`; `preferences` returns as `tuple`
- [ ] `route_context_from_state` reads only the state dict; `RouteContext` unchanged
- [ ] `grep -rn "route_context_from_session" . ` returns 0 — all 3 production call sites and both test consumers updated
- [ ] `decide_route_by_rules` and `validate_route` unchanged
- [ ] No `Callable`, `BaseTool`, compiled graph, or `Lock` reachable from `TripState`
- [ ] Phase 2 characterization suite green, unmodified
- [ ] Full `pytest` green

## Risk Assessment

| Risk | Mitigation |
|---|---|
| `preferences` silently becomes a `list` and `replace()`-based intake logic misbehaves | Explicit `tuple` coercion in `from_dict`, pinned by Phase 2's round-trip test |
| `trip_data` contains a non-JSON value (datetime, Decimal) from Supabase | Step 8 asserts round-trip on a *fully populated finalized* trip, not an empty one |
| The temporary `TripSession` property shim is left in permanently | Phase 5 success criteria explicitly require its removal |
| A field is added to a state dataclass later and forgotten in `to_dict` | `to_dict` / `from_dict` live next to the dataclass; round-trip test covers all fields |
| Renaming `route_context_from_session` breaks an unseen call site | Use LSP `findReferences` + GitNexus `rename`, per `CLAUDE.md` — not find-and-replace |

## Execution Notes (2026-08-02)

- GitNexus MCP `rename` tool unavailable this session (see Phase 1 notes —
  MCP server not registered even though the CLI index exists). Used LSP
  `findReferences` instead, which returned exactly 8 references across 4
  files — matching the plan's verified consumer list exactly (3 production
  call sites + definition + 2 imports + 2 test consumers). Manual edits at
  each site, verified clean by re-grepping afterward.
- **Found a transitive impact LSP's reference search correctly couldn't
  flag**: `tests/test_agents/test_supervisor.py`'s `_FakeSession` and
  `test_supervisor_routing_accuracy.py`'s `_FakeSession` never call
  `route_context_from_session` by name — `decide_route_by_llm` calls it
  internally via `_state_summary`. Since `_state_summary` now does
  `route_context_from_state(session.state)`, both fakes needed a new
  `.state` property translating their legacy attributes into a TripState-
  shaped dict. Caught by actually running `test_supervisor.py` (5 real,
  non-skipped tests construct `_FakeSession` and call `decide_route_by_llm`
  directly) rather than trusting the plan's line-level audit alone.
- `TripSession` became a hand-rolled class instead of staying a
  `@dataclass`: a `@dataclass`'s generated `__init__` can't simultaneously
  declare a field AND have that name be a `@property` — and the seven
  business-fact names need to be properties (proxying into `self.state`)
  while still being accepted as constructor kwargs (every existing test's
  `TripSession(trip_data=..., intake_state=..., ...)` call pattern). Used
  `None`-as-unset sentinels for the boolean kwargs so an explicit
  `initial_plan_complete=False` isn't silently indistinguishable from "not
  passed."
- Verified no `dataclasses.replace/asdict/fields` calls existed anywhere
  against `TripSession` before dropping `@dataclass` — would have broken
  silently otherwise.
- Full suite: 426 passed (was 423 after Phase 2; +3 new serialization
  tests), same 12 pre-existing failures, run twice with no flake. Phase 2's
  characterization suite (`tests/test_chat_turn_characterization.py`,
  `tests/test_hotel_flow_tools.py`) confirmed byte-unmodified via
  `git diff --stat` and still green.
- New file `tests/test_agents/test_state_serialization.py`: JSON round-trip
  on a fully-populated *finalized* `TripState` (not an empty one, per the
  plan's own risk note), a round-trip through the embedded
  `TripIntakeState`/`HotelPreferenceState` dataclasses specifically, and a
  static schema check (`typing.get_type_hints`) that no `TripState` field
  annotation references `Callable`/`BaseTool`/`Lock`/`StateGraph`.
- Ruff: introduced exactly 1 new issue (an unnecessary quoted forward-ref
  in `HotelPreferenceState.from_dict`'s return annotation, since the file
  already has `from __future__ import annotations`) — fixed. Confirmed via
  before/after error-count diff against a `git stash`, not assumed.
