---
title: "LangGraph orchestration state patch and interrupts"
description: "Replace the hard-coded intake cascade and four rival mutation mechanisms with one validated state-patch layer, interruptible slots, and hard search filters."
status: pending
priority: P1
effort: "~15d"
tags: [langgraph, orchestration, refactor, state-management]
created: 2026-08-12
blockedBy: []
blocks: []
---

# LangGraph orchestration state patch and interrupts

## Overview

The chatbot deadlocks or silently drops intent whenever a user says something the
current turn is not standing in a slot for. Five reported failures — ambiguous date,
day-1 theme, budget gate, amenity re-search, radius search — are **one architectural
fault**, not five bugs:

`_process_chat_turn` runs **two control planes that never talk**. A hard-coded `if`
ladder (`_run_intake`, `session.py:1166-1206`) owns the pre-plan phase and has exactly
one branch per step — answer the pending question, or re-ask it. The ReAct agent only
gets control after the ladder finishes. Any other intent falls through a crack.

Underneath, **four rival mutation mechanisms** exist with no shared contract:
`TripIntakeState.with_message` (first-non-null-wins merge), `HotelPreferenceState.with_message`,
`TripPreferenceUpdate` (`changed_fields`, 5 fields only), and `TripEditPlan` (9 operations).

This plan adopts the orchestration layer of
`data/travel_chatbot_langgraph_production_architecture.md` — a single validated
state-patch abstraction, tri-state slot values, LangGraph `interrupt()` for ambiguity,
and an explicit impact map. It **keeps the existing deterministic domain layer**
(`trip_scheduler.py`, `trip_planner.py`, `routing.py`, `supabase_search.py`), which is
already what that document demands.

Source analysis: `backend/plans/reports/assessment-260812-0916-langgraph-production-architecture-fit.md`

### Locked decisions

| Decision | Choice |
|---|---|
| Checkpointer backend | Existing Supabase Postgres via `DATABASE_URL` |
| Radius search center | The user's selected hotel; `interrupt()` and ask when absent or ambiguous |
| Folder layout | Keep `src/{api,agents,services,models}` — reject the doc's `app/`+`repositories/` layout |
| Scope | Orchestration layer only; domain services stay |

### Non-goals

- Booking flow (doc §26) — no booking exists in this product.
- Rewriting `trip_scheduler.py` / `routing.py` — they are the correct deterministic layer.
- A `trips` table (doc §6) — duplicates the existing `itineraries`.
- Multi-agent proliferation (doc §38 warns against it explicitly).

## Goals

| # | Goal | Priority |
|---|------|----------|
| 1 | No pending question can deadlock the conversation | P1 |
| 2 | No user intent is silently dropped — state it, or say it is unsupported | P1 |
| 3 | One validated mutation path replaces the four rival mechanisms | P1 |
| 4 | Ambiguous input asks instead of guessing, and stays correctable | P1 |
| 5 | Amenity and radius become real filters, not ranking hints | P2 |
| 6 | Editing one day does not regenerate the whole trip | P2 |
| 7 | Every state mutation is auditable and measurable | P3 |

## Phases

| # | Phase | Depends on | Effort | Status |
|---|-------|-----------|--------|--------|
| 1 | [Fix deterministic theme and amenity bugs](./phase-01-start.md) | — | 0.5d | Pending |
| 2 | [Canonical TravelState and patch layer](./phase-02-canonical-travelstate-and-patch-layer.md) | — | 2d | Pending |
| 3 | [Unified extract_patch node](./phase-03-unified-extract-patch-node.md) | 2 | 2d | Pending |
| 4 | [Slot-driven interruptible intake](./phase-04-slot-driven-interruptible-intake.md) | 2, 3 | 2d | Pending |
| 5 | [Postgres checkpointer and interrupt](./phase-05-postgres-checkpointer-and-interrupt.md) | 4 | 2d | Pending |
| 6 | [Impact map, locked days, day-level regeneration](./phase-06-impact-map-locked-days-and-day-level-regeneration.md) | 2 | 3d | Pending |
| 7 | [Amenity and radius hard filters](./phase-07-amenity-and-radius-hard-filters.md) | 2, 5 | 1.5d | Pending |
| 8 | [Audit log and state patch eval](./phase-08-audit-log-and-state-patch-eval.md) | 2 | 1.5d | Pending |

**Phase 1 is independent of everything else — ship it first, on its own branch.**
It fixes two proven deterministic bugs and needs none of the refactor.

Natural stop points: after Phase 1 (bugs gone), after Phase 4 (deadlock class gone),
after Phase 7 (all five reported cases fixed). Phase 8 is measurement, not behavior.

## Reported failure → phase mapping

| Reported symptom | Root cause | Fixed in |
|---|---|---|
| Đổi theme ngày 1 không ăn | `normalize_day_themes:534` overwrites the user's theme with the trip-level preference | **P1** |
| Search lại amenities trả về khách sạn không có tiện ích | Amenity is a `+0.03` ranking bonus, never a filter; pills assigned blindly on first request | **P1** (pill), **P7** (filter) |
| Ngân sách chưa nhập chưa cho edit | `_run_intake` step 2 hard gate; `direct_preference_update` unreachable; date picker gated behind budget | **P4** |
| Ngày 01/07 thiếu năm bị đoán bừa và khoá cứng | No temporal validation; `with_message:296` first-non-null-wins makes it uncorrectable | **P3** (correctable), **P5** (ask) |
| Tìm khách sạn bán kính 3km | `recommend_hotels` never passes `max_radius_km`; no center concept | **P7** |

## Risk register

| Risk | Severity | Mitigation | Phase |
|---|---|---|---|
| `normalize_day_themes` blast radius: **CRITICAL**, 14 symbols, 10 execution flows | High | Marker is **per-theme**, not per-call. Absent marker ⇒ old behavior, and that old behavior is *verified correct* for all three callers (see P1 characterization table) — not assumed. Characterization tests pin each caller before the change | P1 |
| `select_hotel_candidates` blast radius: **CRITICAL**, 12 symbols, 10 flows | High | New keyword-only params defaulting to `None`; existing 4 call sites untouched | P7 |
| Local model (llama3.1) emits invalid JSON patch | High | Strict parse + retry-once (reuse `plan_trip_edit`'s proven shape); fall back to `decide_route_by_rules` | P3 |
| `TripIntakeState` blast radius: MEDIUM, 17 symbols, 5 direct | Medium | Keep the class as a read-only *view* over canonical state; no call-site signature changes | P2 |
| `PostgresSaver.from_conn_string` is a context manager; current code builds a checkpointer per session | Medium | Move to one app-lifespan checkpointer; sessions share it keyed by `thread_id` | P5 |
| `interrupt()` only works inside a graph node; intake is currently plain Python outside the graph | Medium | P5 depends on P4 turning intake into a node — sequencing is mandatory, not optional | P5 |
| Persistent checkpointer changes `thread_id` semantics for live sessions | Medium | Ship behind a settings flag; existing in-memory sessions drain via TTL | P5 |

## Success Criteria

- [ ] Every reported failure in the mapping table above has a regression test that fails before its phase and passes after
- [ ] No code path can re-ask the same question twice with no state change and no explanation
- [ ] `ALLOWED_PATHS` rejects every path outside the allow-list, proven by test
- [ ] `TripIntakeState` / `HotelPreferenceState` public APIs unchanged — existing tests pass untouched
- [ ] `make test` green after every phase, not only at the end
- [ ] `eval/` end-to-end pass rate ≥ the committed `eval/results/baseline.json`

## References

- Architecture source: `data/travel_chatbot_langgraph_production_architecture.md`
- Fit assessment: `backend/plans/reports/assessment-260812-0916-langgraph-production-architecture-fit.md`
- Existing eval harness: `plans/260807-1400-ragas-rag-evaluation-harness/` (delivered; Phase 8 extends it)
- LangGraph persistence: https://docs.langchain.com/oss/python/langgraph/persistence
- LangGraph interrupts: https://docs.langchain.com/oss/python/langgraph/interrupts

## Open Questions

1. Phase 5 flag rollout: drain live sessions via TTL, or force-reset all sessions at deploy?
2. Should `locked_days` (Phase 6) get a UI control, or stay chat-only for now?
3. Phase 8 audit log: new Supabase table, or extend the existing `sessions.context_data`?

<!-- slug: langgraph-orchestration-state-patch-and-interrupts -->
