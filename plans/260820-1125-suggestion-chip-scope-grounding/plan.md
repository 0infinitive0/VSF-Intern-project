---
title: "Suggestion chip scope + itinerary grounding"
description: "Keep next-chat suggestion chips inside what the agent can actually do, and ground itinerary chips in the real day/item data the same way hotel chips are grounded in real cards."
status: done
priority: P2
branch: "main"
tags: [suggestions, prompt, grounding, langgraph]
blockedBy: []
blocks: []
effort: "0.5d"
created: 2026-08-20
---

# Suggestion chip scope + itinerary grounding

## Overview

`generate_next_chat_suggestions` is already grounded in **data** — the prompt forbids
inventing hotels, amenities, and numbers, and `_clean` only trims/dedupes. It is not
grounded in **capability**: nothing in the prompt tells the model what this agent can
actually do, so a chip like "Đặt phòng Khách sạn B" or "Thời tiết Đà Nẵng tuần này" is
fully legal today. Those chips are dead ends, and no layer downstream catches them.

Second, itinerary turns are the one gated worker with almost no grounding: the context
carries `trip_duration_days` and nothing else about the plan, so a chip that edits a day
has to invent the item it edits — and the "no fabrication" rule only names hotels,
amenities, and numbers, so it does not stop that.

Both fixes land in `suggestions.py` + `routes.py::_suggestion_context`. No wire-format
change, no frontend change, no new module.

## Established facts (verified 2026-08-20, read from source)

- **The prompt has zero capability constraints.** `suggestions.py:148-153` lists exactly
  four rules: no fabricated data, filters must carry a concrete number, no amenity outside
  the given list, under 12 words. None of them bounds *what kind of request* a chip may be.
- **Nothing downstream catches an out-of-scope chip.** Chips are sent verbatim as the next
  user message (`routes.py:1255` builds `{label: text, value: text}`,
  `suggestion-chips.tsx:33` sends `s.value`). A booking chip cannot reach `booking_node` —
  `_IMPOSSIBLE["booking_node"]` is unconditionally `True` (`booking_node.py:9-14`) — so the
  supervisor falls back to `qa_node`, whose only tools are `get_hotel_options`,
  `get_trip_plan`, `query_hotel`, `query_hotel_rooms`, `search_places` (`qa_node.py:66-70`).
  The out-of-scope refusal guard was never built: `scope_guard.py:12-18` says so in its own
  words ("was never actually built despite its plan doc being marked done").
- **Itinerary grounding is missing, not thin.** `_suggestion_context` (`routes.py:1171-1181`)
  passes `trip_duration_days` only. The data exists and is already on the response:
  `TripPlanPayload.days[] -> DayPlan{day_number, theme, items[]}` and
  `ItineraryItem.activity` (`schemas.py:277-327`), both always set by `trip_formatter`.
- **Blast radius is small.** `SuggestionContext` has two production constructors
  (`routes.py:1171`, `terminal_chat.py:66`) and three test files. A new field with a default
  leaves the CLI path compiling and behaving exactly as today (its docstring already declares
  its grounding intentionally thinner, `terminal_chat.py:43-44`).
- **`_clean` is the only post-processing.** It strips ordinals, dedupes case-insensitively,
  drops empties, truncates to `limit` (`suggestions.py:93-107`). No filtering of any kind.

## Decisions (user, 2026-08-20)

1. **Enforcement is prompt-only** — a whitelist of what the agent does plus an explicit
   forbidden list, inside `_build_prompt`. No keyword post-filter (a static reject list
   contradicts this module's "no hardcoded strings" charter and is brittle across two
   languages), no second validator LLM call (cost + latency + another failure point).
2. **Itinerary grounding is in scope** — real day themes and item names go into the context,
   the same shape `hotel_cards` already uses.
3. **`booking_node` stays in `_SUGGESTION_WORKERS`** even though its only status
   (`"declined"`, `booking_node.py:39`) is in `_SKIP_STATUSES`, making it unreachable today.
   Left as-is deliberately for when a booking backend exists.

## Non-goals

- No change to the SSE contract, `SuggestionPayload`, or any frontend file.
- No revival of `guardrails/scope.py` — an out-of-scope *user* message is a different
  problem from an out-of-scope *chip*, and remains deferred.
- No enrichment of the CLI's `_cli_suggestion_context`; it stays intentionally thinner.
- No change to `_SKIP_STATUSES` or the worker gate.

## Phases

| # | Phase | Depends on |
|---|-------|------------|
| 1 | [Capability scope in the suggestion prompt](phase-01-capability-scope-prompt.md) | — |
| 2 | [Ground itinerary chips in real day data](phase-02-itinerary-grounding.md) | 1 |

## Acceptance criteria

- `_build_prompt` output names the four things the agent can do and the things it must never
  suggest; asserted by test, not by eyeball.
- A turn whose `trip_plan` has days puts those day numbers, themes, and item names into the
  prompt; a turn with no plan puts an explicit "chưa có lịch trình" placeholder instead.
- Prompt stays bounded regardless of trip length (day and per-day item caps, same pattern as
  `_MAX_CARDS_IN_PROMPT`).
- `pytest tests/test_suggestions.py tests/test_stream_suggestions.py tests/test_respond.py`
  green; no existing assertion weakened.
- `terminal_chat.py` untouched and still constructs a valid `SuggestionContext`.
