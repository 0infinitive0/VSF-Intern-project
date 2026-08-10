---
title: "V-OTA AI Chat — PoC Master Roadmap (M1→M3)"
description: "Program-level roadmap sequencing all work from the current state to the Sprint 3 go/no-go, mapped to BRD milestones M1/M2/M3 and business requirements BR-02..BR-10."
status: in-progress
priority: P1
branch: "main"
tags: [roadmap, poc, brd, milestones]
blockedBy: []
blocks: []
created: "2026-07-23T03:44:37.915Z"
createdBy: "ck:plan"
source: skill
---

# V-OTA AI Chat — PoC Master Roadmap (M1→M3)

## Overview

Program-level roadmap from today's state to Demo Day. It sequences the two existing plans and adds the work neither covers. Detail belongs in per-phase plans spawned as each phase starts — this document is the spine, not the implementation spec.

**Authoritative source:** `docs/BRD_V-OTA_AI-Chat_VSF2026_2.pdf` v1.2, 20/07/2026 (9 pages, text extracted 2026-07-23). Milestones §12, business requirements §7, layered design §13.

## Where the project actually stands

Established by reading `src/`, `scripts/`, `data/`, and both compose files on 2026-07-23.

| BRD component (§13.2 L2) | Sprint | State |
|---|---|---|
| Connector OTA (crawl/API) | 1 | **Shipped** — 4 Airflow DAGs, ~4,000 lines, Playwright + OSM/Wikidata |
| Chuẩn hóa dữ liệu (clean, dedup) | 1 | **Shipped** — 7-stage XCom pipeline, category-balanced dedup |
| Kho dữ liệu: CSDL | 1 | **Shipped for M1 corpus** — Postgres has producers for `destinations`, `attractions`, and OTA `hotels`/`rooms`/`room_prices` |
| Kho dữ liệu: chỉ mục vector | 1 | **Absent** — no Qdrant, no embeddings, no client code |
| Điều phối hội thoại | 2 | **Stub** — `src/agents/graph.py`, 29 lines |
| NLU song ngữ VI/EN | 2 | **Absent** — no design doc mentions English at all |
| Sinh trả lời + grounding | 2 | **Stub** — `src/services/llm.py`, 12 lines |
| Tìm kiếm & bộ lọc | 2 | **Absent** |
| Handoff đặt phòng | 2 | **Absent** |
| Web Chat UI | 2 | **Absent** — design comp at `docs/design/v-ota-chat-ui/`, no code |
| Lập lịch trình & tối ưu | 3 | **Absent** |

Sprint 1's data-engineering half is genuinely strong. Everything from the dialog core rightward is unstarted, and Sprint 1 ends ~3 Aug.

## Three findings that shape this roadmap

**1. BO-02 is now met for M1.** The BRD requires ≥1,000 normalized records from ≥2 OTA sources, *queryable*, by end of Sprint 1. `booking_agoda_hotel_loader_pipeline` loads `data/agoda.json` (503) + `data/booking.json` (600) into Postgres: 1,103 hotels, 6,375 rooms, 6,375 room_prices, validated by `plans/260723-1057-merge-data-pipeline-hotel-loader`.

**2. BR-10 (bilingual VI/EN) is mandatory and has zero design coverage.** The BRD marks it *Bắt buộc*, explicitly including mixed-language queries ("tên địa danh/khách sạn tiếng Anh trong câu tiếng Việt"), with replies in the user's active language. `design_proposal.md` never mentions English; the Stitch comp is Vietnamese-only; §13.4 requires a dialog state machine with "nhánh VI/EN". Per user decision, bilingual is first-class from Sprint 2, not retrofitted. It threads through Phases 2, 3, 4 and 5 — it is not a single task.

**3. The vector index is BRD architecture, not optional.** §13.2 L2 specifies "Kho dữ liệu: CSDL + chỉ mục vector" as a Sprint 1 component. Per user decision: **Qdrant**, matching `design_proposal.md` and `data_dictionary.md` §2's `hotels_vector` / `attractions_vector` collections. This settles the docs-consolidation plan's open Qdrant question — it is confirmed architecture, and that plan's "mark as Sprint 2 planned" wording should firm up accordingly.

## Phases

| Phase | Name | Milestone | Status |
|-------|------|-----------|--------|
| 1 | [M1 hotel loader and dataset acceptance](./phase-01-m1-hotel-loader-and-dataset-acceptance.md) | **M1** | Completed |
| 2 | [Semantic search foundation with Qdrant](./phase-02-semantic-search-foundation-with-qdrant.md) | M1→M2 | Pending |
| 3 | [Bilingual conversational core](./phase-03-bilingual-conversational-core.md) | M2 | Pending |
| 4 | [Search, filter and booking handoff](./phase-04-search-filter-and-booking-handoff.md) | M2 | Pending |
| 5 | [Web chat UI](./phase-05-web-chat-ui.md) | M2 | Pending |
| 6 | [M2 gate — end-to-end integration](./phase-06-m2-gate-end-to-end-integration.md) | **M2** | Pending |
| 7 | [Itinerary planning and optimization](./phase-07-itinerary-planning-and-optimization.md) | M3 | Pending |
| 8 | [M3 — evaluation, handover, go/no-go](./phase-08-m3-evaluation-handover-and-go-no-go.md) | **M3** | Pending |

**Critical path:** 1 → 2 → 3 → 4 → 6 → 7 → 8. Phase 5 (UI) runs parallel to 3–4 once Phase 4's API contract is fixed — it is the most parallelisable work and the natural split for a 2-intern team.

**Suggested calendar** (assuming BRD §10's 2-week sprints from ~20 Jul):

| Window | Phases |
|---|---|
| Now → 3 Aug (M1) | 1, start 2 |
| 4 Aug → 17 Aug (M2) | finish 2, then 3 + 4, 5 in parallel, 6 |
| 18 Aug → 31 Aug (M3) | 7, 8 |

## Requirement coverage

Every mandatory BRD requirement maps to a phase. Nothing is silently dropped.

| BR | Requirement | Sprint | Phase |
|----|-------------|--------|-------|
| BR-02 | Legal/ToS-compliant collection | 1 | **Shipped** — `allow_ota_web_scraping` gate, `ScrapeBlockedError`; the missing *written* assessment is Phase 8 |
| BR-03 | Natural-conversation search, VI or EN | 2 | 3, 4 |
| BR-04 | In-conversation refinement (price, stars, amenities, area) | 2 | 4 |
| BR-05 | Seamless search→booking, no context loss | 2 | 4 |
| BR-06 | Personalized itinerary by day/budget/preference, optimized | 3 | 7 |
| BR-07 | All output grounded in real system data | 2–3 | 3 (validation node), 6 (adversarial test) |
| BR-08 | Documentation sufficient for handover | 1–3 | `260723-0910-docs-consolidation-audit`, 8 |
| BR-09 | KPI evaluation + go/no-go recommendation | 3 | 8 |
| BR-10 | Bilingual VI/EN incl. mixed queries | 2–3 | 2, 3, 4, 5 |

Business objectives: BO-01 → Phase 8; BO-02 → Phase 1; BO-03 → Phases 3–4, 7; BO-04 → Phase 4 (≥70% scenarios reach handoff, verified in Phase 6); BO-05 → Phase 8.

## Related plans

| Plan | Relationship |
|---|---|
| `260723-1010-agoda-booking-database-schema` | **Cancelled 2026-07-23**, superseded by `260723-1057-merge-data-pipeline-hotel-loader`. Its `hotel_listings`/`hotel_nearby_places` split was rejected in favor of a flat per-listing `hotels` schema ported alongside a working loader. |
| `260723-1057-merge-data-pipeline-hotel-loader` | **Completed 2026-07-23.** Ports a working, tested Extract→Validate→Normalize→Dedupe→Load pipeline from `github.com/NhatLam71388/data_pipeline_hotel`, targeting a flat `hotels` table (one row per OTA listing). Phase 1's loader deliverable is complete. |
| `260723-0910-docs-consolidation-audit` | Runs alongside; serves BR-08. Two decisions here feed it: Qdrant is confirmed architecture (firms up its validation Q1), and its ERD population-status table gains the hotel tables once Phase 1 lands. |
| `260729-1637-trip-planner-chat-ui-and-agents-backend` | **Opened 2026-07-29.** Delivers the first working slice of Phases 3, 5 and 7 by porting `scripts/poc_trip_planner.py` into `src/agents/` + `src/services/trip_planner.py`, exposing a session-scoped chat API, and shipping a single-column Vite/React chat UI. Deliberately narrower than Phase 5: Vietnamese only, no streaming, no three-panel comp — those remain Phase 5's target and it is not superseded. No blocking relationship; that plan can land independently. |

## Acceptance Criteria

- [x] **M1:** ≥1,000 hotel records from both OTA sources loaded and queryable in Postgres, via a reproducible loader (BO-02).
- [ ] **M2:** A user can search in Vietnamese *or* English, refine in-conversation, and reach a booking handoff carrying full selection context (BR-03, BR-04, BR-05, BR-10).
- [ ] **M2:** ≥70% of defined test scenarios complete through to handoff (BO-04).
- [ ] **M2:** No assistant response asserts a hotel, price, or fact absent from the datastore (BR-07).
- [ ] **M3:** Day-by-day itinerary generated from budget and preferences, tied to real hotel and attraction records (BR-06).
- [ ] **M3:** Test report, known-limitations list, handover package, and an honest go/no-go recommendation (BR-08, BR-09).
- [ ] All 10 Demo Day deliverables point at real project content.

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| **Sprint 2 is the whole product and nothing is started.** Dialog core, search, handoff and UI are all absent with ~2 weeks allotted. | **High** | Phase 5 parallelises to the second intern. Phases 3–4 target a deliberately thin vertical slice — one working query path end-to-end — before breadth. If M2 slips, Phase 6 descopes filters before it descopes grounding. |
| Bilingual doubles NLU and response surface area | High | Built in from Phase 2 (embedding model choice) rather than retrofitted. Phase 6 tests both languages plus mixed queries explicitly. |
| Qdrant adds a second datastore to operate at PoC scale | Medium | Accepted user decision. Phase 2 keeps the SQL keyword-search fallback already specified in `design_proposal.md` §4C, so a Qdrant outage degrades rather than breaks the demo. |
| LLM cost/quota on a PoC budget (BRD §10) | Medium | Phase 3 caps context; embeddings computed once in Phase 2, not per query. Track from Sprint 1 per BRD §11. |
| Grounding failures damage credibility (BRD §11, BR-07) | Medium | Validation node in Phase 3; adversarial testing in Phase 6 before any demo, as BRD §11 requires. |
| 2 interns, part-time mentor, no extension (BRD §10) | Medium | This roadmap doubles as the descope order: Phase 7 before Phase 8, filters before grounding. Cutting is expected; cutting *silently* is not. |

## Open Questions

1. **Actual sprint dates.** BRD §10 flags the 2-week cadence as an assumption "cần xác nhận", confirmed by the mentor at kick-off. The calendar above is derived, not authoritative.
2. **Was BR-10 verbally descoped?** Its total absence from the design docs is conspicuous. Worth confirming with the mentor — if descoped, Phases 2–5 simplify substantially.
3. **Booking handoff target.** BR-05 requires handoff "kèm ngữ cảnh", but §4 puts the booking engine out of scope. Deep-link to the source OTA URL (`hotels.source_url` stores the per-listing OTA URL), or a stub V-OTA page? Affects Phase 4.
4. **KPI thresholds.** BRD §3 and §9 defer exact numbers to kick-off ("ban điều hành/mentor chốt lại tại kick-off"). Phase 8 cannot report against unset targets.
5. **Team roster.** BRD §5 names Đinh Nguyễn Nhật Lâm and Nguyễn Hữu Đức; `sprint1_weekly_plan.md` still has unfilled owner placeholders. Phase ownership assumes two implementers.
