---
phase: 5
title: "Graph skeleton + supervisor behind a flag"
status: pending
priority: P1
effort: "3.5d"
dependencies: [3, 4]
---

# Phase 5: Graph skeleton + supervisor behind a flag

## Overview

Build the single control plane as a real `StateGraph` — every node, every edge — running behind
`orchestrator=graph|legacy`. The **supervisor node** is the central orchestrator: it creates
tasks, delegates to worker nodes, and checks completion. Nodes are thin or stubbed here;
Phases 6-9 fill them. This is the phase that makes "one supervisor, four workers" a structure
rather than an intention.

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
- Functional: the supervisor node creates a task list, delegates to a worker, and checks
  completion — with `IMPACT_MAP` as deterministic fallback when the LLM fails.
- Functional: the supervisor loop is bounded by a max iteration count (5).
- Non-functional: `PlannerChatResponse` field shape is frozen for the whole plan — the frontend
  must not change until after Phase 11.
- Non-functional: the legacy plane is **frozen** from this phase on. No edits except reverts.

## Architecture

`backend/src/agents/graph_v2/` — a new package, so the legacy `graph.py` stays untouched and
deletion in Phase 11 is a directory removal rather than surgery.

### Graph topology

```python
builder = StateGraph(TravelGraphState)

# --- Tiền xử lý (pipeline) ---
builder.add_node("load_context",   load_context)
builder.add_node("scope_guard",    scope_guard)      # Phase 2, already built
builder.add_node("extract_patch",  extract_patch)    # Phase 6
builder.add_node("validate_patch", validate_patch)   # Phase 3 validators
builder.add_node("apply_patch",    apply_patch)      # Phase 3
builder.add_node("ask_slot",       ask_slot)         # Phase 7

# --- Supervisor + 4 worker nodes ---
builder.add_node("supervisor",     supervisor)       # 🧠 Tạo task, chia task, kiểm tra
builder.add_node("hotel_node",     hotel_node)       # Phase 8
builder.add_node("itinerary_node", itinerary_node)   # Phase 9
builder.add_node("booking_node",   booking_node)     # Placeholder — plan riêng
builder.add_node("qa_node",        qa_node)          # ReAct agent as a WORKER subgraph

# --- Kết thúc ---
builder.add_node("respond",        respond)
```

### Edges — supervisor loop

```python
# Pipeline: START → ... → supervisor
builder.add_edge(START, "load_context")
builder.add_edge("load_context", "scope_guard")
# scope_guard → refuse | extract_patch
builder.add_edge("extract_patch", "validate_patch")
# validate_patch → interrupt | apply_patch
builder.add_edge("apply_patch", "ask_slot")
# ask_slot → ask (END) | supervisor

# Supervisor → worker delegation
builder.add_conditional_edges(
    "supervisor",
    route_supervisor,
    {
        "hotel_node":     "hotel_node",
        "itinerary_node": "itinerary_node",
        "booking_node":   "booking_node",
        "qa_node":        "qa_node",
        "respond":        "respond",       # all tasks done
    }
)

# Workers → back to supervisor for checking
builder.add_edge("hotel_node",     "supervisor")
builder.add_edge("itinerary_node", "supervisor")
builder.add_edge("booking_node",   "supervisor")
builder.add_edge("qa_node",        "respond")  # QA goes directly to respond

builder.add_edge("respond", END)
```

The key pattern: **workers always return to supervisor**, except `qa_node` which goes
directly to respond (no further orchestration needed for Q&A).

### Supervisor node — the brain

```python
class SupervisorDecision(BaseModel):
    """Structured output from the supervisor LLM."""
    next_worker: Literal["hotel_node", "itinerary_node", "booking_node", "qa_node", "respond"]
    reasoning: str                  # for audit trail
    task_description: str           # what the worker should do

def supervisor(state: TravelGraphState) -> dict:
    """
    Central orchestrator. Receives a compact SessionManifest, NOT the full state,
    and decides which worker to call next (or finish).
    
    Fallback: if LLM fails → IMPACT_MAP deterministic routing.
    Loop guard: max 5 iterations per turn.
    """
    if state["supervisor_iterations"] >= MAX_SUPERVISOR_ITERATIONS:
        return {"next_worker": "respond", "routing_source": "max_iterations"}
    
    try:
        manifest = build_manifest(state)
        decision = llm.with_structured_output(SupervisorDecision).invoke(
            build_supervisor_prompt(manifest)
        )
        return {
            "next_worker": decision.next_worker,
            "task_description": decision.task_description,
            "routing_source": "supervisor",
            "routing_reasoning": decision.reasoning,
            "supervisor_iterations": state["supervisor_iterations"] + 1,
        }
    except Exception:
        # Fallback to deterministic IMPACT_MAP
        impact = detect_impact_from_map(state)
        return {
            "next_worker": impact or "respond",
            "routing_source": "impact_map_fallback",
            "supervisor_iterations": state["supervisor_iterations"] + 1,
        }
```

### Supervisor vs old `detect_impact` — what changed

| Aspect | Old (`detect_impact`) | New (`supervisor`) |
|--------|----------------------|-------------------|
| Mechanism | `IMPACT_MAP[path]` table lookup | LLM structured output |
| Multi-task | 1 flow per turn | Can delegate multiple workers sequentially |
| Checking | None — flow runs and finishes | Supervisor checks result, can re-delegate |
| Fallback | N/A — already deterministic | `IMPACT_MAP` on any LLM failure |
| Audit | Path → domain | Task description + reasoning + routing_source |
| Data Scope | Flow gets full state | Supervisor gets compact manifest; workers get state slices via Data Contracts |

### Node vs subgraph — decided, not defaulted

| Component | Kind | Why |
|---|---|---|
| The pipeline nodes (load_context..ask_slot) | node | Single step, no loop, no mid-node interrupt |
| `supervisor` | node | LLM call → structured output → route decision |
| `hotel_node` | node | Linear; its one `interrupt` sits at `resolve_center`, before any expensive call |
| `itinerary_node` | node | Delegates to `rebuild_day` subgraph internally |
| `booking_node` | node | Placeholder; will become subgraph when real booking exists |
| `qa_node` | **subgraph** | `create_react_agent` returns a *compiled graph*; set `checkpointer=` explicitly |
| `rebuild_day` (Phase 9) | **subgraph** | Invoked once per day through a parent loop edge, so each day checkpoints independently |

The driver is LangGraph's interrupt semantics: an interrupted node **re-executes from its
beginning** on resume (https://docs.langchain.com/oss/python/langgraph/interrupts). Anything
that loops *and* contains an interrupt point must therefore be a subgraph invoked per
iteration, never a Python `for` inside one node. Phase 7 states this as a standing constraint;
Phase 9 is where it bites.

### The ReAct agent becomes `qa_node`

`qa_node` wraps `create_react_agent` with **only** `query_hotel` and `query_hotel_rooms`.
`recommend_hotels`, `select_hotel`, and `modify_trip_plan` are removed from its tool list — they
are worker node actions now. The model can no longer decide whether a trip gets rebuilt; it can
only answer questions about data.

The supervisor decides whether a turn goes to `qa_node` or to `hotel_node` — that decision
is the concrete meaning of "one supervisor orchestrates all routing."

### State

`TravelGraphState` is small per doc §9 — ids, messages, intent, the patch, validation errors,
missing slots, tool results, response. Added fields for the supervisor loop:

```python
class TravelGraphState(TypedDict):
    # ... existing fields ...
    
    # Supervisor loop state
    supervisor_iterations: int           # loop counter, reset each turn
    next_worker: str                     # which worker to call
    task_description: str                # what the worker should do
    task_results: list[dict]             # results from completed workers
    routing_source: str                  # "supervisor" | "impact_map_fallback"
    routing_reasoning: str               # supervisor's reasoning (audit)
```

The **business** state is the Phase 3 `TravelState` loaded by `load_context` and persisted by
`apply_patch`; the graph state carries execution, not truth.

## Related Code Files

- Create: `backend/src/agents/graph_v2/{__init__,state,graph,contracts}.py`
- Create: `backend/src/agents/graph_v2/nodes/{supervisor,load_context,scope_guard,ask_slot,respond}.py`
- Create: `backend/src/agents/graph_v2/nodes/{hotel_node,itinerary_node,booking_node,qa_node}.py` — stubs
- Modify: `backend/src/config.py` — `orchestrator` setting, default `legacy`
- Modify: `backend/src/api/routes.py` — dispatch on the flag; response shape unchanged
- Create: `backend/tests/test_graph_v2_skeleton.py`
- Create: `backend/tests/test_supervisor_routing.py`

## Implementation Steps

1. Define `TravelGraphState` with supervisor loop fields, `SessionManifest`, and the node/edge topology.
2. Build the supervisor node with structured output over `SessionManifest` and `IMPACT_MAP` fallback.
3. Wire `load_context` to Phase 3's `TravelState` and Phase 4's checkpointer.
4. Define Data Contracts (`NodeContract`) for the 4 workers to limit read/write access.
5. Port `scope_guard` from Phase 2 as the first real node.
5. Build `qa_node` with the reduced two-tool agent.
6. Build `respond` to emit the frozen `PlannerChatResponse` shape.
7. Stub `hotel_node`, `itinerary_node`, `booking_node` as pass-throughs.
8. Add the `orchestrator` flag and route the endpoint through it.
9. Assert the topology in a test: every node reachable, no orphan, supervisor loop
   terminates within max iterations.
10. Test supervisor fallback: mock LLM failure → verify `IMPACT_MAP` routing kicks in.
11. Run the existing suite under `orchestrator=legacy` — it must be green and unchanged.

## Success Criteria

- [ ] `orchestrator=graph` completes a turn end to end and returns a valid `PlannerChatResponse`
- [ ] `orchestrator=legacy` is byte-identical to today; the full suite passes untouched
- [ ] Supervisor creates a task and delegates to a worker in at least one test case
- [ ] Supervisor loop terminates within max iterations in all cases
- [ ] Supervisor LLM failure falls back to `IMPACT_MAP` deterministic routing
- [ ] `qa_node` exposes exactly two tools; `recommend_hotels`/`select_hotel`/`modify_trip_plan`
      are absent from its list
- [ ] No node reads a raw message to choose the next node — routing is supervisor or edges only
- [ ] `qa_node` is registered as a compiled subgraph with an explicitly stated `checkpointer=`
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
| **Supervisor LLM picks wrong worker** | Structured output with closed label set (4 workers); `IMPACT_MAP` fallback on failure; routing accuracy measured in Phase 10 |
| **Supervisor loops infinitely** | Hard cap at 5 iterations/turn; exceeded → force respond. Counter is in graph state, not trust |
| **Supervisor overhead adds latency** | 1 LLM call per supervisor decision; same as old `decide_route_by_llm`. Multi-task turns add more calls but deliver more value |
