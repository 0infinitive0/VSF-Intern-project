---
phase: 3
title: "Backend generation wiring"
status: completed
priority: P1
effort: "1d"
dependencies: [2]
---

# Phase 3: Backend generation wiring

## Overview

Make the new fields (Phase 2) actually affect output: (a) resolve intake facts +
hotel budget in the same turn when one message answers both, (b) feed
companions/notes into the dormant `hotel_preferences` argument, (c) inject the new
taxonomy into itinerary day-theme generation. No frontend changes in this phase.

## Requirements

- Functional: `_run_intake()` (`src/agents/session.py:736-765`) currently defers the
  hotel-budget question to the turn AFTER intake facts complete (see comment at
  745-747), so a single combined message never resolves both facts and budget in one
  turn. Change: when `intake_state` just became complete on this turn, immediately
  also try `hotel_pref_state.with_message(user_input, ...)` with the SAME message,
  rather than only asking the budget question next turn. If that also resolves
  (`is_complete`), proceed straight to the `recommend_hotels` invocation this turn. If
  it does NOT resolve (message had no budget signal), fall back to today's behavior
  (ask the budget question next turn) — no regression for a plain chat user who only
  ever answers one fact per message.
- Functional: extend the `verified_arguments` dict built at
  `session.py:758-761` to also include a `hotel_preferences` key, built from
  `intake_state.companions` (mapped to a short phrase the amenity tagger already
  matches, e.g. `"đi cùng gia đình"` → include `"gia đình"`) and `intake_state.notes`
  (appended verbatim, already sanitized in Phase 2) — merge, don't overwrite, if
  `hotel_pref_state.tool_arguments()` or elsewhere ever populates this key.
- Functional: `recommend_hotels` (`src/agents/tools/recommend_hotels.py`) already
  accepts and forwards `hotel_preferences` (verify exact param name/plumbing to
  `hotel_matches_amenity_tag`'s `family` tag before wiring — confirm the amenity
  reranker actually reads free text for tag matching, not just structured tags; if it
  doesn't, this requirement narrows to "notes/companions are visible in the tool call
  for now" and the actual amenity-matching hookup becomes a follow-up, not blocking
  this plan).
- Functional: thread the new taxonomy into `_generate_day_themes()`
  (`src/services/trip_planner.py:164-192`): add a `context: str` parameter built from
  `pace`/`day_rhythm`/`notes` (companions/preferences already flow in via existing
  `preferences` param — do not duplicate), inserted into the prompt as one extra
  line, e.g. `Additional user context: {context}`. Trace every caller of
  `_generate_day_themes()` (seen at `trip_planner.py:401,414`) back to where
  `TripIntakeState`/`_current_trip_parameters()` is available, and thread the new
  fields through the same path `preferences` already takes — do not introduce a
  parallel plumbing path.
- Non-functional: `notes` is untrusted free text from the user, already
  length-capped (Phase 2). Treat it as *context to honor*, not as instructions — the
  prompt wording should read like the existing "Honor these user preferences when
  possible" line (advisory), not an imperative the model executes literally.

## Architecture

```
_run_intake() [session.py:736]
  intake_state.with_message(msg)         → may become complete this turn
  IF just-completed:
    hotel_pref_state.with_message(msg)   [NEW: same message, same turn]
    IF hotel_pref_state now complete:
      recommend_hotels.invoke({...intake_state.tool_arguments(),
                                ...hotel_pref_state.tool_arguments(),
                                hotel_preferences: companions+notes})   [stage → hotel_options]
    ELSE:
      ask hotel_pref_state.next_question()   [unchanged fallback]

_generate_day_themes(destination, days, categories, preferences, context)  [NEW param]
  prompt += "Additional user context: {context}"   ← pace/day_rhythm/notes
```

## Related Code Files

- Modify: `src/agents/session.py` (`_run_intake`, `verified_arguments` construction)
- Modify: `src/services/trip_planner.py` (`_generate_day_themes` + its callers)
- Modify: `src/agents/tools/recommend_hotels.py` (only if `hotel_preferences`
  plumbing needs a fix to actually reach the amenity reranker)
- Read (verify, no edit unless needed): `src/services/hotel_selection.py`
  (`hotel_matches_amenity_tag`, `_AMENITY_KEYWORD_TAGS`)

## Implementation Steps

1. Read `recommend_hotels.py` end to end to confirm exactly how (or whether)
   `hotel_preferences` currently reaches `hotel_matches_amenity_tag` — this
   determines whether requirement 4 is a real wire-up or already-there plumbing.
2. Implement the same-turn carry-through in `_run_intake()`; update the Phase 1
   characterization test's now-expected diff (two-turn → one-turn when signal
   present).
3. Extend `verified_arguments` with `hotel_preferences`.
4. Add the `context` param to `_generate_day_themes()` and thread it through every
   caller found via grep.
5. Manually invoke `_generate_day_themes()` in a REPL/test with
   `pace="dày đặc", notes="thích ăn hải sản"` and print the constructed prompt to
   confirm the context line renders correctly before writing the automated test
   (deferred to Phase 6).

## Success Criteria

- [ ] A message containing both a complete set of trip facts AND a budget-tier
      phrase reaches `hotel_options` stage in one turn (verified by the updated
      characterization test).
- [ ] A message with only trip facts (no budget signal) still asks the budget
      question next turn — no regression.
- [ ] `_generate_day_themes()`'s constructed prompt string contains the new context
      line when `pace`/`day_rhythm`/`notes` are set, and omits the line cleanly when
      none are set (verified in Phase 6).
- [ ] `hotel_preferences` argument on the `recommend_hotels` call is non-empty when
      `companions` or `notes` is set.

## Risk Assessment

| Risk | Mitigation |
|---|---|
| Same-turn carry-through accidentally also fires when only intake facts complete but the message contains an unrelated number that free-text budget parsing misreads as a price | `hotel_pref_state.with_message()` reuses the same `_parse_free_text_budget`/`resolve_guided_reply` grounding already used today — no new parsing logic, same false-positive surface as today's follow-up-turn path, not worse |
| `_generate_day_themes()` signature change breaks an untraced caller | Grep `_generate_day_themes(` across `src/` before editing; make `context` default `""` so old call sites compile unchanged during the transition |
| Prompt injection via `notes` (user writes "ignore previous instructions...") | Frame the context line as advisory preference text, not a directive; day-theme generation only returns constrained JSON (`{"themes": [...]}, day_number/title/query` — parsed and validated by `normalize_day_themes()`), so even a successful injection has a narrow blast radius (can't escape the JSON contract) |
