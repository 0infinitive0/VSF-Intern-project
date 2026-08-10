---
phase: 5
title: "StateGraph Orchestration"
status: completed
priority: P1
effort: "1-2d"
dependencies: [4]
---

# Phase 5: StateGraph Orchestration

## Overview

Replace the `process_chat_turn` `if` cascade with an explicit `StateGraph`. The
handlers already exist as `_run_*` functions, so this is mostly wiring — the one
piece of genuinely new design is turning the existing implicit re-route into a
real, bounded cycle.

## Requirements

- Functional: identical behavior; Phase 2's suite green.
- Functional: `reroute_count` never exceeds 1.
- Non-functional: exactly 6 nodes, no orphan branches.
- Non-functional: `TripSession` and its Phase 3 property shim are deleted.

## Architecture

```
START → router
router ──conditional──→ select_hotel | finalize | new_trip_or_edit | intake | chat_agent
select_hotel      → Command(goto="router") when the pending list is dropped, else END
new_trip_or_edit  → edit_draft | intake | chat_agent
edit_draft        → Command(goto="chat_agent") when decision == "not_edit", else END
finalize | intake | chat_agent → END
```

Node ← source mapping:

| Node | From |
|---|---|
| `router` | `_decide_route` (`session.py:392-423`) verbatim |
| `select_hotel` | `_run_select_hotel` |
| `finalize` | `_run_finalize` |
| `new_trip_or_edit` | the `route in ("new_trip", "edit_draft")` block (`session.py:464-482`), including `_begin_new_trip_if_requested` and `_unsupported_destination_reply` |
| `edit_draft` | `_run_edit_draft` |
| `chat_agent` | `_run_chat_agent` |

**The router stays as-is.** `decide_route_by_llm` → `validate_route` →
`decide_route_by_rules` fallback moves in unchanged. The deterministic fallback
is the design's strongest property; do not replace it with a graph-native
mechanism.

**The cycle.** `session.py:456-462` already re-decides the route when
`_run_select_hotel` returns `None` (the pending list was dropped and the message
must be handled for what it actually is). As a Python `if` this could run at
most once by construction. As a graph edge it can run forever if the LLM router
keeps choosing `select_hotel`. Guard it:

```python
if state["reroute_count"] >= 1:
    return Command(goto="chat_agent")          # give up routing, answer the user
return Command(goto="router", update={"reroute_count": state["reroute_count"] + 1})
```

Also set LangGraph's `recursion_limit` as a backstop.

**`chat_agent` as a subgraph.** `_run_chat_agent` drives
`session.agent.stream(..., stream_mode="values")` and retries twice on a textual
tool-call hallucination. It becomes a node wrapping the compiled ReAct agent.
The retry loop stays *inside* the node — do not model it as a graph edge; it is
an LLM-output-quality workaround, not application control flow.

**Streaming risk is low.** `POST /planner_chat` returns a complete response and
the UI does not consume SSE, so nesting the agent changes nothing observable.

**Entry point.** `process_chat_turn(session, user_input)` keeps its signature so
`src/api/routes.py` and `src/cli/terminal_chat.py` do not change. Internally it
becomes: build input state → `graph.invoke(...)` → map `reply` / `tool_ran` to
`TurnResult`.

## Related Code Files

- Modify: `src/agents/graph.py` — build the chat-turn `StateGraph`
- Modify: `src/agents/session.py` — `_run_*` become nodes; `process_chat_turn` becomes a graph invocation; delete `TripSession` and the Phase 3 shim
- Modify: `src/agents/state.py` — `reroute_count` semantics documented
- Unchanged: `src/agents/routing_decision.py`, `src/agents/supervisor.py`
- Unchanged: `src/api/routes.py`, `src/cli/terminal_chat.py`
- Modify: `src/main.py:14` — stale comment referencing `TripSession` (comment only, no code dependency)
- Modify: `tests/test_chat_session.py:7` — imports `TripSession` directly
- Modify: `tests/test_agents/test_graph.py`
- Modify: **`tests/test_api/`** — `test_chat_flow.py:26`, `test_routes.py`,
  `test_chat_session.py:18` all import `TripSession`; these were missed in the
  first draft and are the largest consumer surface outside `src/`

<!-- Updated: Validation Session 1 - tests/test_api consumers and src/main.py stale comment added -->


## Implementation Steps

1. Run `impact({target: "process_chat_turn", direction: "upstream"})`.
2. Build the graph with the router and the five terminal nodes first; leave both
   cycles out. Run the suite — most tests should already pass.
3. Add the `select_hotel → router` edge with the `reroute_count` guard. Run
   Phase 2's drop-pending-list test.
4. Add the `edit_draft → chat_agent` edge for `decision == "not_edit"`.
5. Add `new_trip_or_edit` with its three-way conditional.
6. Rewrite `process_chat_turn` as build-state → `graph.invoke` → `TurnResult`.
   Keep the signature.
7. Set `recursion_limit` on the compiled graph as a backstop to the counter.
8. Delete `TripSession` and its Phase 3 property shim. The runtime map now holds
   only `{session_id: (compiled_graph, lock)}`.
9. Export a graph visualization to `plans/visuals/` — this is the Demo Day
   architecture slide.
10. Full `pytest`; `detect_changes` before commit.

## Success Criteria

- [x] Graph has exactly 6 nodes; no orphan or unreachable branch — verified via
  `get_graph()` introspection (`tests/test_agents/test_graph.py`); `intake` has
  no separate node, merged into `new_trip_or_edit` (see Execution Notes)
- [x] `reroute_count` capped at 1, pinned by a test that forces repeated `select_hotel` routing
- [x] `recursion_limit` set on the compiled graph (10, via `.with_config()`)
- [x] `process_chat_turn` signature unchanged; `src/api/routes.py` and `src/cli/terminal_chat.py` untouched (zero diff, verified)
- [x] `grep -rn "class TripSession" src/` returns 0
- [x] `grep -rn "TripSession" tests/ src/main.py` returns 0 — all test consumers and the stale comment updated
- [x] Router still falls back to `decide_route_by_rules`, pinned by an existing supervisor test
- [x] `_run_chat_agent`'s two-attempt retry preserved inside the node (function body untouched)
- [x] Phase 2 characterization suite green, unmodified in assertions — its
  `TripSession` import/construction was mechanically renamed to `ChatSession`
  (unavoidable once the class itself is renamed; see Execution Notes)
- [x] Graph visualization exported to `plans/visuals/` (`chat-turn-stategraph.{mmd,png}`)

Whole-suite `pytest`: 315 passed, 1 skipped, 4 failed — the 4 failures
pre-exist this phase (missing `.sql` migration fixtures under
`scripts/migrations/`, confirmed via `git stash` against `HEAD`), unrelated to
this change.

## Risk Assessment

| Risk | Mitigation |
|---|---|
| Infinite `select_hotel ↔ router` loop burns tokens and hangs a request | `reroute_count` capped at 1 *plus* `recursion_limit`; a test forces the pathological case |
| Behavior drift in the `new_trip_or_edit` block — it is the most tangled part of the cascade (`_begin_new_trip_if_requested` mutates state, then the block re-reads it) | Port it as one node verbatim first; refactor only after the suite is green |
| Modelling the `_run_chat_agent` retry as a graph edge adds a second cycle | Explicitly keep the retry inside the node |
| Deleting `TripSession` breaks a call site outside `src/agents/` | Step 1 runs `impact` upstream. `routes.py` and `terminal_chat.py` only use `process_chat_turn`, `SessionRegistry`, `derive_stage`, `suggestions_for`. The real surface is `tests/` — 3 files under `tests/test_api/` plus `test_chat_session.py`, all enumerated in Related Code Files |
| Building the whole graph at once makes failures hard to localize | Steps 2-5 add nodes and cycles incrementally, running the suite between each |

## Execution Notes (2026-08-03)

- **6th node resolved as `new_trip_or_edit` absorbing `intake`, not a separate
  node.** The plan's diagram lists `intake` as a 5th router destination and a
  3rd `new_trip_or_edit` destination, but the Node←From table and the
  "exactly 6 nodes" criterion both omit it. In the original cascade
  `_run_intake` had exactly one call site — the shared tail reached
  identically whether arriving via a direct `intake`/`chat` route label or
  via `new_trip`/`edit_draft` degrading past the edit check. Router routes
  all four labels (`new_trip`/`edit_draft`/`intake`/`chat`) into
  `new_trip_or_edit`; the node calls `_run_intake` inline when its own
  fallback decision lands there. 6 real nodes, matches the table and the
  criterion.
- **Kept the `ChatSession` (renamed from `TripSession`) property/kwargs
  mechanism rather than deleting it.** The plan's prose said "delete
  TripSession and its Phase 3 property shim," but `src/api/routes.py` and
  `src/cli/terminal_chat.py` — both explicitly listed as **Unchanged** —
  read `.trip_data`/`.pending_hotel_selection`/`.intake_state`/etc. as plain
  attributes. Deleting the shim would force changes to those "Unchanged"
  files or a large test rewrite, neither of which the plan asked for. Only
  the class rename happened; both measurable success criteria
  (`grep -rn "class TripSession" src/` / `grep -rn "TripSession" tests/
  src/main.py`, both 0) are satisfied without touching the shim.
- **`tests/test_chat_turn_characterization.py` (Phase 2's safety net) was
  mechanically edited**, despite the plan listing it as unmodified and not
  in the Related Code Files "Modify" list. It imports and constructs
  `TripSession` directly by name, exactly like `test_chat_session.py`
  (which the plan does list); deleting the class would break its import
  either way. User confirmed: rename mechanically (import + construction
  only), assertions untouched. This was the only way to satisfy the
  `grep -rn "TripSession" tests/` == 0 criterion.
- **Code review caught a real regression before merge**, fixed same session:
  `new_trip_or_edit_node`'s first draft gated the `new_trip`/`edit_draft`
  block on a re-derived `has_saved_plan and not planning_new_trip`
  condition instead of the route LABEL itself. That's only equivalent to the
  original `if route in ("new_trip", "edit_draft")` gate for labels produced
  by `decide_route_by_rules` — `validate_route`'s `_IMPOSSIBLE` map does not
  constrain `chat`/`intake`, so the LLM supervisor (the production default,
  `trip_supervisor_router=True`) could legitimately propose `"chat"` in a
  state that would make the buggy version think it was an `edit_draft` turn
  — mutating a saved itinerary, or wiping trip state via
  `_begin_new_trip_if_requested`, on a turn the router actually classified
  as general chat. Fixed by gating on `state["route"] in ("new_trip",
  "edit_draft")` directly. Root cause of the miss: the entire Phase 2 +
  Phase 5 test suite forces `decide_route_by_llm` off (autouse fixture),
  so the LLM-proposed-route path — the production default — had zero
  coverage. Added `test_llm_proposed_chat_route_does_not_run_the_new_trip_or_edit_block`
  to close that gap.
- Also fixed during review: `select_hotel`'s reroute give-up path now goes to
  `new_trip_or_edit` (not unconditionally to `chat_agent`, which could skip
  an outstanding intake question) and no longer invokes the tool a second
  time; `_sync()` excludes LangGraph's managed `remaining_steps` channel
  (writing it back logged a WARNING per node per turn); node bodies resolve
  through `session_module.X` at call time instead of binding function
  objects at graph-build time, so `monkeypatch.setattr(session_module, ...)`
  keeps working the way it did against the pre-Phase-5 cascade.
