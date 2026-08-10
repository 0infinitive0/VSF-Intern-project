---
phase: 4
title: "Search, filter and booking handoff"
status: pending
priority: P1
dependencies: [3]
effort: ""
---

# Phase 4: Search, filter and booking handoff

## Overview

The business services layer: in-conversation filtering (BR-04) and a booking handoff that carries full selection context (BR-05). Together with Phase 3 these close M2's functional scope.

## Requirements

- Functional: refine by price, star rating, amenities, and area *within* the conversation, without restarting (BR-04).
- Functional: filters are cumulative and individually removable ("rẻ hơn" then "có hồ bơi" applies both).
- Functional: handoff to booking preserves hotel, room, dates, and guest count (BR-05).
- Functional: ≥70% of test scenarios reach handoff (BO-04).
- Non-functional: filter round-trip fast enough to feel conversational.

## Architecture

**Filters are structured state, not free text.** Phase 3's state carries an active filter set; this phase makes it queryable. Per Phase 2's decision, vector search produces semantically ranked candidate IDs and Postgres applies structured constraints — which is why per-listing fidelity matters: price and room data live on `rooms`/`room_prices`, keyed to the flat, per-OTA-listing `hotels` row (see `plans/260723-1057-merge-data-pipeline-hotel-loader`), not a merged physical-property row.

**Filter vocabulary must be bilingual.** "hồ bơi" and "swimming pool" must resolve to the same amenity, in both directions. Amenity values in the corpus are themselves mixed-language, so normalise to a canonical set at Phase 1 load time if possible, or maintain a synonym map here. Prefer the former — normalising once at load beats resolving on every query.

**Booking handoff — open question, decide before building.** BR-05 requires handoff "kèm ngữ cảnh", but BRD §4 puts a real booking engine out of scope. Options: deep-link to the source OTA (`hotels.source_url` stores the per-listing OTA URL, and `room_prices.source_url` can override it for a room/price package), or a stub V-OTA page rendering the carried context. The deep-link is more honest for a PoC and requires no new surface — the context is preserved in the URL and the summary shown before departure. Confirm with the mentor; this is roadmap Open Question 3.

**"On your trip" / Room Badging** (`design_proposal.md` §3A) is a ranking concern that belongs here, not in the UI: the backend selects the optimal room and flags it; Phase 5 renders the badge.

## Related Code Files

- Create: `src/services/filters.py`, `src/services/booking_handoff.py`
- Create: `src/agents/tools/filter_tool.py`
- Modify: `src/services/search.py` (accept structured filters), `src/agents/graph.py` (refine route), `src/api/routes.py` (handoff endpoint), `src/models/schemas.py`
- Read only: `scripts/database_schema.sql` (post-schema-plan), `design_proposal.md` §3A

## Implementation Steps

1. **Define the filter contract** in `schemas.py`: price range, star rating, amenities, area, guest capacity. This is also Phase 5's API contract — fix it early so UI work can start in parallel.
2. **Build the bilingual amenity vocabulary.** Extract the real amenity values from both corpora, cluster VI/EN equivalents, and canonicalise. Do not hand-write the list from imagination — derive it from the data.
3. **Implement filter application** against Postgres over the vector-search candidate IDs, preserving semantic rank order within the filtered set.
4. **Add the refine route to the graph:** parse a refinement utterance, merge into active filters, re-run search, respond with the narrowed set. Support removal ("bỏ giới hạn giá").
5. **Implement room badging** — select the best-value room per hotel against the active constraints and flag it.
6. **Implement booking handoff:** assemble hotel, room, dates, and guests into a handoff payload; resolve the target per the decision above; persist the event so Phase 6 can measure BO-04.
7. **Define the test scenario set** for BO-04's ≥70% threshold — a written list of representative journeys in both languages. Phase 6 executes it; without the list there is nothing to measure.

## Success Criteria

- [ ] Filters apply cumulatively and can be individually removed, in conversation.
- [ ] Filter terms resolve equivalently in Vietnamese and English.
- [ ] Handoff carries hotel, room, dates, and guest count with no context loss.
- [ ] Handoff target decision recorded (deep-link vs stub) with rationale.
- [ ] Room badging selects and flags one room per hotel.
- [ ] Test scenario set written and countable.

## Risk Assessment

- **Risk:** Amenity values are too inconsistent across OTAs to normalise cleanly.
  **Mitigation:** Step 2 derives from real data. If clustering is poor, restrict the demoed filter vocabulary to amenities that *are* clean and say so, rather than shipping a filter that silently misses matches.
- **Risk:** Handoff decision is deferred and blocks the phase.
  **Mitigation:** Raise it at the next mentor review. Deep-linking is the low-risk default and needs no new UI.
- **Risk:** BO-04's 70% is measured against a scenario set written to be easy.
  **Mitigation:** Write the set in step 7 *before* the implementation is tuned, and include known-hard cases. A self-graded metric with a self-chosen test set is worth little at go/no-go.
- **Risk:** Filtering over vector candidates over-filters — the top-N semantic set may contain nothing matching a narrow constraint.
  **Mitigation:** Widen candidate N when filters are restrictive, or fall back to filter-first-then-rank. Detect the empty-result case and offer to relax a constraint rather than replying "no results".
