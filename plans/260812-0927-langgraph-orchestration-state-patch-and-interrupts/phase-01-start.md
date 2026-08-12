---
phase: 1
title: "Fix deterministic day-theme and amenity bugs"
status: done
priority: P1
effort: "0.5d"
dependencies: []
---

# Phase 1: Fix deterministic day-theme and amenity bugs

## Overview

Two proven, deterministic bugs that need none of the refactor in Phases 2-8. Ship this
first, on its own branch. Both produce a *success message with wrong data* — the worst
failure shape, because nothing looks broken.

## The bugs

### Bug A — a user-specified day theme is discarded

`_apply_day_replan` (`trip_planner.py:1354`) correctly writes the user's new theme, then
`_build_trip_data` throws it away:

```
_apply_day_replan:1375-1377  themes[day1] = {title:"Thiên nhiên...", query:"nature parks gardens outdoor"}
_build_trip_data:612         normalize_day_themes(themes_override, n_days, preferences=["biển"])
trip_scheduler.py:534-535    clean_preferences non-empty  → _preference_theme_for_day(["biển"], 1, "nature parks...")
trip_scheduler.py:499        preference = "biển"                    ← the ORIGINAL trip preference
trip_scheduler.py:508        "bien" in "nature parks gardens outdoor"? NO
trip_scheduler.py:511        query = "biển điểm tham quan nổi bật"  ← user's query DISCARDED
_apply_day_replan:1390       itinerary["day_themes"] = themes       ← user's TITLE still written
```

Net effect: the stored title says "Thiên nhiên", the scheduled attractions are the old
beach theme. `resolve_trip_edit_request:1544` then replaces the informative
`"Đã lập lại ngày 1 theo chủ đề ..."` with a generic `"Điều chỉnh đã áp dụng."`, so the
user has no signal at all.

Reproduces only when the trip has preferences (`itinerary["preferences"][1:]` non-empty).
With no preferences the `:534` guard is false and replan works — which is why the
behavior looked intermittent.

### Bug B — amenity pills asserted without checking

`recommend_hotels.py:408-416`: on the **first** amenity request (`previous_active_ids`
empty) every newly fetched hotel is labelled with every requested preference —
`list(current_pref_ids)` — bypassing `hotel_matches_amenity_tag`. The predicate is
applied only on follow-up requests. So the first "khách sạn có hồ bơi" marks all cards
as having a pool regardless of fact.

## Caller characterization (verified before changing anything)

`normalize_day_themes` is **CRITICAL** blast radius: 14 symbols, 10 execution flows,
3 direct callers. The preference-override at `:534` was audited per caller:

| Caller | Passes `preferences`? | Override intent | Verdict |
|---|---|---|---|
| `_generate_day_themes` (`trip_planner.py:206`) | Yes | LLM is already prompted "Honor these user preferences" (`:185`); the override *enforces* adherence when the model ignores it, and fills all days when the LLM call raised and left `raw_themes=[]` | **Correct — keep** |
| `trip_formatter.py:124` | **No** (2 positional args only) | `clean_preferences` is empty, so `:534` never fires | **Unaffected** |
| `_build_trip_data:612` via reuse template | Yes | Template borrowed from a *different* trip; re-theming to the current user's preferences is the point of Tier-1 reuse | **Correct — keep** |
| `_build_trip_data:612` via `_apply_day_replan` | Yes | User explicitly named this day's theme | **Wrong — this is Bug A** |

Conclusion: "no marker ⇒ existing behavior" is the right default **because three of the
four paths are intent-correct**, not merely because preserving behavior is safer. Only
the fourth path changes.

**Design constraint that follows:** the marker must be **per-theme, not per-call**.
`_apply_day_replan` replans one day while the same `themes` list still carries the other
days, which must stay preference-driven. A call-level flag would wrongly unlock every day.

## Requirements

- Functional: a day theme the user explicitly named survives `_build_trip_data` unchanged
  (title *and* query), while unnamed days in the same list keep preference-derived themes.
- Functional: an amenity pill appears on a hotel card only when `hotel_matches_amenity_tag`
  returns True for that hotel.
- Functional: the user-facing reply for a day replan names the day and the theme applied.
- Non-functional: zero behavior change for `_generate_day_themes`, `trip_formatter`, and
  the reuse-template path — pinned by characterization tests written *before* the change.

## Architecture

Add an explicit per-theme provenance field rather than inferring intent:

- `DayTheme` (`trip_scheduler.py:93`) gains `selection_mode: str = "auto"`. Default keeps
  every existing constructor call valid.
- `normalize_day_themes:534` skips `_preference_theme_for_day` when the raw theme carries
  `selection_mode == "user_specified"`, preserving its `title`/`query` verbatim.
- `serialize_day_themes:576` persists the field so a second edit does not re-overwrite it.
- `_apply_day_replan:1377` stamps `selection_mode: "user_specified"` on the replanned day.
  The edit planner prompt already emits this exact value (`trip_edit_planner.py:442`), so
  the vocabulary is not new — it is currently just dropped by `value.update({...})`.

The field is additive and defaulted, so persisted itineraries written before this change
deserialize to `"auto"` and behave exactly as today.

## Related Code Files

- Modify: `backend/src/services/trip_scheduler.py` — `DayTheme` (:93), `normalize_day_themes` (:517-573), `serialize_day_themes` (:576)
- Modify: `backend/src/services/trip_planner.py` — `_apply_day_replan` (:1354-1392), `resolve_trip_edit_request` reply (:1540-1545)
- Modify: `backend/src/agents/tools/recommend_hotels.py` — preference labelling (:408-416)
- Modify: `backend/tests/test_trip_scheduler.py`, `backend/tests/test_trip_modification.py`

## Implementation Steps

1. **Characterization tests first.** Pin current behavior of all three `normalize_day_themes`
   callers: preference-override enforcement in `_generate_day_themes`, the no-preferences
   `trip_formatter` path, and reuse-template re-theming. These must pass before and after.
2. Run `impact` on `DayTheme` and `serialize_day_themes` before editing; record the result
   in the PR description.
3. Add `selection_mode` to `DayTheme` with default `"auto"`; thread it through
   `serialize_day_themes`.
4. Guard `normalize_day_themes:534` on the per-theme `selection_mode`.
5. Stamp `selection_mode: "user_specified"` in `_apply_day_replan:1377`.
6. Return the real adjustment text from `resolve_trip_edit_request` instead of the generic
   `"Điều chỉnh đã áp dụng."`.
7. Apply `hotel_matches_amenity_tag` on the first-request branch in `recommend_hotels.py:408-416`.
8. Add regression tests for Bug A (theme survives, other days unaffected, survives a second
   edit round-trip through serialize/deserialize) and Bug B (pill only on matching hotels).

## Success Criteria

- [ ] "đổi theme ngày 1 sang thiên nhiên" on a trip **with** preferences changes day 1's
      scheduled attractions, not just its title
- [ ] Days 2..N in that same trip keep their preference-derived themes
- [ ] A second consecutive replan of day 1 still honors the user's theme (persistence round-trip)
- [ ] First-time "khách sạn có hồ bơi" labels only hotels that actually match
- [ ] The reply names the day and theme applied
- [ ] Characterization tests for all three unaffected callers pass unchanged
- [ ] `make test` green

## Risk Assessment

| Risk | Mitigation |
|---|---|
| `normalize_day_themes` CRITICAL blast radius (10 execution flows) | Per-theme opt-in marker; default `"auto"` preserves the three intent-correct paths, each pinned by a characterization test written first |
| `DayTheme` is consumed by `build_itinerary`, `trip_formatter`, `itinerary_reuse` | New field is defaulted — no positional constructor call breaks. Verify with `impact` before editing |
| Old persisted itineraries lack `selection_mode` | Absent ⇒ `"auto"` ⇒ current behavior; explicitly covered by a deserialization test |
| Returning real adjustment text changes reply strings other tests assert on | Grep tests for `"Điều chỉnh đã áp dụng"` and update deliberately |
