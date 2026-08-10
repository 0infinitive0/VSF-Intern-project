---
phase: 7
title: "Itinerary planning and optimization"
status: pending
priority: P1
dependencies: [6]
effort: ""
---

# Phase 7: Itinerary planning and optimization

## Overview

Generate personalized day-by-day itineraries from budget, dates, and preferences, tied to real hotel and attraction records with an optimized route (BR-06). This is Sprint 3's headline feature and the third of the three capabilities the final demo must show (BRD §9).

## Requirements

- Functional: day-by-day itinerary from the five profiling slots collected in Phase 3 (BR-06).
- Functional: every item references a real `attractions` or `hotels` record (BR-07).
- Functional: route optimized by travel time and opening hours.
- Functional: respects the stated budget.
- Functional: bilingual output (BR-10).
- Non-functional: generation fast enough to feel interactive, or clearly progress-indicated.

## Architecture

**The data already exists and is unusually well-suited.** The attractions pipeline captures coordinates, categories, and — critically — opening hours, which `design_proposal.md` §3A explicitly calls out as the enabler for timeline scheduling. The category-balanced selection already implemented in `attraction_utils.py` (each category soft-capped at 40% of the limit) is directly reusable for building a varied day rather than five museums in a row.

**Persist to the existing schema.** `itineraries` and `itinerary_items` exist with no producer; this phase is their producer. `itinerary_items` already carries day, order, reference type, reference ID, and cost — matching BRD §13.3's conceptual model.

**Optimization should stay simple.** With a handful of attractions per day, an exact solution is unnecessary — nearest-neighbour ordering plus an opening-hours feasibility check is sufficient and explicable. A sophisticated solver is not what earns marks at go/no-go; a schedule that respects real opening hours and plausible travel times does. Keep travel-time estimation simple (straight-line distance with a city-speed factor) unless a routing API is already available.

**Thematic days** (`design_proposal.md` §3A) — give each day a coherent theme rather than a flat list. This is largely a grouping-and-labelling concern over the category data.

**Not in scope:** local events integration (`design_proposal.md` §3A) has no data source — `events` has no producer and no pipeline populates it. Either drop it explicitly or note it as a future item; do not imply it works.

## Related Code Files

- Create: `src/services/itinerary.py` (generation), `src/services/routing.py` (ordering, travel time, opening hours)
- Create: `src/agents/nodes/itinerary_node.py`, `src/agents/tools/itinerary_tool.py`
- Create: `docs/itinerary_sequence_diagram.md` (BRD §13.4 required L3 artifact)
- Modify: `src/agents/graph.py` (itinerary route), `src/models/schemas.py`, `frontend/` (timeline panel)
- Read only: `src/airflow/dags/data_pipeline/attraction_utils.py` (category balancing precedent)

## Implementation Steps

1. **Document the itinerary sequence diagram** — a required Sprint 3 L3 deliverable per BRD §13.4, and the clearest specification of the flow.
2. **Implement candidate selection:** attractions near the chosen hotel's destination, filtered by preference, balanced across categories using the existing precedent.
3. **Implement day allocation** across trip length with a coherent theme per day.
4. **Implement route ordering and scheduling:** order by proximity, assign time ranges honouring opening hours, insert realistic travel gaps. Drop or reschedule anything that cannot fit.
5. **Implement budget accounting** — sum hotel and attraction costs, report against the stated budget, and flag overruns rather than silently trimming.
6. **Persist** to `itineraries` and `itinerary_items`.
7. **Wire the graph route**, triggered by the "Tạo lịch trình" action once all five slots are filled.
8. **Render the timeline** in Phase 5's right panel — the comp already shows the intended treatment.
9. **Bilingual output** — day themes and item descriptions in the conversation language.

## Success Criteria

- [ ] Day-by-day itinerary generated from the collected slots.
- [ ] Every item references a real record — no invented attractions (BR-07).
- [ ] Time ranges respect opening hours; no impossible schedules.
- [ ] Budget reported against the stated figure; overruns flagged.
- [ ] Itineraries persist and reload.
- [ ] Timeline renders in the UI in both languages.
- [ ] `docs/itinerary_sequence_diagram.md` exists (BRD §13.4).

## Risk Assessment

- **Risk:** Attraction coverage is thin for a chosen destination, producing a sparse itinerary.
  **Mitigation:** Check coverage per destination early. If thin, run the attractions DAG for the demo destinations — the pipeline already exists and this is exactly what it is for.
- **Risk:** Opening-hours data is missing or malformed for many attractions.
  **Mitigation:** Measure coverage before building the scheduler. Where hours are unknown, schedule conservatively and mark the item rather than asserting a precise slot.
- **Risk:** Optimization scope creep consumes Sprint 3.
  **Mitigation:** Nearest-neighbour plus feasibility is the committed approach. Anything more is out of scope unless M3 deliverables are already complete.
- **Risk:** Sprint 3 must also produce all of Phase 8's handover material.
  **Mitigation:** Phase 8 starts in parallel — documentation does not depend on this phase finishing, and the roadmap's descope order puts Phase 7 ahead of Phase 8 only for *build* work.
