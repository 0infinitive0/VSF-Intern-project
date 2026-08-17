---
phase: 17
title: "Derive the response payload from graph state"
status: completed
priority: P1
effort: "1.5d"
dependencies: [11, 15]
---

# Phase 17: Derive the response payload from graph state

## Overview

Six fields of `PlannerChatResponse` are still Phase-5 placeholders that `respond` hardcodes.
Each one has a live frontend consumer that silently gets a constant. This phase derives every
one of them from state the graph already holds — or proves the field is dead and says so.

## Problem

`respond.py:213-228` builds the frozen response shape, and six of its fields never vary:

```python
"suggestions": [],
"stage": "intake",
"requires_stay_dates": False,
"compound_min_price": None,
"compound_max_price": None,
"all_preferences": [],
"active_preferences": [],
```

The node's docstring justifies this as a Phase-5 placeholder because
*"hotel_node/itinerary_node don't produce real trip data until Phases 8-9"*. Phases 8, 9 and 11
are complete. The precondition expired; the constants did not.

### The reported symptom

User states destination, dates, people and budget in one message; backend replies "Mình tìm
được 5 khách sạn phù hợp."; the UI then asks "Cuối cùng - bạn thích kiểu trải nghiệm nào? Chọn
vài mục nhé." with a preference chip picker.

That sentence is not model output — it is `intakePreferencesQuestion`
(`frontend/src/i18n/locales/vi.json:166`), rendered by `intake-parameters-form.tsx:147`:

1. `respond.py:219` — every turn reports `stage: "intake"`.
2. `chat-panel.tsx:121` — `showIntakeForm` is true whenever `lastStage === 'intake'`, so the
   intake form never unmounts.
3. `next-intake-field.ts:143` — `currentIntakeField` ends in an unconditional
   `return 'preferences'`; its own docstring calls this the sticky terminal field.
4. The preferences card renders its question.

`chat-panel.tsx:115` shows the same root cause from the other side: `inHotelStage` requires
`lastStage === 'hotel_options'`, which can never be true, so the hotel rail and `StepNavigator`
stay in intake state for the whole session.

### Field-by-field evidence

| Field | Frontend consumer | Producer available in the graph plane | Verdict |
|---|---|---|---|
| `stage` | `chat-panel.tsx:115,121,204` | `missing_slots`, `trip_data`, `hotel_options` | Derive |
| `suggestions` | `suggestion-chips.tsx`; also gates the whole footer at `chat-panel.tsx:178` | `services/suggestions.py::generate_next_chat_suggestions` — exists, but **only `cli/terminal_chat.py:15` calls it**. The web plane never has | Wire up |
| `compound_min_price` / `compound_max_price` | `use-chat-session.ts:88-89` → `stage-hotels.tsx:199-200`, the price-slider bounds | `travel_state`'s `budget.min` / `budget.max` — the same slots the in-flight budget work already surfaces as `intake.min_price`/`max_price` | Derive |
| `all_preferences` | `use-chat-session.ts:90` → `stage-hotels.tsx:201`, the preference pill list | `services/amenity_catalog.py::query_approved_amenities` | Derive |
| `active_preferences` | `use-chat-session.ts:91` → `stage-hotels.tsx:95`, seeds the initial filter selection | `travel_state`'s `hotel_preferences.amenities` (`travel_state.py:65`) | Derive |
| `requires_stay_dates` | **none** — zero references anywhere under `frontend/src` | **none** — no backend writer exists either; only `respond.py:223` and the `schemas.py:383` default | Dead field |

### Two stale comments this phase must correct

- `ask_slot.py:11` cites *"`api/routes.py`'s `requires_stay_dates`"*. `routes.py` contains no
  such symbol — the only `stay_dates` there is `request.stay_dates` on the input model
  (`routes.py:218-219`), a different thing entirely.
- `respond.py`'s docstring calls `compound_*`/`*_preferences` bookkeeping that Phase 8
  *"deliberately replaces with `travel_state` as the single source of truth"*. That decision is
  correct and this phase implements it — but the docstring reads as if the work were done.

### Vocabulary bound for `stage`

`ChatStage` (`schemas.py:327`) is `Literal["intake", "hotel_options", "planned", "modified",
"finalized", "error"]`. Of these:

- `finalized` — the graph plane has **no finalize node**. `finalize` exists only as an
  `extract_patch` intent label (`prompts.py:54`, `extract_patch.py:66`); nothing consumes it.
- `modified` — the legacy plane derived it from `TripSession.pending_trip_edit_request`. No
  graph equivalent, and no frontend code reads it.
- `error` — no graph path produces it; `routes.py:378` owns its own error shape.

None of the three may be faked. Only three values are reachable and that is enough: the three
frontend call sites test for `'intake'` and `'hotel_options'` only, and `types.ts:148` types
`Stage` loosely as `'hotel_options' | 'error' | string | null`.

`derive_stage` (`session.py:65-78`) is the legacy deriver. It documents the intended precedence
— a complete plan outranks a pending hotel pick — but reads `TurnResult.tool` and `TripSession`
flags that do not exist in `TravelGraphState`. Port the ordering, not the code.

## Requirements

- Functional: `stage` is `"intake"` while any required slot is missing; `"planned"` once
  `trip_data` holds a trip; `"hotel_options"` when hotel options were returned this turn and no
  trip exists; `"intake"` otherwise. Always a valid `ChatStage`.
- Functional: `finalized`, `modified` and `error` are never emitted until a real producer and a
  real consumer both exist.
- Functional: `suggestions` carries real follow-up prompts, shaped as `SuggestionPayload`
  (`{label, value}`, `schemas.py:309-311`) — note `generate_next_chat_suggestions` returns
  `list[str]`, so the mapping is this node's job.
- Non-functional: `suggestions` adds **no** LLM call on turns whose action already has a
  hardcoded list. `generate_next_chat_suggestions` short-circuits for `recommend_hotel*` /
  `pending_hotel*` / `finalize*` (`suggestions.py:30-43`) and only calls the model on the
  general branch; pass a `last_action` derived from the new `stage` so the common paths stay
  free.
- Functional: `compound_min_price` / `compound_max_price` come from `travel_state`'s
  `budget.min` / `budget.max`, presence-aware. Do **not** port `recommend_hotels.py:457-490`'s
  cross-turn accumulation — Phase 8 replaced it deliberately.
- Functional: `active_preferences` comes from `hotel_preferences.amenities`;
  `all_preferences` from the approved amenity catalog.
- Non-functional: the catalog lookup must not add a Supabase round-trip to every turn. Fetch it
  only when the filter panel can actually render it (`stage == "hotel_options"`), and confirm
  the catalog call is cached before wiring it in.
- Functional: `requires_stay_dates` stays `False` and the field stays in the shape — the frozen
  `PlannerChatResponse` contract is what the whole plane is built on. Correct `ask_slot.py:11`'s
  claim that `routes.py` produces it.
- Non-functional: `stage` derivation is a pure function of `TravelGraphState`, unit-testable
  without a graph run.
- Non-functional: no file under `frontend/` is modified. Every consumer already behaves
  correctly once the values are truthful.

## Architecture

```python
def _derive_stage(state: TravelGraphState, hotel_options: list[dict[str, Any]]) -> str:
    if state.get("missing_slots"):
        return "intake"
    if state.get("trip_data"):
        return "planned"
    if hotel_options:
        return "hotel_options"
    return "intake"
```

`missing_slots` is checked first because it is the only signal that intake is genuinely
incomplete — `ask_slot` is its sole writer and `load_context` deliberately does not reset it.
`trip_data` outranks `hotel_options` per `derive_stage`'s precedence. `hotel_options` is passed
in already computed so the two fields cannot disagree.

`stage` is derived first and then feeds the rest: it selects the `last_action` for suggestions
and gates the amenity-catalog fetch. One derivation, four consumers, no second source of truth.

### Interaction with in-flight work

Uncommitted changes on this branch add `min_price`/`max_price`/`budget_skipped` to
`IntakeStatus` and a `_budget_from_travel_state` helper in `respond.py` that reads the
`budget.*` slots presence-aware. `compound_min_price`/`compound_max_price` need the same two
slots — **reuse that helper, do not write a second reader.** Land the budget work first so the
diffs stay separable.

## Related Code Files

- Modify: `backend/src/agents/graph/nodes/respond.py` — `_derive_stage`, suggestion mapping,
  compound-price and preference derivation; rewrite the docstring paragraphs that declare these
  fields placeholders
- Modify: `backend/src/agents/graph/nodes/ask_slot.py` — correct the stale `requires_stay_dates`
  claim on `:11`
- Modify: `backend/tests/test_respond.py` (untracked, added by the in-flight budget work)
- Read-only reference: `backend/src/agents/session.py:65-78`, `backend/src/models/schemas.py:309-311,327`,
  `backend/src/services/suggestions.py:30-43`, `backend/src/services/amenity_catalog.py`,
  `frontend/src/components/chat-panel.tsx:115,121,178,204`,
  `frontend/src/components/stage-hotels.tsx:95,199-203`

## Implementation Steps

1. Add `_derive_stage` next to the other `_`-helpers; replace the hardcoded `"stage"` with the
   call, passing the `hotel_options` list computed on the line below.
2. Add stage tests to `test_respond.py` and confirm them green before touching anything else —
   this is the change that fixes the reported bug, and it should be provable on its own.
3. Map `stage` → `last_action` and wire `generate_next_chat_suggestions`, converting `list[str]`
   to `SuggestionPayload{label, value}`. Assert in a test that a `hotel_options` turn makes no
   LLM call.
4. Derive `compound_min_price`/`compound_max_price` by reusing `_budget_from_travel_state`.
5. Derive `active_preferences` from `hotel_preferences.amenities`. Confirm
   `query_approved_amenities` is cached; then derive `all_preferences` from it, gated on
   `stage == "hotel_options"`.
6. Fix the stale `requires_stay_dates` comment in `ask_slot.py:11` and the placeholder
   paragraphs in `respond.py`'s docstring.
7. Replay the reported transcript manually: the preference chip card must not appear after the
   hotel result, the hotel rail must open, and the filter panel must show real price bounds and
   pills.

## Success Criteria

- [x] Every `stage` value `respond` emits is a member of `ChatStage`
- [x] Missing slots → `intake`; hotel options with no trip → `hotel_options`; `trip_data` present
      → `planned` even when hotel options are also present; empty state → `intake`
- [x] Replaying the reported transcript no longer renders the preference chip card after
      "Mình tìm được 5 khách sạn phù hợp." (proven at the node level: a `hotel_node` task result
      with no `trip_data` set now derives `stage: "hotel_options"`, not `"intake"` —
      `test_respond.py::TestRespondSuggestions::test_hotel_options_turn_gets_the_hardcoded_list_without_calling_the_llm`)
- [x] `inHotelStage` becomes true on a hotel-result turn, so the rail renders (true for the
      reported bug's intake→hotel flow; see Open Question 3 for the post-plan re-search gap)
- [x] `suggestions` is non-empty on a hotel-result turn, and that turn makes **no** LLM call for
      suggestions (asserted on a fake — verified by mutation testing, see review report)
- [x] `compound_min_price`/`compound_max_price` reflect the `budget.min`/`budget.max` slots, and
      are `None` when those slots are unset
- [x] `active_preferences` reflects `hotel_preferences.amenities`
- [x] The amenity catalog is not queried on an intake-stage turn (asserted with a call counter,
      not a raiser — `generate_next_chat_suggestions`/`query_approved_amenities` both fail closed
      on exceptions, which made an earlier raiser-based version of this test a false pass)
- [x] No file under `frontend/` is modified
- [x] Full backend suite passes with no existing test modified (531 passed; 1 pre-existing
      failure in `test_trip_modification.py` unrelated to this phase, reproduces identically on
      `main`/pre-change via `git stash`)

## Risk Assessment

| Risk | Severity | Mitigation |
|---|---|---|
| Wiring `suggestions` adds an LLM call to every turn, on the terminal node of every path | High | Only the general branch of `generate_next_chat_suggestions` calls a model; hotel and finalize actions return hardcoded lists. Derive `last_action` from `stage` so the common paths stay free, and assert the no-call case in a test |
| `all_preferences` puts a Supabase round-trip in `respond`, which does no I/O today | High | Gate on `stage == "hotel_options"` and verify the catalog call is cached **before** wiring it. If it is not cached, stop and cache it first rather than accepting per-turn I/O on the terminal node |
| A truthful `stage` unmounts the intake form on paths that silently relied on it staying mounted | Medium | Only three consumers read stage; `editingIntakeField` keeps the "Sửa" path working independently of stage, by explicit design in `chat-panel.tsx`'s own comment |
| Zero-result hotel turn reports `intake`, so the intake form reappears | Medium | Accepted: the turn genuinely has nothing to show. Do not invent a stage without a consumer |
| Deriving five fields at once makes the diff hard to review and hard to bisect | Medium | Step 2 gates on the stage change being green in isolation; each remaining field is its own commit |
| Reusing `_budget_from_travel_state` couples this work to an uncommitted change | Low | Land the budget work first (stated in Architecture) |
| Emitting `planned` reaches frontend code that has never seen it | Low | `Stage` is typed `string \| null`; no branch matches `planned`, so it falls through to today's default path |

## Open Questions

1. Should a zero-result hotel search get its own stage, or keep falling back to `intake`?
2. `requires_stay_dates` has no producer and no consumer on either side. Keep it in the frozen
   shape as a permanent `False`, or schedule its removal in a contract-cleanup phase?
3. **Known gap, accepted at implementation time:** `trip_data` outranking `hotel_options` (per
   this phase's own Architecture/Success Criteria) means `stage` is `"planned"` for the rest of
   the session once a trip exists — even on a turn where `hotel_node` runs again and returns
   fresh results (e.g. a post-plan "tìm khách sạn khác"). That turn's hotel rail
   (`inHotelStage`, `chat-panel.tsx:115`) never opens and `all_preferences` stays empty (gated
   the same way), because both read `stage`, not `hotel_options` directly. Flagged by review;
   kept as-is because reversing it would diverge from this phase's explicit, already-decided
   precedence without a recorded design change. Needs either a real "trip was just rebuilt this
   turn" signal or an explicit re-scope of the stage precedence in a follow-up phase.
