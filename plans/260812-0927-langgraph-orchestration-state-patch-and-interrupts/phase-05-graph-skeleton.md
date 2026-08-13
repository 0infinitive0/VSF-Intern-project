---
phase: 5
title: "Graph skeleton + supervisor behind a flag"
status: done
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

# Workers → deterministic completion check → supervisor or onward
builder.add_conditional_edges("hotel_node",     all_tasks_done, {True: "budget_check", False: "supervisor"})
builder.add_conditional_edges("itinerary_node", all_tasks_done, {True: "budget_check", False: "supervisor"})
builder.add_conditional_edges("booking_node",   all_tasks_done, {True: "budget_check", False: "supervisor"})
builder.add_edge("qa_node", "respond")   # read-only: no budget or orchestration follow-up

builder.add_edge("respond", END)
```

`all_tasks_done(state) -> bool` is `not state["pending_tasks"]` — plain Python on a conditional
edge. Two consequences worth stating, because both were wrong in the first draft:

- **The supervisor is entered only when work remains.** A finished single-task turn never
  re-enters it, so it costs one delegation decision per turn at most, not two.
- **`qa_node` has exactly one outgoing edge.** An earlier revision drew it going both to the
  completion check and straight to `respond`; the diagram has been corrected to match.

### Supervisor node — delegation only, never completion counting

Doc §36 is explicit about the split: *"Validation within `understand_request`, patch/impact
logic within `apply_change`, **completion checks**, availability, booking confirmation, and
route/budget validation **remain deterministic Python**."* The supervisor prompt
(`prompts/supervisor.md`) covers only *"Routing, delegation, and replanning"*.

So the supervisor **has** an LLM, but "are all tasks done?" is `len(pending_tasks) == 0` —
a conditional edge, not a model call. Asking a model a question code already answers is the
same anti-pattern this whole plan removes.

**Worker names are not workflow names.** `detect_impact` returns
`set[Workflow]` where `Workflow = Literal["hotel","itinerary","itinerary_day"]`
(`domain/travel_state.py:24`). Mapping those to worker nodes is orchestration knowledge and
lives here — `domain/` must not know node names (Phase 3 purity test):

```python
WORKFLOW_TO_WORKER: dict[Workflow, str] = {
    "hotel":         "hotel_node",
    "itinerary":     "itinerary_node",
    "itinerary_day": "itinerary_node",   # same worker, narrower scope in state
}
# Fixed order when several workflows are impacted: the hotel anchors the itinerary,
# so rebuilding the itinerary first would schedule around a hotel about to change.
WORKER_ORDER = ("hotel_node", "itinerary_node", "booking_node", "qa_node")
```

**Possibility guard.** Structured output guarantees a valid *label*, not a *possible action* —
the distinction the legacy `validate_route` got right and this design initially dropped. Port
`_IMPOSSIBLE` (`routing_decision.py:174-177`) forward:

```python
_IMPOSSIBLE: dict[str, Callable[[TravelState], bool]] = {
    "itinerary_node": lambda s: not s.has_trip_data,        # nothing to edit yet
    "booking_node":   lambda s: True,                       # blocked until the booking plan lands
}
```

```python
class SupervisorDecision(BaseModel):
    next_worker: Literal["hotel_node", "itinerary_node", "booking_node", "qa_node"]
    task_description: str
    reasoning: str                       # audit only

def supervisor(state: TravelGraphState) -> dict:
    """Delegation only. Completion is decided by `all_tasks_done` on the edge."""
    if state["supervisor_iterations"] >= MAX_SUPERVISOR_ITERATIONS:
        return {"next_worker": "respond", "routing_source": "max_iterations"}

    workers = [WORKFLOW_TO_WORKER[w] for w in detect_impact(state["applied_changes"])]
    workers = [w for w in WORKER_ORDER if w in workers and not _IMPOSSIBLE.get(w, _never)(state)]

    # Fast path: exactly one possible worker and no prior failure → no LLM needed.
    if len(workers) == 1 and not state["task_results"]:
        return _delegate(workers[0], "impact_map", state)

    try:
        decision = llm.with_structured_output(SupervisorDecision).invoke(
            build_supervisor_prompt(build_manifest(state))
        )
        if _IMPOSSIBLE.get(decision.next_worker, _never)(state):
            raise ValueError(f"impossible worker: {decision.next_worker}")
        return _delegate(decision.next_worker, "supervisor", state, decision)
    except Exception:
        return _delegate(workers[0] if workers else "respond", "impact_map_fallback", state)
```

The fast path matters: ~90% of turns impact exactly one workflow, and those now cost **zero**
supervisor LLM calls. The model is consulted only for multi-workflow turns and for recovery
after a worker reports failure — the one decision `IMPACT_MAP` genuinely cannot make.

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
| `supervisor` | node | Delegation decision; deterministic fast path, LLM only for multi-workflow / recovery |
| `hotel_node` | **subgraph** | Doc §36 `subgraphs/hotel_flow.py` — search → availability → filter → rank. Contains an `interrupt` at `resolve_center` |
| `itinerary_node` | **subgraph** | Doc §36 `subgraphs/itinerary_flow.py`; itself drives the `rebuild_day` loop |
| `booking_node` | node | Declines explicitly until the booking plan lands — a stub that answers, not a pass-through |
| `qa_node` | **subgraph** | `create_react_agent` returns a *compiled graph*; set `checkpointer=` explicitly |
| `rebuild_day` (Phase 9) | **subgraph** | Invoked once per day through a parent loop edge, so each day checkpoints independently |

### `booking_node` declines — it does not pass through

`plan.md` defers booking: no auth model, no inventory source. But the supervisor needs a
routable destination for a booking request, otherwise such a turn silently falls to `respond`
with nothing said.

So `booking_node` exists and **answers**: it states booking is not supported yet and names what
the user *can* do. `_IMPOSSIBLE["booking_node"]` keeps the supervisor from ever selecting it for
planning work; only an explicit booking intent reaches it. A pass-through stub would produce the
silent no-op this plan exists to eliminate.

### Data contracts — doc §36 `contracts.py`

Each worker declares what it may read and write, so a worker cannot corrupt state it does not
own. Doc §36's example: *"`hotel_flow` may read trip dates and preferences and write hotel
results or a selected hotel; it cannot write itinerary or booking state."*

```python
@dataclass(frozen=True)
class NodeContract:
    reads:  frozenset[str]      # TravelState paths
    writes: frozenset[str]
    tools:  frozenset[str]
```

`qa_node` is **read-only** — an empty `writes` set, enforced at the node boundary rather than
trusted. That is what stops a Q&A turn from mutating a trip.

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
2. Define `WORKFLOW_TO_WORKER`, `WORKER_ORDER`, and `_IMPOSSIBLE` in `graph_v2/` — **not** in
   `domain/`, which must stay ignorant of node names (Phase 3 purity test).
3. Build the supervisor: deterministic fast path first, LLM only on multi-workflow or after a
   worker failure, `IMPACT_MAP` fallback on any LLM error.
4. Implement `all_tasks_done` as a plain predicate on a conditional edge — no LLM.
5. Wire `load_context` to Phase 3's `TravelState` and Phase 4's checkpointer.
6. Define `contracts.py` (`NodeContract`) for the four workers; `qa_node` writes nothing.
7. Port `scope_guard` from Phase 2 as the first real node.
8. Build `qa_node` with the reduced two-tool agent.
9. Build `respond` to emit the frozen `PlannerChatResponse` shape.
10. Stub `hotel_node` and `itinerary_node` as pass-throughs; make `booking_node` decline explicitly.
11. Add the `orchestrator` flag and route the endpoint through it.
12. Assert topology: every node reachable, no orphan, `qa_node` has exactly one outgoing edge,
    supervisor loop terminates within max iterations.
13. Test the fast path: a single-workflow turn issues **zero** supervisor LLM calls.
14. Test the fallback: mock LLM failure → `IMPACT_MAP` routing kicks in with a real worker name.
15. Test the possibility guard: supervisor proposing `itinerary_node` with no trip is rejected.
16. Run the existing suite under `orchestrator=legacy` — it must be green and unchanged.

## Success Criteria

- [x] `orchestrator=graph` completes a turn end to end and returns a valid `PlannerChatResponse`
      (`/planner_chat` only — `/planner_chat/stream` and the other session endpoints still always
      run the legacy cascade; documented in `config.py`'s `orchestrator` field and `.env.example`)
- [x] `orchestrator=legacy` is byte-identical to today; the full suite passes untouched (diff of
      `routes.py` is purely an early-return branch above the untouched legacy code)
- [x] Supervisor creates a task and delegates to a worker in at least one test case
- [x] Supervisor loop terminates within max iterations in all cases
- [x] **A single-workflow turn issues zero supervisor LLM calls** (fast path), asserted by call count
- [x] Supervisor LLM failure falls back to `IMPACT_MAP` and yields a real worker **node name**, not a `Workflow` value
- [x] A supervisor proposal that is impossible for current state is rejected and re-routed (extended
      during review to also reject a proposal outside this turn's `pending_tasks` queue, not just an
      `_IMPOSSIBLE` precondition failure)
- [x] `all_tasks_done` is a plain predicate — no LLM call in the completion path, asserted by call count
- [x] `booking_node` returns an explicit decline; it never returns an empty pass-through
- [x] `qa_node` writes nothing — contract violation raises, proven by test (structural for `qa_node`
      itself; `hotel_node`/`itinerary_node`/`booking_node` wrapped with `enforce_contract` in `build_graph`)
- [x] `qa_node` has exactly one outgoing edge
- [x] `qa_node` exposes exactly two tools; `recommend_hotels`/`select_hotel`/`modify_trip_plan`
      are absent from its list
- [x] No node reads a raw message to choose the next node — routing is supervisor or edges only
- [x] `qa_node` is registered as a compiled subgraph with an explicitly stated `checkpointer=`
- [x] Topology test passes: every node reachable, no orphans
- [x] `PlannerChatResponse` field shape unchanged from before this phase (`schemas.py` untouched)
- [ ] `make test` green — **not literally green**: `make test` runs the full unscoped `pytest tests/`,
      which was already red before this phase (pre-existing failures in `test_agents/test_supervisor.py`,
      `test_session_store.py`, `test_structural_regression_harness.py::test_full_session_structural_signature`,
      and 6 `test_api/` failures — all confirmed via `git stash` to fail identically without this
      phase's changes). Every test this phase's scope actually touches is green; see phase report.

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
