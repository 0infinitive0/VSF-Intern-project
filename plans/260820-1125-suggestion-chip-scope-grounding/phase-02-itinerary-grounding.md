# Phase 2 — Ground itinerary chips in real day data

**Status:** done
**Depends on:** Phase 1
**Files:** `backend/src/services/suggestions.py`, `backend/src/api/routes.py`,
`backend/tests/test_suggestions.py`, `backend/tests/test_stream_suggestions.py`

## Context

`itinerary_node` is a gated suggestion worker, but the only itinerary fact reaching the
prompt is `trip_duration_days` (`routes.py:1180`). A chip that edits a day must therefore
invent the item it edits, and the fabrication rule only covers hotels, amenities, and
numbers. The data is already on the response object — no new query, no state read:
`TripPlanPayload.days[] -> DayPlan{day_number, theme, items[]}`, `ItineraryItem.activity`
(`schemas.py:277-327`), all set by `trip_formatter`.

## Requirements

**`suggestions.py`**

- New frozen dataclass beside `SuggestionHotelCard`:

  ```python
  @dataclass(frozen=True)
  class SuggestionDay:
      day_number: int
      theme: str = ""
      activities: tuple[str, ...] = ()
  ```

- New `SuggestionContext` field `itinerary_days: tuple[SuggestionDay, ...] = ()` — a default
  is mandatory, `terminal_chat.py:66` must keep constructing the context unchanged.
- `_format_days(days)` mirroring `_format_cards`: `"(chưa có lịch trình)"` when empty,
  otherwise one line per day — `- Ngày {n} ({theme}): {activity, activity, ...}`.
- Caps, same pattern and reasoning as `_MAX_CARDS_IN_PROMPT`: `_MAX_DAYS_IN_PROMPT = 7`,
  `_MAX_ACTIVITIES_PER_DAY_IN_PROMPT = 4`. Prompt size must not scale with trip length.
- Splice the rendered days into `_build_prompt` under the existing `Số ngày lịch trình` line,
  and extend the fabrication rule to name itinerary items explicitly: a chip may only
  reference a day number and an activity that appear above.

**`routes.py::_suggestion_context`**

- Build `itinerary_days` from `response.trip_plan.days` when `trip_plan` is set, `()`
  otherwise. Read stays inside the existing lock-held section — no new state access, the
  response object is already in hand.
- Keep `trip_duration_days` as-is; it still carries the length when `days` is empty (a plan
  can exist with no rendered days).

## Steps

1. Add `SuggestionDay`, the context field, `_format_days`, and the two caps.
2. Wire `_build_prompt`.
3. Map `response.trip_plan.days` in `_suggestion_context`.
4. Extend docstrings: `SuggestionContext` gains a line on why day data is capped.

## Validation

`tests/test_suggestions.py`:
- `test_prompt_lists_real_itinerary_days_and_activities` — day number, theme, and activity
  strings from the context appear in the prompt.
- `test_prompt_says_no_itinerary_when_there_are_no_days` — placeholder present, no stray
  "Ngày" line.
- `test_day_and_activity_caps_bound_the_prompt` — 10 days × 10 activities in, at most 7 day
  lines and 4 activities each out.

`tests/test_stream_suggestions.py` (`TestSuggestionContext`, existing `_response` helper —
add a `trip_plan` override rather than changing the shared default):
- `test_itinerary_days_are_mapped_from_the_trip_plan` — `ctx.itinerary_days` matches the
  response days/themes/activities.
- `test_itinerary_days_is_empty_when_there_is_no_trip_plan` — `ctx.itinerary_days == ()` and
  `ctx.trip_duration_days is None` (guards the existing `trip_plan=None` default).

Run: `pytest tests/test_suggestions.py tests/test_stream_suggestions.py tests/test_respond.py -q`.
Then a broader `pytest -q` since `SuggestionContext` is shared with the CLI path.

## Risk / rollback

Low-medium. The one real risk is prompt bloat on a long trip — the caps exist for exactly
that and are asserted by test. `SuggestionContext` is additive with a default, so
`terminal_chat.py` cannot break; a full `pytest -q` confirms it.

Rollback = revert both files; chips fall back to today's behavior (grounded in hotels only).
