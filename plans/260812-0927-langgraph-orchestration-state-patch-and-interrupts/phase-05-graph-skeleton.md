---
phase: 5
title: "Graph skeleton behind a flag"
status: pending
priority: P1
effort: "3d"
dependencies: [3, 4]
---

# Phase 5: Graph skeleton behind a flag

## Overview

Build the single control plane as a real `StateGraph` — every node, every edge — running behind
`orchestrator=graph|legacy`. Nodes are thin or stubbed here; Phases 6-9 fill them. This is the
phase that makes "one plane" a structure rather than an intention.

## Why a skeleton first

The alternative — grow the graph node by node while the cascade still routes — is how the two
planes appeared in the first place. Building the whole shape first means every later phase fills
a node whose contract is already fixed by an edge, and the flag makes the whole thing revertible
until Phase 11.

## Requirements

- Functional: `orchestrator=graph` processes a turn end to end through the graph and returns a
  `PlannerChatResponse` indistinguishable in **shape** from the legacy plane.
- Functional: `orchestrator=legacy` (default in this phase) behaves byte-identically to today.
- Functional: every node exists and is wired, even when its body is a pass-through.
- Functional: routing is expressed **only** as graph edges. No node inspects a message to decide
  where the turn goes next.
- Non-functional: `PlannerChatResponse` field shape is frozen for the whole plan — the frontend
  must not change until after Phase 11.
- Non-functional: the legacy plane is **frozen** from this phase on. No edits except reverts.

## Architecture

`backend/src/agents/graph_v2/` — a new package, so the legacy `graph.py` stays untouched and
deletion in Phase 11 is a directory removal rather than surgery.

```python
builder = StateGraph(TravelGraphState)
builder.add_node("load_context",   load_context)
builder.add_node("scope_guard",    scope_guard)      # Phase 2, already built
builder.add_node("extract_patch",  extract_patch)    # Phase 6
builder.add_node("validate_patch", validate_patch)   # Phase 3 validators
builder.add_node("apply_patch",    apply_patch)      # Phase 3
builder.add_node("ask_slot",       ask_slot)         # Phase 7
builder.add_node("detect_impact",  detect_impact)    # Phase 3 IMPACT_MAP
builder.add_node("hotel_flow",     hotel_flow)       # Phase 8
builder.add_node("itinerary_flow", itinerary_flow)   # Phase 9
builder.add_node("general_qa",     general_qa)       # ReAct agent as a LEAF
builder.add_node("respond",        respond)
```

Conditional edges carry all routing: `scope_guard → refuse|continue`,
`validate_patch → interrupt|clarify|apply`, `apply_patch → ask_slot|detect_impact`,
`detect_impact → hotel|itinerary|general_qa|none`.

### There is no planner node — routing is a table lookup

`extract_patch` proposes `{intent, changes[]}`; `detect_impact` decides which flow runs by
reading `IMPACT_MAP` (a plain dict, Phase 3). **The LLM proposes state changes; deterministic
code decides what executes.** That is doc §2's core principle, and the direct fix for today's
`_decide_route` letting a supervisor LLM pick a route that `validate_route` only half-checks
(2 of 5 labels guarded, `routing_decision.py:174-177`).

### Node vs subgraph — decided, not defaulted

| Component | Kind | Why |
|---|---|---|
| The 9 pipeline nodes | node | Single step, no loop, no mid-node interrupt |
| `hotel_flow` | node | Linear; its one `interrupt` sits at `resolve_center`, before any expensive call |
| `general_qa` | **subgraph** | `create_react_agent` returns a *compiled graph*; adding it as a node already makes it a subgraph. Name it and set `checkpointer=` explicitly rather than inheriting silently |
| `rebuild_day` (Phase 9) | **subgraph** | Invoked once per day through a parent loop edge, so each day checkpoints independently |

The driver is LangGraph's interrupt semantics: an interrupted node **re-executes from its
beginning** on resume (https://docs.langchain.com/oss/python/langgraph/interrupts). Anything
that loops *and* contains an interrupt point must therefore be a subgraph invoked per
iteration, never a Python `for` inside one node. Phase 7 states this as a standing constraint;
Phase 9 is where it bites.

### The ReAct agent becomes a leaf

`general_qa` wraps `create_react_agent` with **only** `query_hotel` and `query_hotel_rooms`.
`recommend_hotels`, `select_hotel`, and `modify_trip_plan` are removed from its tool list — they
are graph flows now. The model can no longer decide whether a trip gets rebuilt; it can only
answer questions about data.

This is the concrete meaning of "one control plane": the agent still uses an LLM loop, but it
sits *inside* the graph as one terminal node rather than beside it as an alternative path.

### State

`TravelGraphState` is small per doc §9 — ids, messages, intent, the patch, validation errors,
missing slots, affected domains, tool results, response. The **business** state is the Phase 3
`TravelState` loaded by `load_context` and persisted by `apply_patch`; the graph state carries
execution, not truth.

## Related Code Files

- Create: `backend/src/agents/graph_v2/{__init__,state,graph}.py`
- Create: `backend/src/agents/graph_v2/nodes/*.py` — one file per node
- Modify: `backend/src/config.py` — `orchestrator` setting, default `legacy`
- Modify: `backend/src/api/routes.py` — dispatch on the flag; response shape unchanged
- Create: `backend/tests/test_graph_v2_skeleton.py`

## Implementation Steps

1. Define `TravelGraphState` and the node/edge topology with stub bodies.
2. Wire `load_context` to Phase 3's `TravelState` and Phase 4's checkpointer.
3. Port `scope_guard` from Phase 2 as the first real node.
4. Build `general_qa` with the reduced two-tool agent.
5. Build `respond` to emit the frozen `PlannerChatResponse` shape.
6. Add the `orchestrator` flag and route the endpoint through it.
7. Assert the topology in a test: every node reachable, no orphan, no cycle except the
   interrupt-resume edge.
8. Run the existing suite under `orchestrator=legacy` — it must be green and unchanged.

## Success Criteria

- [ ] `orchestrator=graph` completes a turn end to end and returns a valid `PlannerChatResponse`
- [ ] `orchestrator=legacy` is byte-identical to today; the full suite passes untouched
- [ ] `general_qa` exposes exactly two tools; `recommend_hotels`/`select_hotel`/`modify_trip_plan`
      are absent from its list
- [ ] No node reads a raw message to choose the next node — routing is edges only
- [ ] `general_qa` is registered as a compiled subgraph with an explicitly stated `checkpointer=`
- [ ] Topology test passes: every node reachable, no orphans
- [ ] `PlannerChatResponse` field shape unchanged from before this phase
- [ ] `make test` green

## Risk Assessment

| Risk | Mitigation |
|---|---|
| Two planes coexisting reintroduces the bug being fixed | Legacy plane frozen from this phase; window closed by Phase 11. This is a rollout mechanism, not an architecture |
| Skeleton drifts from what Phases 6-9 actually need | Node contracts are fixed by edges here; a later phase that needs a different contract must change the edge deliberately, in review |
| Frontend breaks mid-rewrite | Response shape frozen for the whole plan; the graph fills the same fields |
| Reduced agent tool list breaks existing Q&A | `query_hotel`/`query_hotel_rooms` cover today's Q&A paths; the other three were never reachable from a question, only from a planning intent |
| `graph_v2` naming lingers after cutover | Phase 11 renames it to `graph` as part of the deletion |
