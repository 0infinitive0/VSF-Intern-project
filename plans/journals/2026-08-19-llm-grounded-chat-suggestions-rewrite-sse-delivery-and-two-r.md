---
title: "LLM-grounded chat suggestions: rewrite, SSE delivery, and two race fixes"
date: 2026-08-19
summary: "Replaced hardcoded per-stage suggestion chips with LLM-grounded generation gated by worker, delivered via a new post-final SSE event; code review caught and fixed 2 high-severity streaming races."
---

# LLM-grounded chat suggestions: rewrite, SSE delivery, and two race fixes

## What happened

Implemented plan `260819-1554-llm-grounded-chat-suggestions` end to end (4 phases):

- **Phase 1**: Rewrote `backend/src/services/suggestions.py` from scratch. The old
  version returned hardcoded Vietnamese suggestion lists keyed by `last_action`
  (`recommend_hotels`/`finalized`), and the web flow never actually reached the
  branches that called the LLM — chips were structurally dead on most turns.
  New version always calls `get_fast_llm(...).with_structured_output(NextChatSuggestions)`
  with a `SuggestionContext` built from real turn data (hotel cards, real amenity
  labels, active filters, trip duration, language). No static fallback: LLM
  failure/timeout/empty output all degrade to `[]` with `logger.warning`, never an
  exception escaping the caller.
- **Phase 2**: Removed suggestion generation from the `respond` graph node entirely
  (`respond()` now always sets `"suggestions": []`). Moved it into `routes.py`'s
  `planner_chat_stream`, gated by `task_results[-1]["worker"]` (not `stage` — the
  old gate mapped only `hotel_options`, missing `itinerary_node`/`budget_check`
  turns completely) via a new `last_worker_from_task_results` helper. Chips are
  now delivered as a new SSE `suggestions` event sent AFTER `final`, so the reply
  is never delayed by the suggestion LLM call. Extracted the `_run_turn` closure
  into a top-level `_run_stream_turn` for direct testability.
- **Phase 3**: `stream-client.ts`'s frame reader no longer returns immediately at
  `case 'final'` — it keeps draining until the stream closes, so a trailing
  `suggestions` frame isn't dropped. Added `onFinal`/`onSuggestions` handlers and
  a `STREAM_SUGGESTIONS` reducer action in `use-chat-session.ts`.
- **Phase 4**: Updated `docs/chat_api_contract.md` (`suggestions` frame example,
  the "non-terminal frame after terminal frame" exception, removed all dead
  `suggestions_for()` references, corrected the stale "one chip per hotel option"
  claim).

## Code review findings and fixes

Spawned a `code-reviewer` subagent against the full diff. Two HIGH severity findings,
both real regressions introduced by decoupling `pending`-clear from stream-close:

1. **Post-`final` stream failure surfaced as a user-visible error despite a
   successful reply.** `stream-client.ts`'s new keep-draining loop had no
   `catch` — any read failure after `final` (network drop, an aborted read)
   propagated and rejected the promise even though `onFinal` had already fired
   and the reply was already on screen. Fixed: `finalData` is now authoritative
   — if it's set, a post-final read error is swallowed and `finalData` is
   returned instead of thrown.
2. **`turnId` staleness guard didn't cover same-session multi-turn races.**
   `pending` now clears at `final`, not at stream-close, so the SSE connection
   can still be draining (waiting on the suggestions frame) when the user sends
   the next message. `turnId` only advances on RESET/RESTORE, not between two
   ordinary messages in one session — so a late `suggestions` frame from turn N
   could land under turn N+1's already-rendered reply. Fixed: `send()` now calls
   `abortRef.current?.abort()` before starting a new turn, same pattern
   `startNew()`/`restore()` already used.

Medium findings also fixed: `_SKIP_STATUSES` was missing `hotel_selection_failed`
and `already_paid` (a locked/paid session's hotel-node turn was still generating
unexecutable "đổi khách sạn" chips); `generate_next_chat_suggestions` had no
timeout on the Ollama fallback path (only `get_llm`'s `timeout=` reaches the
OpenAI branch) — added a `concurrent.futures`-based wall-clock guard that bounds
every provider uniformly; `_suggestion_context` had zero direct unit coverage
(only exercised through a mocked `generate_next_chat_suggestions`) — added a
12-test `TestSuggestionContext` class covering gating, field mapping, and the
language switch.

## Decision

Kept the fix for finding 1 narrow: `finalData` short-circuits a post-final error
rather than adding a broader retry/reconnect mechanism, since the contract only
guarantees one non-terminal frame after `final` and a dropped `suggestions` frame
is already a designed "no chip" state, not data loss.

Left three things unfixed, all documented as accepted/out-of-scope rather than
silently dropped:
- The duplicate `app.get_state()` read inside `session.lock` (once by
  `_persist_turn`, once by `_suggestion_context`) — the plan's own non-goals
  explicitly say no premature caching/optimization; revisit only if measured.
- `active_preferences[].label` stays Vietnamese-only in English conversations —
  `PreferencePayload` has no `label_en` field; a pre-existing schema limitation,
  not something this plan introduced.
- `terminal_chat.py` has a pre-existing broken import (`process_chat_turn` does
  not exist in `src.agents.session` — confirmed via `git show HEAD` that this
  predates this session). The CLI adapter (`_cli_suggestion_context`) is correct
  at the code level but unexercisable until that unrelated bug is fixed.

## Next steps

- Manual smoke test against a real LLM (Phase 4's success criterion — click every
  chip on a hotel turn and an itinerary turn, confirm none get scope-guard-refused
  or return zero results) was not run this session; needs a live backend+frontend.
- Fix the pre-existing `process_chat_turn` import break in `terminal_chat.py` in a
  separate, scoped change so the CLI path can actually be smoke-tested.
- If p95 latency on `get_fast_llm` for the suggestion prompt turns out high,
  the plan's own open question flags a cache keyed on `(worker, hash of
  hotel/trip list)` as the next lever — deliberately not built preemptively.

> Historical work record — not durable authority. Prefer docs/specs/ADRs for current decisions.
