---
phase: 5
title: "Web chat UI"
status: pending
priority: P1
dependencies: [4]
effort: ""
---

# Phase 5: Web chat UI

## Overview

Build the three-panel React chat interface from the existing design comp. **This is the parallel track** — once Phase 4 fixes the API contract, this runs alongside Phases 3–4 rather than after them, which is the natural work split for a 2-intern team and the main lever against Sprint 2's schedule risk.

Dependency on Phase 4 is contract-only, not implementation: agree the request/response schemas early and build against mocks.

## Requirements

- Functional: three-panel layout per `docs/wireframe_web.png` and the generated comp.
- Functional: streaming assistant responses.
- Functional: hotel result cards with images, AI reasoning lines, prices, and the "Gợi ý cho bạn" badge.
- Functional: live-updating trip checklist (progressive profiling) and itinerary timeline.
- Functional: **all UI copy in both Vietnamese and English**, following the conversation language (BR-10).
- Non-functional: responsive — the comp is desktop-only and needs breakpoints added by hand.

## Architecture

**Design assets already exist**, produced 2026-07-23:

| Asset | Path |
|---|---|
| Tailwind HTML export | `docs/design/v-ota-chat-ui/design.html` |
| Full 3-panel render | `docs/design/v-ota-chat-ui/design-rendered-1600w.png` |
| Design spec + palette | `docs/design/v-ota-chat-ui/DESIGN.md` |
| Desktop wireframe | `docs/wireframe_web.png` |
| Mobile direction | `docs/wireframe.png` |

`DESIGN.md` carries the Material-3 token palette (primary `#00342b`, secondary `#fed65b`) and the realised feature list. **Three caveats recorded there:** the comp is desktop-only with no breakpoints; it loads Tailwind CDN, Google Fonts, and Google-hosted placeholder images that must be replaced; and it covers no loading, error, or empty states.

**Stack:** Vite + React + CSS Modules per `design_proposal.md` §1. Note the conflict — `docs/architecture_diagram.md` says Next.js, but that file is unmodified AI20K template boilerplate and is being corrected by the docs-consolidation plan (finding F2). Follow `design_proposal.md`.

**Bilingual UI is not an afterthought.** Every label, placeholder, pill, and empty-state string needs both languages, switching with the conversation. Use an i18n structure from the first component; retrofitting string extraction across a built UI is expensive and is precisely the trap BR-10's absence from the design docs sets.

**Not in the comp, still required:** loading states (`design_proposal.md` §3A specifies engaging loading copy — "Đang tìm kiếm phòng Vinpearl giá tốt nhất..."), error and empty states, and the Rich Media Modal for hotel cards.

## Related Code Files

- Create: `frontend/` — Vite + React app (panels, message list, hotel carousel, trip checklist, itinerary timeline, composer)
- Create: `frontend/src/i18n/` — VI/EN string catalogues
- Read only: `docs/design/v-ota-chat-ui/*`, `design_proposal.md` §3
- Modify: `src/api/routes.py` (CORS), `docs/SETUP_GUIDE.md` (frontend run instructions)

## Implementation Steps

1. **Agree the API contract with Phase 4 and freeze it.** This is the gate that lets the two tracks proceed independently — do it first, write it down, build against mocks.
2. **Scaffold Vite + React**, extracting the design tokens from `DESIGN.md` into CSS custom properties.
3. **Set up i18n before building components**, with both catalogues wired to the conversation language.
4. **Build the three-panel shell** with responsive breakpoints — the comp is desktop-only, so mobile behaviour is a decision to make, not a design to copy (`docs/wireframe.png` shows the mobile direction).
5. **Build the chat thread** with streaming rendering and the AI/user message treatments.
6. **Build the hotel carousel**: images, star rating, VND price, italic AI reasoning line, badge. Replace the comp's Google-hosted placeholder images with real `hotels.images` data.
7. **Build the trip checklist** bound to Phase 3's five profiling slots, revealing the "Tạo lịch trình" CTA when complete.
8. **Build the itinerary timeline** (Phase 7 supplies data; render an empty state until then).
9. **Add loading, error, and empty states** — absent from the comp, and the loading copy is a specified feature.
10. **Wire to the real API**, replacing mocks.

## Success Criteria

- [ ] Three-panel layout matches the comp at desktop width and degrades sensibly below it.
- [x] Assistant responses stream visibly. Shipped 07/08/2026 (plan [`260806-1602-streaming-chat-messages`](../260806-1602-streaming-chat-messages/plan.md), Phase 5) — `message-bubble.tsx` renders a growing bubble with a blinking cursor as `delta` frames arrive, with a growing `turn-phases.tsx` step list for turns that don't stream tokens (intake/hotel-search/finalize branches) and automatic downgrade to `POST /planner_chat` when SSE is unavailable.
- [ ] Hotel cards render real data including reasoning line and badge.
- [ ] Trip checklist updates live as slots fill.
- [ ] Every UI string renders in both VI and EN, following conversation language.
- [ ] Loading, error, and empty states exist.
- [ ] No Google-hosted placeholder images or CDN-only assets remain.

## Risk Assessment

- **Risk:** The API contract shifts and invalidates parallel UI work — the main hazard of parallelising.
  **Mitigation:** Step 1 freezes it. Changes after the freeze go through both tracks deliberately.
- **Risk:** i18n retrofit late in the phase.
  **Mitigation:** Step 3 precedes all component work. Non-negotiable ordering.
- **Risk:** Comp fidelity is chased at the expense of function.
  **Mitigation:** The comp is a proposal, not a spec. Working bilingual search beats pixel-perfect panels; descope visual polish before function.
- **Risk:** No frontend exists at all, so this is a from-zero build in a compressed sprint.
  **Mitigation:** `design.html` is usable Tailwind markup — port it rather than designing from scratch. It is the largest single accelerator available to this phase.
