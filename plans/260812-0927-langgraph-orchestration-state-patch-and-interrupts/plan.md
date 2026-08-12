---
title: "Single control plane — LangGraph rewrite of the orchestration layer"
description: "Replace the deterministic cascade + ReAct plane with one LangGraph graph: patch-validated state, interrupts, hard filters, day-level regeneration. Delete the old plane."
status: pending
priority: P1
effort: "~27d"
tags: [langgraph, orchestration, rewrite, state-management]
created: 2026-08-12
blockedBy: []
blocks: []
---

# Single control plane — LangGraph rewrite of the orchestration layer

## Overview

A chat turn currently runs through **two control planes that never talk**:

- a deterministic cascade (`_process_chat_turn` → `_run_intake` / `_run_edit_draft` /
  `_run_finalize`), which calls tools directly through `_ToolAdapter`, and
- a ReAct agent (`_run_chat_agent`), which only gets control after the cascade finishes.

This plan **deletes the first and demotes the second**, replacing both with one LangGraph
graph built on `data/travel_chatbot_langgraph_production_architecture.md` §10/§35.

### Why two planes exist — and why patching them was rejected

Archaeology, from git rather than guesswork:

| Evidence | Meaning |
|---|---|
| `create_react_agent` present in `3dc4acd Initial commit` | Started as a pure-agent product |
| `_run_intake` appears much later | The ladder grew afterwards |
| `routing_decision.py` docstring: *"extracted from `process_chat_turn`'s cascade… reproduces today's cascade conditions"* | The cascade came first; the router was reverse-engineered from it |
| `graph.py::_ToolAdapter`: *"the pre-Phase-4 `.invoke(args) -> str` convention that the deterministic cascade depends on"* | The cascade calls tools directly — that is the second plane |

The ladder is **scar tissue from an unreliable local model** (`llama3.1` via Ollama). Each
guard was individually rational — `MIN_PLAUSIBLE_PRICE_VND` came from a real RAGAS finding,
the `recommend_hotels` anti-loop from real model behavior, `_new_trip_signal`'s day-scope regex
from "3 ngày 2 người" being misread as "edit day 2". Fifteen rational reactions compounded into
an architecture nobody designed.

An earlier revision of this plan kept both planes alive during an incremental migration. That
was rejected: it accepted "two sources of truth during transition" as a standing risk, and it
left every regex guard in place with nobody able to prove what depended on them.

### The single plane

```
START → load_context → scope_guard → extract_patch → validate_patch
      → [interrupt when ambiguous] → apply_patch → next_question?
      → detect_impact → hotel_flow | itinerary_flow | general_qa | none
      → validate_result → respond → END
```

All routing lives in **graph edges**. There is no `_decide_route`, no
`decide_route_by_rules`, no regex intent zoo.

**The ReAct agent survives as a leaf node, not a plane.** It handles the
`general_question` intent only, keeping `query_hotel` and `query_hotel_rooms`.
`recommend_hotels`, `select_hotel`, and `modify_trip_plan` stop being agent tools and become
graph flows, so the model can no longer choose whether a trip gets rebuilt.

### What is deleted

| Target | Size |
|---|---|
| `routing_decision.py` | 189 LOC |
| `supervisor.py` | 108 LOC |
| 17 functions in `session.py` — `_process_chat_turn`, `_decide_route`, `_run_intake`, `_run_edit_draft`, `_run_chat_agent`, `_run_finalize`, `_run_recommend_hotels`, `_begin_new_trip_if_requested`, `_looks_like_*`, `_is_generic_*`, `_unsupported_destination_reply`, … | ~900 LOC |
| `TripPreferenceUpdate`, `TripIntakeState.with_message`, `HotelPreferenceState.with_message` | ~250 LOC |
| `graph.py::_ToolAdapter`, `SessionTools` | ~60 LOC |

≈ **1,400 LOC removed.** `session.py` shrinks 1656 → ~400 (`TripSession`, `SessionRegistry`,
persist hooks).

### What is kept — deliberately

The **5,051-LOC domain layer** (`trip_scheduler`, `trip_planner`, `routing`,
`supabase_search`, `itinerary_reuse`, `trip_formatter`) is untouched as a layer. It is not a
control plane; it is what the control plane calls, and doc §5 explicitly requires it. Rewriting
it would mean rewriting it identically.

### Doc §36 project structure — adopted selectively

Measured rather than argued: 3 of §36's directories already exist under different names, 3
differences are pure renames, 2 are real gaps.

| Decision | Reason |
|---|---|
| **Reject** `app/` ← `src/`, `graph/` ← `agents/`, sibling `tools/` | **248 import lines across 81 files**, zero behavior change. Worse, Phase 5 creates `graph_v2/` and Phase 11 renames it to `graph/` — a simultaneous global directory move makes every diff unreadable and `git bisect` useless exactly when P11's 1,400-LOC deletion needs it |
| **Adopt** `domain/` — **new files only** | `src/services/` is already 18 files mixing pure algorithms, data access, LLM calls, and formatting. `travel_state.py` and `slot_registry.py` are pure state/validation and do not belong beside `supabase_search.py`. Free to adopt because these files do not exist yet |
| **Defer** `repositories/` | Real debt — 7 service files call `supabase.table(...)` directly. But fixing it means editing the 5,051-LOC domain layer this plan freezes. Separate plan, after cutover |

Layer rule becomes `api → agents → services → domain → models`, with `domain/` importing
nothing above it. Phase 3 adds the layer, its purity test, and the `ARCHITECTURE.md` update
together, so the document changes with the code rather than ahead of it.

### Non-goals

- Rewriting the domain layer.
- A `trips` table (doc §6) — duplicates the existing `itineraries`.
- Multi-agent proliferation (doc §38 warns against it explicitly).

### Deferred to separate plans — blocked, not declined

| Requirement | Blocker |
|---|---|
| "Không cho người khác xem" | No user model. `SessionRegistry` issues anonymous UUIDs; `itineraries` has no `user_id`; no sharing concept. Doc §6 assumes `trips.user_id NOT NULL` throughout |
| Giữ chỗ / sold out / handoff | The above, **plus** no inventory/availability source. `grep` for booking/hold/reserve/sold_out across `src/` returns zero functional hits |

Sequence: **auth + ownership plan → booking plan.** Building booking without a real availability
source means fabricating inventory state — the failure doc §32 names explicitly.

## Goals

| # | Goal | Priority |
|---|------|----------|
| 1 | Exactly one path processes a turn; the old plane is deleted, not disabled | P1 |
| 2 | No pending question can deadlock the conversation | P1 |
| 3 | One validated writer for all state; no mechanism can bypass `ALLOWED_PATHS` | P1 |
| 4 | Ambiguous input asks instead of guessing, and stays correctable | P1 |
| 5 | Out-of-scope requests are refused, never answered or fabricated | P1 |
| 6 | Amenity, rating and radius are real filters; no silent relaxation anywhere | P2 |
| 7 | Editing one day does not regenerate the whole trip | P2 |
| 8 | Constraints the user can state, the scheduler can enforce | P2 |
| 9 | Places are searchable; suggestions precede replacement | P2 |
| 10 | Every state mutation is auditable, and patch accuracy is measured | P1 |

## Phases

| # | Phase | Depends on | Effort |
|---|-------|-----------|--------|
| 1 | [Domain bug fixes: day theme + amenity pill](./phase-01-start.md) | — | 0.5d |
| 2 | [Out-of-scope refusal guardrail](./phase-02-out-of-scope-refusal-guardrail.md) | — | 0.5d |
| 3 | [TravelState, patch layer, IMPACT_MAP](./phase-03-travelstate-patch-layer.md) | — | 2d |
| 4 | [Postgres checkpointer](./phase-04-postgres-checkpointer.md) | — | 1.5d |
| 5 | [Graph skeleton behind a flag](./phase-05-graph-skeleton.md) | 3, 4 | 3d |
| 6 | [extract_patch node](./phase-06-extract-patch-node.md) | 5 | 2d |
| 7 | [Slot registry, next_question, interrupt](./phase-07-slots-and-interrupt.md) | 6 | 2.5d |
| 8 | [hotel_flow: hard filters, radius, center](./phase-08-hotel-flow.md) | 7 | 2d |
| 9 | [itinerary_flow: day-level regen, locked_days](./phase-09-itinerary-flow.md) | 7 | 3d |
| 10 | [Audit log and State Patch Accuracy eval](./phase-10-audit-and-eval.md) | 3 | 1.5d |
| 11 | [**CUTOVER** — flip default, delete the old plane](./phase-11-cutover.md) | 8, 9, 10 | 2d |
| 12 | [Per-day itinerary constraints](./phase-12-per-day-constraints.md) | 9, 11 | 2.5d |
| 13 | [Place search and suggest-before-replace](./phase-13-place-search.md) | 8, 11 | 2d |
| 14 | [Trip-total budget constraint](./phase-14-trip-total-budget.md) | 9, 11 | 2.5d |

**Phases 1 and 2 are independent of the rewrite — ship them first, together, ~1 day.**
Phase 1's bugs live in the domain layer and survive any orchestration change; Phase 2 closes
the refusal gap. Neither waits on anything.

**Phase 11 is the point of no return.** Phases 5-9 build the new plane behind
`orchestrator=graph|legacy`; both planes exist only during that window, and Phase 11 ends it by
deleting the old one. Phase 10 lands *before* cutover because State Patch Accuracy plus the
existing RAGAS end-to-end score are the evidence that the new plane is at least as good.

Natural stop points: after 1+2, after 7 (deadlock class gone), after 11 (one plane), after 14.

## Reported failure → phase mapping

| Symptom | Root cause | Fixed in |
|---|---|---|
| Đổi theme ngày 1 không ăn | `normalize_day_themes:534` overwrites the user's theme; prompt collision `trip_edit_planner.py:442`/`:445` | **1**, **6** |
| Search amenities trả về khách sạn không có tiện ích | `+0.03` ranking bonus, never a filter; pills asserted blindly | **1**, **8** |
| Ngân sách chưa nhập chưa cho edit | `_run_intake` hard gate; `direct_preference_update` unreachable; date picker gated behind budget | **7** |
| Ngày 01/07 thiếu năm, đoán rồi khoá cứng | No temporal validation; `with_message:296` first-non-null-wins | **6**, **7** |
| Ngày `1-2-2026`, `31/07` thứ tự ngày/tháng | No order rule anywhere | **7** |
| Ngày ngoài vùng dữ liệu `1/7-7/7` | Valid date, no `room_prices` → blames coordinates | **8** |
| Bán kính 3km | `recommend_hotels` never passes `max_radius_km`; no center concept | **8** |
| Đánh giá trên 4 sao | `min_star_rating` silently falls back to unfiltered (`supabase_search.py:281`) | **8** |
| Kết hợp nhiều tiện ích, "có gym" | AND undefined; gym/spa absent from the 7-tag taxonomy | **8** |
| Giới hạn N địa điểm/ngày, khoảng cách <1km | `planning_constraints` has neither family | **12** |
| Tìm nhà hàng xung quanh | Restaurants only exist as fixed meal-slot queries | **13** |
| Gợi ý địa điểm trước khi đổi | Only hotels have a selection list | **13** |
| Tổng ngân sách dưới 3tr | `_calculate_trip_budget` computes but never constrains | **14** |
| Từ chối toán / code / vé máy bay | `guardrails/` covers jailbreak only | **2** |
| Đi cùng người yêu · sang trọng/bình dân · đổi nhiều địa điểm | Already work | — |

## Risk register

| Risk | Severity | Mitigation | Phase |
|---|---|---|---|
| **Big-bang cutover breaks the product** | **High** | Both planes run behind a flag through 5-10; cutover requires Phase 10's eval ≥ committed baseline. Flag stays revertible for one release after Phase 11 | 11 |
| Deleting regex guards loses hard-won knowledge | High | Every guard gets a **test** before its deletion, not after — the behavior is preserved as an assertion even when the code goes. Phase 11 lists them individually | 11 |
| Local model emits invalid JSON patches — and the graph depends on it *more* than the cascade did | High | Strict parse + retry-once + explicit `unparseable` edge to a clarify node. Measured continuously as State Patch Accuracy | 6, 10 |
| `normalize_day_themes` blast radius: CRITICAL, 14 symbols, 10 flows | High | Per-theme marker; absent ⇒ old behavior, *verified correct* for all three callers. Characterization tests first | 1 |
| `select_hotel_candidates` blast radius: CRITICAL, 12 symbols, 10 flows | High | Keyword-only params defaulting to empty; existing 4 call sites untouched | 8 |
| `PostgresSaver.from_conn_string` is a context manager; today's checkpointer is per-session | Medium | App-lifespan singleton, sessions keyed by `thread_id` | 4 |
| Frontend contract drift during the rewrite | Medium | `PlannerChatResponse` shape is frozen for the whole plan. The graph fills the same fields; no client change until after Phase 11 | 5, 11 |
| Two planes coexisting 5→11 reintroduces the bug being fixed | Medium | The legacy plane is **frozen** — no edits to it after Phase 5 except reverts. Time-boxed to one window that Phase 11 closes | 5-11 |
| **An interrupted node re-executes from its start**, so a per-day Python loop containing a shortlist interrupt re-runs completed days — re-searching and silently changing days the user never touched | **High** | Loops with interrupt points are **subgraphs invoked per iteration** (`rebuild_day`), not `for` inside a node. Interrupt-isolation test in Phase 9 step 8 is the proof | 5, 7, 9, 13 |
| Subgraph checkpointer inherited by accident | Medium | `general_qa` and `rebuild_day` compile with an explicitly stated `checkpointer=`; asserted by test | 5, 9 |

## Success Criteria

- [ ] After Phase 11, `grep -r "_run_intake\|decide_route_by_rules\|_ToolAdapter" src/` returns nothing
- [ ] Exactly one code path processes a turn; no tool is invoked outside the graph
- [ ] Every symptom in the mapping table has a regression test failing before its phase, passing after
- [ ] No question is re-asked twice with no state change and no explanation
- [ ] `ALLOWED_PATHS` rejects every out-of-list path, proven by test
- [ ] No filter silently relaxes; zero results always name the binding constraint
- [ ] `make test` green after every phase
- [ ] `eval/` end-to-end ≥ committed `eval/results/baseline.json`, measured at Phase 10 and again after Phase 11

## Diagrams

- [`target-architecture.md`](./target-architecture.md) — the single-plane graph, flows, state layer
- [`capability-map.md`](./capability-map.md) — today's two-plane flow and capability table

## References

- Architecture source: `data/travel_chatbot_langgraph_production_architecture.md`
- Fit assessment: `backend/plans/reports/assessment-260812-0916-langgraph-production-architecture-fit.md`
- Capability audit: `backend/plans/reports/assessment-260812-1018-capability-coverage-gap.md`
- Eval harness (delivered): `plans/260807-1400-ragas-rag-evaluation-harness/`
- LangGraph persistence: https://docs.langchain.com/oss/python/langgraph/persistence
- LangGraph interrupts: https://docs.langchain.com/oss/python/langgraph/interrupts

## Open Questions

1. **Booking — is there a real inventory/availability source?** Blocks the booking plan entirely.
2. **Does the product need multi-user auth now**, or is per-session isolation enough for
   "không cho người khác xem"?
3. Phase 4 rollout: drain live sessions via TTL, or force-reset at deploy?
4. Phase 10 audit storage: new Supabase table, or extend `sessions.context_data`?
5. `MINIMUM_ITEMS_PER_DAY = 7` vs "1 địa điểm 1 ngày" — keep the reuse gate and accept sparse
   days are never template-reusable? (Phase 12 assumes yes.)
6. `repositories/` layer (7 service files call Supabase directly) — separate plan after cutover, or leave as-is?

Decided while planning, recorded so the reasoning is not lost:

| Question | Decision |
|---|---|
| Incremental patch or full rewrite? | **Full rewrite of the orchestration layer**, domain layer kept. User decision after the trade-off was presented twice |
| Does the ReAct agent survive? | **Yes, as a leaf node** for `general_question` with `query_hotel`/`query_hotel_rooms`. It stops being a plane |
| Multi-amenity AND or OR? | **AND**, with a binding-constraint report on zero results — never silent relaxation |
| "4 sao" = stars or review score? | Different columns; both filterable. "N sao" ⇒ stars, "N/10" ⇒ review score, ambiguous ⇒ ask |
| "1-2-2026" fixed rule or ask? | **Ask**, but only when genuinely ambiguous — `31/07` has one valid reading |
| Node or subgraph for each flow? | Pipeline nodes and `hotel_flow` stay nodes. `general_qa` and `rebuild_day` are **subgraphs** — the first already is one (`create_react_agent` returns a compiled graph), the second must be, because an interrupted node re-executes from its start and the per-day loop contains an interrupt |
| Adopt doc §36 folder layout? | **Partially** — `domain/` for new pure files; reject the renames; defer `repositories/` |

<!-- slug: langgraph-orchestration-state-patch-and-interrupts -->
