---
phase: 13
title: "Place search and suggest-before-replace"
status: pending
priority: P2
effort: "2d"
dependencies: [8, 11]
---

# Phase 13: Place search and suggest-before-replace

## Overview

Make places searchable on demand ("tìm nhà hàng xung quanh") and let the user pick from
suggestions before a place is swapped, instead of the system choosing silently.

## Problem

**Places are not searchable.** Restaurants exist only as fixed meal-slot queries buried inside
itinerary construction — `trip_planner.py:334-374` and `:642-678` build
`"local restaurant lunch Vietnamese food in {destination}"` and friends. There is no
user-facing place search. Only hotels can be searched on demand.

Doc §22 names `search_places` / `get_place_details` as core tools; the project has neither.

**Replacement is silent.** `replace_item` picks a venue and applies it. There is no
"here are 3 options, pick one" flow for places — hotels are the only entity with a selection
list (`pending_hotel_selection` → `select_hotel`). So "gợi ý địa điểm phù hợp" has no path:
the user gets a decision, never a choice.

## Requirements

- Functional: "tìm nhà hàng xung quanh" returns real venues near a resolved center.
- Functional: center resolution reuses Phase 8's rule — current hotel, else a named place,
  else ask. No second center implementation.
- Functional: "gợi ý địa điểm phù hợp" returns a ranked shortlist the user picks from.
- Functional: a picked suggestion applies through the existing `replace_item` / `add_item`
  operations — the edit path is unchanged, only the choice becomes explicit.
- Functional: "đổi nhiều địa điểm" resolves each target to its own shortlist.
- Non-functional: no venue is invented. Results come from the `attractions` table only,
  the same grounding rule the edit planner already enforces
  (*"Never invent an item_id, venue UUID, venue name, hours, coordinates"*).
- Non-functional: direct replacement stays available — suggestion is an added mode, not a
  mandatory extra turn.

## Architecture

New tool `search_places(query, near, category, limit)` in `backend/src/agents/tools/`,
following the established module-level `ToolRuntime`/`Command` shape used by the other six
tools. It wraps the existing `_search_attraction_candidates` / `supabase_search` path — the
retrieval layer already exists and already supports radius; only the user-facing surface is new.

### The shortlist interrupt lives inside `rebuild_day`

`select_place` is a user interaction, so it is an `interrupt()` point — and it sits **inside the
per-day loop**. Phase 9 already made `rebuild_day` a subgraph precisely so this works: picking a
place for day 2 resumes only day 2's subgraph, leaving day 1 checkpointed and untouched.

Do not add the shortlist to `itinerary_node` (the worker node that selects affected days). An interrupt
there re-executes day selection and `plan_trip_edit` on resume — a wasted LLM call, and a second
`plan_trip_edit` run can legitimately return different operations, silently changing the edit
the user already saw.

Suggestion flow reuses the hotel pattern rather than inventing a parallel one:

| Hotels (exists) | Places (new) |
|---|---|
| `pending_hotel_selection` | `pending_place_selection` |
| `select_hotel(selection)` | `select_place(selection)` |
| `resolve_hotel_selection` (rank number → id) | reuse the same resolver |

`resolve_hotel_selection` (`hotel_selection.py:343`) is already generic over
`(data, candidate)` tuples and resolves by ID, rank number, or name substring. Generalise its
name and reuse it — do not write a second resolver. This also means "chọn cái thứ 2" works for
places for free, satisfying doc §11 for a second entity type.

## Related Code Files

- Create: `backend/src/agents/tools/search_places.py`, `backend/src/agents/tools/select_place.py`
- Modify: `backend/src/agents/graph.py` — register the new tools in `_AGENT_TOOLS`
- Modify: `backend/src/services/hotel_selection.py` — generalise `resolve_hotel_selection` naming
- Modify: `backend/src/agents/state.py` — `pending_place_selection`
- Modify: `backend/src/services/trip_edit_planner.py` — a `suggest` decision alongside `apply`/`clarify`/`not_edit`
- Create: `backend/tests/test_search_places.py`, `backend/tests/test_place_selection.py`

## Implementation Steps

1. Extract the place-retrieval call already used by itinerary building into a reusable service
   function; do not duplicate the query construction.
2. Build `search_places` on top of it, with the Phase 8 center resolver.
3. Add `pending_place_selection` to `TripState`.
4. Generalise the selection resolver; verify hotel selection tests still pass unchanged.
5. Add `select_place`, applying the pick through existing `replace_item` / `add_item`.
6. Add the `suggest` decision to the edit planner for "gợi ý địa điểm phù hợp".
7. Support multi-target: each replaced item gets its own shortlist, resolved in order.
8. Register both tools with the ReAct agent and update the supervisor prompt.

## Success Criteria

- [ ] "tìm nhà hàng xung quanh" returns real venues near the current hotel
- [ ] With no hotel selected, it asks for the center (Phase 8 rule, not a new one)
- [ ] "gợi ý địa điểm phù hợp thay cho X" returns a shortlist instead of swapping silently
- [ ] "chọn cái thứ 2" resolves a place pick through the shared resolver
- [ ] Picking a place for day 2 resumes only day 2 — day 1 stays byte-identical and issues no new search
- [ ] The shortlist interrupt is raised inside `rebuild_day`, never in `itinerary_node`
- [ ] "đổi nhiều địa điểm" produces one shortlist per target
- [ ] Every returned venue exists in `attractions` — none invented
- [ ] Direct replacement still works without going through suggestion
- [ ] Existing hotel-selection tests pass unchanged after the resolver rename
- [ ] `make test` green

## Risk Assessment

| Risk | Mitigation |
|---|---|
| Two pending-selection states confuse routing | `routing_decision.py` already gates on `has_pending_hotel_selection`; add the place equivalent to the same `RouteContext` rather than a parallel mechanism |
| Renaming `resolve_hotel_selection` has call-site blast radius | Run `impact` first; keep a thin alias if callers are numerous. Existing tests are the gate |
| Suggestion adds a turn to every edit | Suggestion is opt-in via the `suggest` decision; direct replacement stays the default |
| Two new tools grow the ReAct tool list from 6 to 8 | Tool count affects selection accuracy — measure with the Phase 10 eval before and after, and record both numbers |
| Place search duplicates itinerary retrieval logic | Step 1 extracts a shared function first; the tool wraps it rather than re-querying |
