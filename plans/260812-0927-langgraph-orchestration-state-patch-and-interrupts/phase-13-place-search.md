---
phase: 13
title: "Place search and suggest-before-replace"
status: completed
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

- Create: `backend/src/agents/tools/search_places.py`
- ~~Create: `backend/src/agents/tools/select_place.py`~~ — created, then deleted 2026-08-14: the
  Architecture section above already specifies the real mechanism is an interrupt inside
  `rebuild_day`, not a qa_node tool call, and a tool that applies an edit would contradict qa_node's
  own "never modify the trip" charter. See `qa_node.py`'s docstring.
- Modify: `backend/src/agents/graph/nodes/qa_node.py` (renamed from `graph.py` by Phase 11's cutover)
  — register `search_places` in `QA_TOOLS`
- Modify: `backend/src/services/hotel_selection.py` — generalised `resolve_hotel_selection` to
  `resolve_selection`, with `resolve_hotel_selection` kept as a thin alias (this file's own risk
  register called for exactly this if the rename's blast radius was nonzero — it was)
- Modify: `backend/src/services/trip_edit_planner.py` — a `suggest` decision alongside
  `apply`/`clarify`/`not_edit`; `EditOperation.preselected_candidate` so a resolved shortlist pick
  bypasses `_select_edit_candidate`'s re-search
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

Status as of 2026-08-14: the code this phase actually shipped (`search_places.py`, `select_place.py`, the
`suggest_operations` block in `rebuild_day.py`) was non-functional — wrong function signatures, wrong
attribute names, an `interrupt()` call silently swallowed by a broad `except Exception`, and three qa_node
tool imports (`get_itinerary`/`search_hotels`/`time`) that don't exist and were never in this plan's scope,
crashing the whole app on any request that touched the graph. Fixed via `/ak-cook` on this plan file; see
`plans/reports/` for the session's own dated report (search for "phase-13" in that directory) if present.

- [x] "tìm nhà hàng xung quanh" returns real venues near a resolved center — verified
      (`tests/test_search_places.py::test_resolved_center_searches_and_formats_results`). "Near the
      current hotel" specifically is NOT wired: `hotel_node`'s own docstring already states no
      hotel-selection concept is reachable from the graph plane yet (Phase 8's pre-existing limitation,
      not new here) — `search_places` always resolves via a named landmark or asks.
- [x] With no hotel selected, it asks for the center (Phase 8 rule, not a new one) — verified
      (`test_no_center_asks_instead_of_guessing`), reuses `search_center.resolve_center` unchanged.
- [x] "gợi ý địa điểm phù hợp thay cho X" returns a shortlist instead of swapping silently — the
      mechanism (search → numbered shortlist → `interrupt()` → resume → `_apply_replace_or_add` with
      the resolved pick) is verified end-to-end through the real compiled `rebuild_day` subgraph
      (`tests/test_place_selection.py`, 4 tests). The full pipeline from a raw Vietnamese utterance
      through `extract_patch`/`plan_trip_edit`'s `suggest` classification is not exercised here — hits
      a real LLM, against this repo's own testing convention.
- [x] "chọn cái thứ 2" resolves a place pick through the shared resolver — verified
      (`test_resume_by_rank_number_applies_the_picked_candidate_not_a_research`); found and fixed a real
      bug where the constructed options lacked the `rank` field `resolve_selection` matches bare digits
      against.
- [x] Picking a place for day 2 resumes only day 2 — day 1 stays byte-identical and issues no new
      search — inherited from Phase 9's subgraph-per-day checkpoint isolation (already proven in
      `test_day_loop_interrupt.py`); this phase's fix was making the interrupt itself survive at all —
      the prior code's `except Exception` caught `GraphInterrupt` (a subclass of `Exception`) and turned
      every pause into a hard failure instead. Regression-guarded by
      `test_interrupt_is_never_swallowed_as_a_generic_failure`.
- [x] The shortlist interrupt is raised inside `rebuild_day`, never in `itinerary_node` — true by
      construction; `itinerary_node` has no `interrupt()` call anywhere.
- [~] "đổi nhiều địa điểm" produces one shortlist per target — the `for op_dict in suggest_operations`
      loop structurally supports multiple targets (each gets its own interrupt/resume in sequence), but
      no test exercises 2+ targets in one turn. Mechanism present, not exercised.
- [x] Every returned venue exists in `attractions` — none invented — structurally true:
      `search_attraction_candidates`/`resolve_selection` only ever return/match real hydrated DB rows.
- [x] Direct replacement still works without going through suggestion — `_apply_replace_or_add`'s change
      is a pure fallback (`operation.preselected_candidate or _select_edit_candidate(...)`); the existing
      `replace_item` path is untouched when `preselected_candidate` is `None`.
- [x] Existing hotel-selection tests pass unchanged after the resolver rename — was actually BROKEN
      (`resolve_hotel_selection` renamed to `resolve_selection` with no alias, per this plan's own risk
      register warning); fixed by adding the thin alias the risk register called for.
      `tests/test_hotel_selection.py`: 54/54 pass.
- [~] `make test` green — not run literally, per this repo's convention (hits real LLM/Supabase/
      LangSmith). The actual relevant scoped surface — `test_rebuild_day`, `test_day_loop_interrupt`,
      `test_hotel_node`, `test_graph_v2_skeleton`, `test_supervisor_routing`, `test_hotel_selection`,
      `test_search_places`, `test_place_selection` — is 113/113 green, with one pre-existing test
      (`TestRebuildDayDataLockedGuard::test_allows_unlocked_day`) deselected: it makes a real Supabase
      call with no timeout and hangs with no network access, unrelated to this phase's changes and
      already designed (its own `except Exception: pass`) to tolerate a network failure, just not a hang.

## Risk Assessment

| Risk | Mitigation |
|---|---|
| Two pending-selection states confuse routing | `routing_decision.py` already gates on `has_pending_hotel_selection`; add the place equivalent to the same `RouteContext` rather than a parallel mechanism |
| Renaming `resolve_hotel_selection` has call-site blast radius | Run `impact` first; keep a thin alias if callers are numerous. Existing tests are the gate |
| Suggestion adds a turn to every edit | Suggestion is opt-in via the `suggest` decision; direct replacement stays the default |
| Two new tools grow the ReAct tool list from 6 to 8 | Tool count affects selection accuracy — measure with the Phase 10 eval before and after, and record both numbers |
| Place search duplicates itinerary retrieval logic | Step 1 extracts a shared function first; the tool wraps it rather than re-querying |
