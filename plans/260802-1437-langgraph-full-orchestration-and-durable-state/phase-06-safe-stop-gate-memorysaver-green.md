---
phase: 6
title: "Safe Stop Gate MemorySaver Green"
status: pending
priority: P1
effort: "1d"
dependencies: [5]
---

# Phase 6: Safe Stop Gate MemorySaver Green

## Overview

**Final in-scope phase.** Verification and documentation, not new code.
Everything runs on `StateGraph` + `MemorySaver`. Goals 1, 2, 4, and 5 are
delivered; goal 3 (durability) is deliberately not.

Validation session 1 replaced this phase's original go/no-go gate with a
decision already taken: phases 7-8 are deferred until after Demo Day. This phase
now closes out delivery and hands the deferred work forward cleanly.

<!-- Updated: Validation Session 1 - go/no-go gate replaced by deferred-work handoff; phase is now terminal -->


## Requirements

- Functional: web UI and terminal CLI both complete a full trip flow.
- Non-functional: per-turn p50 within 20% of the Phase 2 baseline.
- Non-functional: architecture doc + diagram exist and match the shipped code.

## Architecture

Nothing new is built. This phase produces the artifacts that make the work
legible — the four-layer picture the Demo Day question "what is your
architecture?" is actually asking about:

```
HTTP (src/api/routes.py)
  → chat-turn StateGraph (src/agents/) — router + 5 handler nodes, MemorySaver
    → ReAct subgraph + ToolNode (4 tools reading/writing TripState)
      → services (src/services/) — provider-agnostic via langchain-core
        → Supabase + Qdrant
```

Also state plainly, in the doc, what is *not* durable yet: state lives in memory
and dies with the process. Say it before a judge finds it.

## Related Code Files

- Create: `docs/architecture/chat-turn-graph.md` — four-layer description + node table + the LangGraph/LangChain split
- Create: `plans/visuals/chat-turn-graph.svg` — exported from Phase 5 step 9
- Modify: `plans/reports/baseline-260802-turn-latency.md` — append post-migration numbers
- Modify: `README.md` — only if the run instructions changed

## Implementation Steps

1. Full `pytest` from a clean checkout, no cached artifacts.
2. Manual smoke on the web UI: intake → hotel options → pick → edit → finalize.
   Cover the drop-pending-list case ("chốt lịch trình" while a list is showing).
3. Manual smoke on `scripts/poc_trip_planner.py`, same flow.
4. Re-measure per-turn latency under Phase 2's recorded conditions; append to the
   baseline report. Investigate any regression above 20%.
5. Confirm the plan-level structural criteria: two `create_react_agent`, six
   nodes, no `TripSession`, no tool touching a session.
6. Write `docs/architecture/chat-turn-graph.md`, including the explicit
   "state is not durable yet" statement and a one-line note that Postgres
   checkpointing is designed in phase 7 but deliberately out of scope.
7. Commit; tag or note the commit as the delivery boundary.
8. Confirm phases 7-8 remain marked `deferred` and that no in-scope success
   criterion depends on them. Then stop — remaining time goes to demo and UX.

## Success Criteria

- [ ] Full `pytest` green from a clean checkout
- [ ] Web UI smoke passes end to end, including the drop-pending-list case
- [ ] Terminal CLI smoke passes end to end
- [ ] p50 within 20% of the Phase 2 baseline, same measurement conditions
- [ ] `create_react_agent` × 2; graph has 6 nodes; `TripSession` gone; tools session-free
- [ ] `docs/architecture/chat-turn-graph.md` exists and matches the code
- [ ] Diagram exported to `plans/visuals/`
- [ ] Doc states explicitly that state is not yet durable
- [ ] Delivery-boundary commit recorded
- [ ] Phases 7-8 still marked `deferred`; no in-scope criterion depends on them

## Risk Assessment

| Risk | Mitigation |
|---|---|
| Phases 7-8 get started anyway because the design is already written and looks close | They are marked `deferred` in frontmatter and the phases table; step 8 re-confirms. Restarting them requires an explicit scope change, not momentum |
| The "not durable" caveat is quietly dropped from the doc because it looks bad | It is a named success criterion. A judge finding it unaided costs more than stating it |
| Latency regressed and nobody notices until the demo | Step 4 compares against a recorded baseline under recorded conditions, not against memory |
| The architecture doc describes the plan rather than the shipped code | Written after the smoke tests, from the code; step 5 cross-checks the structural claims |
| Manual smoke misses the drop-pending-list path — the subtlest behavior in the system | Called out explicitly in steps 2 and its own success criterion |
