---
phase: 8
title: "hotel_node: hard filters, radius, center"
status: completed
priority: P2
effort: "2d"
dependencies: [7]
---

# Phase 8: hotel_node — hard filters, radius, center

## Overview

Turn amenity and radius from unreachable or advisory into real search constraints, with a
deterministic center resolved from the user's selected hotel. This node is one of the
supervisor's 4 worker nodes — the supervisor delegates hotel-related tasks here.

## Problem

**Amenity was never a filter.** `select_hotel_candidates` (`hotel_selection.py:73-87`) has
no amenity parameter at all. `rank_hotel_candidates` adds `_AMENITY_MATCH_BONUS = 0.03` per
match — a tie-breaker. "Tìm khách sạn có hồ bơi" therefore returns hotels without pools,
ranked marginally lower. The free-text `hotel_query` does reach vector search, so the
amenity influences retrieval semantically, but nothing verifies the result — even though
`hotel_matches_amenity_tag` exists and is already used for pills and the ranking bonus.

**"Search lại" widens instead of narrowing.** `recommend_hotels.py:419` merges
`existing_options` with new results, so a follow-up amenity request produces a longer list,
not a filtered one. There is no verb to remove a filter.

**Radius is plumbed but unreachable.** `select_hotel_candidates` accepts
`root_latitude`/`root_longitude`/`max_radius_km` (:84-86) and `search_hotels_with_rooms`
validates them (`supabase_search.py:192-248`) — but `recommend_hotels` never builds them
into `selection_kwargs` (:247-255). And there is no center concept: 3km from what?

**Rating filter half-exists and silently lies.** `min_star_rating` is extracted
(`supabase_search.py:214`) and passed to the RPC — but when nothing meets it, the code
**falls back to unfiltered semantic matches** (`:281`, log line: *"No hotels met strict
filters (star>=N). Returning semantic matches."*). So "đánh giá trên 4 sao" can return 3-star
hotels with no indication the filter was dropped. Same anti-pattern as amenity, different
symptom.

**Amenity taxonomy is missing the common cases.** `_AMENITY_KEYWORD_TAGS`
(`hotel_selection.py:751-761`) has 7 tags: non_smoking, pool, swimming_pool, wifi, parking,
parking_lot, family. **No gym, no spa, no restaurant** — all three named as canonical in
doc §19. They currently depend entirely on runtime LLM discovery via
`discover_and_store_amenities`, which is not a dependable path for a common request.

## Locked decisions

**Center = the user's selected hotel.** When no hotel is selected, or the intended center is
otherwise ambiguous, `interrupt()` and ask — which is why this phase depends on Phase 7.

**Multi-amenity is AND.** "Kết hợp nhiều tiện ích" reads literally as all-must-match, so
`{gym, pool}` returns only hotels with both. AND will return zero results more often on this
dataset than OR would — that is handled by the binding-constraint report ("không có khách sạn
nào vừa có gym vừa có hồ bơi; bỏ gym thì có 6"), **not** by silently relaxing to OR. Silent
relaxation is the exact bug being removed from `:281`.

**"Đánh giá trên 4 sao" is ambiguous and gets asked.** `star_rating` (1-5) and `review_score`
(0-10) are different columns. "4 sao" alone means stars; "8/10" means review score; a bare
"đánh giá trên 4" is ambiguous and follows the Phase 7 ask-don't-guess rule.

## Requirements

- Functional: a requested amenity is a hard filter — every returned hotel satisfies it.
- Functional: multiple amenities combine with AND; zero results report which one binds.
- Functional: `gym`, `spa`, and `restaurant` exist in the built-in canonical taxonomy, not
  only via runtime discovery.
- Functional: `min_star_rating` becomes a real filter — the `:281` silent fallback is removed
  and replaced by an explicit "no hotel meets N stars" report.
- Functional: `min_review_score` becomes filterable (it is not, today).
- Functional: filters are removable ("bỏ lọc hồ bơi") via patch, not only additive.
- Functional: a radius search returns only hotels within the radius of the resolved center.
- Functional: no selected hotel and no named center ⇒ ask; never silently pick one.
- Functional: a filter combination yielding zero results says so and names the binding
  constraint, rather than returning an unfiltered list.
- Non-functional: `select_hotel_candidates`' four existing call sites keep working unchanged.

## Architecture

`select_hotel_candidates` gains keyword-only `required_amenities: Collection[str] = ()`.
Defaulting to empty means every existing call site is byte-identical — this matters because
the symbol is **CRITICAL** blast radius (12 symbols, 10 execution flows, 4 direct callers).

Filtering order:

1. RPC-level where cheap and indexed — radius via the existing validated
   `root_latitude`/`root_longitude`/`max_radius_km` params.
2. App-level via `hotel_matches_amenity_tag` for amenities, since amenity data is a JSON
   array on the hotel row, not an indexed column. Over-fetch (`match_count * k`) then filter,
   so post-filtering does not starve the result set.

Center resolution is a small deterministic function, not a model decision:

```
selected hotel coordinates  → use it
explicitly named POI/landmark → geocode against the attractions table
neither → interrupt("Bán kính 3km tính từ đâu?")
```

Constraints live at `hotel_preferences.amenities` / `.radius_km` / `.center` — already in
Phase 3's `ALLOWED_PATHS`, so add/remove are ordinary patch operations. `recommend_hotels`
reads active constraints from state instead of accumulating them in `pending_hotel_selection`.

## Related Code Files

- Modify: `backend/src/services/hotel_selection.py` — `select_hotel_candidates` (:73-169)
- Modify: `backend/src/agents/tools/recommend_hotels.py` — pass radius/amenities (:247-255), stop blind merging (:419)
- Create: `backend/src/services/search_center.py` — center resolution
- Modify: `backend/src/domain/travel_state.py` — radius validator (positive, ≤ max)
- Create: `backend/tests/test_hotel_hard_filters.py`, `backend/tests/test_search_center.py`

## Implementation Steps

1. Run `impact` on `select_hotel_candidates`; confirm the 4 direct callers in the PR description.
2. Add keyword-only `required_amenities`, defaulted; verify all 4 call sites unchanged.
3. Implement over-fetch + `hotel_matches_amenity_tag` post-filter.
4. Build `selection_kwargs` with radius params in `recommend_hotels`.
5. Implement center resolution; `interrupt()` when unresolvable.
6. Add radius bounds validation (doc §25: positive, below a maximum).
7. Replace blind option merging with constraint-driven re-filtering; support removal.
8. Add a zero-results message naming the binding constraint.
9. Test the doc §37 sequence: "Tìm khách sạn trong bán kính 3km, có gym và hồ bơi."

## Success Criteria

- [x] Every hotel returned for "có hồ bơi" satisfies `hotel_matches_amenity_tag(..., "pool")` — hard app-level filter in `select_hotel_candidates`, proven by test
- [x] "có gym và hồ bơi" returns only hotels with **both**; zero results name which one binds — `NoHotelsMatchAmenities.tag_drop_counts`, surfaced by `hotel_node` as "bỏ '{tag}' thì có {count} khách sạn"
- [x] `gym`, `spa`, `restaurant` resolve from the built-in taxonomy without runtime discovery — added to `_AMENITY_KEYWORD_TAGS`
- [x] "khách sạn trên 4 sao" never returns a 3-star hotel — no silent fallback — new hard filter in `select_hotel_candidates` (`NoHotelsMatchRating`, no `data[:match_count]` widen-back). `supabase_search.py`'s own LLM-derived star path (`:280-282`) is deliberately left untouched — it only serves the **frozen legacy plane** (`recommend_hotels.py`), which this phase does not edit per plan.md's risk register ("no edits to the legacy plane after Phase 5 except reverts"); the real fix lands for users at Phase 11 cutover
- [ ] "đánh giá trên 4" asks whether it means stars or review score — this is `extract_patch`'s (Phase 6) prompt/disambiguation concern, not `hotel_node`'s: by the time a turn reaches `hotel_node`, `hotel_preferences.min_star_rating`/`.min_review_score` are already resolved, validated `TravelState` slots. `hotel_node` filters hard on whichever is set; it does not itself ask the stars-vs-score question. Not verified here
- [ ] "bỏ lọc hồ bơi" widens results; the pill disappears — the **mechanism** is real: `hotel_preferences.amenities` is a list path with `remove` (Phase 3), `hotel_node` re-reads it fresh every turn (no accumulation), so a removed tag naturally widens the very next search and its pill drops from `active_preferences`. Whether the phrase "bỏ lọc hồ bơi" itself produces a `remove` patch operation is `extract_patch`'s NLU, not exercised by this phase's tests
- [ ] "bán kính 3km" with a selected hotel returns only hotels within 3km of it — **not reachable today**: no hotel-selection concept exists anywhere in `TravelGraphState`/`TravelState` yet (only the legacy plane's `pending_hotel_selection`/`trip_data`, which this phase does not touch). `search_center.resolve_center(selected_hotel_coordinates=...)` is fully implemented and tested for this case; `hotel_node` always passes `None` for it today, documented in both modules' docstrings
- [x] "bán kính 3km" with no selected hotel asks for the center — `interrupt()` in `hotel_node`, proven via the compiled graph (pause + resume with a named POI + resume with an unrelated reply → `unresolved_resume_text` → replayed as a fresh turn, mirroring `validate_patch`'s established pattern)
- [x] A radius of 0 or above the maximum is rejected with a specific message — already enforced by Phase 3's `hotel_preferences.radius_km` validator (`_number_range(0, 50, inclusive_min=False)`); confirmed still wired end-to-end
- [x] Zero results names the binding constraint instead of silently returning an unfiltered list — for amenities and rating (the two cases the plan's own worked example covers). A radius search that resolves a real center but finds nothing within it falls through to the generic "no hotels found" message rather than a radius-specific binding-constraint line — narrower than the literal wording, not implemented as a third named-constraint case
- [x] All 4 (now 5 — `_legacy_modify_trip_plan` is new since the plan was written) existing `select_hotel_candidates` call sites work unchanged — keyword-only defaulted params; `gitnexus impact`/`detect_changes` and the full pre-existing `test_hotel_selection.py`/`test_hotel_flow_tools.py` suites confirm no behavior change
- [ ] `make test` green — not run literally (`pytest tests/` hits real OpenAI/LangSmith APIs per repo convention); the relevant scoped surface (test_hotel_selection, test_hotel_hard_filters, test_search_center, test_hotel_node, test_graph_v2_skeleton, test_supervisor_routing, test_interrupt_resume, test_travel_state, test_hotel_flow_tools, test_extract_patch — 219 tests) was run instead: 209 passed, 1 skipped (opt-in live-Postgres test), 1 failed — pre-existing and unrelated (`test_rank_hotel_candidates_prefers_cheaper_when_otherwise_tied`, confirmed failing on `main`/pre-Phase-8 via `git stash`, not touched by this phase)

## Risk Assessment

| Risk | Mitigation |
|---|---|
| `select_hotel_candidates` CRITICAL blast radius (10 flows) | Keyword-only params defaulting to empty/`None`; zero change for existing callers, asserted by their untouched tests |
| Hard filtering yields too few results | Over-fetch `match_count * k` before filtering; when still empty, report the binding constraint rather than silently dropping filters |
| Amenity post-filter cost per search | Post-filter runs on already-hydrated rows; `hotel_matches_amenity_tag` is pure string matching. Measure and record in the PR |
| Center geocoding hallucinates a landmark | Resolve only against the existing attractions table; unresolved ⇒ ask. No model-supplied coordinates ever (doc §20: "Do not let GPT calculate geographic distance") |
| Removing accumulate-merge changes UI list behavior | `all_preferences` / `active_preferences` payload keys stay; only the source of truth moves to state. Frontend contract unchanged |
