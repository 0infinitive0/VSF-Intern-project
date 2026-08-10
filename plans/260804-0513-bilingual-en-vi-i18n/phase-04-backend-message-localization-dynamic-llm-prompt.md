---
phase: 4
title: "Backend Message Localization & Dynamic LLM Prompt"
status: pending
priority: P1
effort: "2d"
dependencies: [3]
---

# Phase 4: Backend Message Localization & Dynamic LLM Prompt

## Overview

Wrap every backend string that actually reaches the end user (LLM prompts,
guided-question text, safe error strings, adjustment notes, suggestion-chip
prompt) with the `t()` helper from Phase 3, write the English catalog values
and the English LLM prompt variants, and compile the final `.mo` catalogs.
**Every `vi` msgstr must be byte-identical to the current hardcoded string** —
this phase changes *where* the Vietnamese text lives, not *what* it says, on
the default path.

## Requirements

- Functional: with `language="en"`, every deterministic reply string listed
  below returns English text; with `language="vi"` (default) or omitted,
  behavior is byte-identical to before this plan.
- Functional: the LLM's actual replies (via `SUPERVISOR_PROMPT_EN`) and
  suggestion chips (`suggestions.py`) are in English when `language="en"`.
- Non-functional: `_llm_extract_intake_facts`, `_parse_free_text_budget`, and
  all closed-set matching logic are UNCHANGED — those operate on the
  Vietnamese wire sentence the frontend still sends (Phase 2), independent
  of the reply language.

## Scope: what gets localized (confirmed via `sanitize_system_error` analysis)

`src/models/schemas.py:277-292` collapses any `SYSTEM ERROR:`-prefixed reply
NOT matching `_SAFE_ERROR_PREFIXES` into one generic message — most raw
`ValueError` strings inside tool code (`recommend_hotels.py`,
`finalize_itinerary.py`, etc.) never reach the user. **Only localize:**

1. `_SAFE_ERROR_PREFIXES`' 5 strings (`src/models/schemas.py:268-274`) + the
   generic fallback `_GENERIC_ERROR_MSG` (find its definition near line 268).
2. `TripIntakeState.next_question()` (`src/services/trip_intake.py:309-331`)
   — 4 questions.
3. The hotel budget `GuidedQuestion` prompt + its 4 `GuidedOption` labels
   (`src/services/hotel_selection.py:508-529`) — **but only the `prompt`
   text**; the option labels are what becomes `IntakeStatus.budget_options`,
   which is explicitly out of scope (stays Vietnamese, per plan.md) since the
   frontend renders them verbatim as server-sourced dynamic content.
4. `trip_planner.py`'s user-visible adjustment-note strings — the ones
   returned in lists that end up in `trip_plan.adjustments`
   (grep for the literal `"Đã ...".` sentences around lines 513, 633, 637,
   817, 824, 847-848 found during research; confirm each is actually
   reachable in a response path, not dead code, before wrapping it).
5. `suggestions.py`'s LLM prompt instructing "return Vietnamese JSON" (line
   51) — becomes language-parameterized like `SUPERVISOR_PROMPT`.
6. `session.py:829-832`'s retry-instruction appended to the agent input on
   the second attempt — becomes language-parameterized.
7. `SUPERVISOR_ROUTER_PROMPT` (`src/agents/prompts.py:38-39`) — its
   description of "the user writes in Vietnamese" is informational for the
   router LLM, not a literal user-facing string, but should be genericized
   (e.g. "the user writes in Vietnamese or English") so intent classification
   doesn't get subtly biased once English input becomes common. Does not need
   full `t()` wrapping since it's never shown to a user — a direct prompt
   edit is enough, not a catalog entry.
8. Generic 500-error detail strings in `src/api/routes.py` (`"Đã xảy ra lỗi
   máy chủ. Vui lòng thử lại."`, appears at least at lines 125, 192, 224) —
   these ARE shown to the user (FastAPI's `HTTPException.detail`). Wrap them;
   `routes.py` handlers have `request.language` in scope (or fall back to
   `"vi"` for the two `async def` utility endpoints that have no
   `PlannerChatRequest` — those stay Vietnamese, out of scope, since they're
   debug/search endpoints, not chat-facing).

Explicitly NOT touched: `_llm_extract_intake_facts`'s internal LLM prompt
(operates on the Vietnamese wire message, its own output is grounded/parsed,
never shown raw to the user), closed-set label tuples
(`_PREFERENCE_LABELS` etc. — wire protocol, Phase 2 already established this
boundary), and any `raise ValueError` not in `_SAFE_ERROR_PREFIXES`.

## Architecture

### Catalog key convention

Use the Vietnamese source text itself as the `msgid` (gettext convention —
`t("Bạn muốn đi đâu?", language)`), NOT a symbolic key like
`intake.ask_destination`. This matches `pybabel extract`'s default behavior
(it extracts literal string arguments to `_()`/`t()` calls as msgids) and
means a missing English translation degrades to showing the Vietnamese
source text (via `NullTranslations`/untranslated-`msgid` fallback) rather
than a raw key like `"intake.ask_destination"` leaking to the UI if a
translation is ever missing.

For strings needing interpolation (Python f-strings today), convert to
`str.format()`-style placeholders since `.format(**kwargs)` is what Phase 3's
`t()` helper applies:

```python
# Before:
f"Bạn muốn đi đâu? Hiện mình có dữ liệu cho: {choices}."
# After:
t("Bạn muốn đi đâu? Hiện mình có dữ liệu cho: {choices}.", language, choices=choices)
```

The English `.po` entry:
```
msgid "Bạn muốn đi đâu? Hiện mình có dữ liệu cho: {choices}."
msgstr "Where would you like to go? We currently have data for: {choices}."
```

### `next_question()` needs a `language` parameter

`TripIntakeState.next_question(self, destination_names=(), language="vi")` —
callers: `src/agents/session.py:805` (`session.hotel_pref_state.next_question()`)
and the intake equivalent. Thread `session.state["language"]` (or
equivalently a `language` argument already available at each call site — trace
each caller to confirm) through. Same treatment for
`HotelPreferenceState`'s guided-question path in `hotel_selection.py`.

### Dynamic prompts: fill in `SUPERVISOR_PROMPT_EN` and `suggestions.py`

Replace Phase 3's placeholder `SUPERVISOR_PROMPT_EN` in `src/agents/prompts.py`
with a real English translation of `SUPERVISOR_PROMPT_VI` — same structure
and tool-use instructions, translated meaning (not machine-translated
verbatim; the instructive tone should read naturally in English), ending
with "All your responses to the user MUST be entirely in English." (mirroring
the Vietnamese original's closing constraint).

`suggestions.py:51`'s prompt gets the same treatment: parameterize by
language, with an English variant instructing "Return exactly a JSON array of
English strings" and the call site (wherever `suggestions_for()` builds the
prompt) reads `session.state.get("language", "vi")`.

## Related Code Files

- Modify: `src/services/trip_intake.py` (`next_question`, add `language` param)
- Modify: `src/services/hotel_selection.py` (`_BUDGET_QUESTION.prompt`, guided-question flow)
- Modify: `src/services/trip_planner.py` (adjustment-note strings)
- Modify: `src/services/suggestions.py` (LLM prompt + call site)
- Modify: `src/models/schemas.py` (`_SAFE_ERROR_PREFIXES` handling, `_GENERIC_ERROR_MSG`)
- Modify: `src/agents/session.py` (retry-instruction string, `next_question()` call sites)
- Modify: `src/agents/prompts.py` (`SUPERVISOR_PROMPT_EN` real text, `SUPERVISOR_ROUTER_PROMPT` genericized)
- Modify: `src/api/routes.py` (generic 500-error detail strings)
- Modify: `locales/en/LC_MESSAGES/messages.po`, `locales/vi/LC_MESSAGES/messages.po` (+ recompiled `.mo`)

## Implementation Steps

1. Re-run `pybabel extract -F babel.cfg -o locales/messages.pot src/` after
   wrapping strings (steps 2-8 below) to regenerate the template with real
   msgids, then `pybabel update -i locales/messages.pot -d locales -l en -l vi`.
2. Wrap `_SAFE_ERROR_PREFIXES` strings + `_GENERIC_ERROR_MSG` in `schemas.py`
   with `t()`; thread `language` into `sanitize_system_error(text, *, session_id=None, language="vi")`
   and update its one call site in `routes.py:129`.
3. Add `language` param to `TripIntakeState.next_question()`; wrap its 4
   returned strings with `t()`.
4. Add `language` param to the hotel budget guided-question flow in
   `hotel_selection.py`; wrap `_BUDGET_QUESTION.prompt` (not the option
   labels — out of scope, see above).
5. Wrap the confirmed-reachable adjustment-note strings in `trip_planner.py`
   with `t()`, threading `language` from whatever state/context each
   function already receives (trace each call site — some may need a new
   `language` parameter added to their function signature).
6. Update `session.py`: thread `language` into both `next_question()` calls
   (lines ~805, ~817) and localize the retry-instruction string (~829-832).
7. Write `SUPERVISOR_PROMPT_EN` in `prompts.py` (real English translation);
   genericize `SUPERVISOR_ROUTER_PROMPT`'s Vietnamese-only framing line.
8. Parameterize `suggestions.py`'s prompt by language; update its call site
   to pass `session.state.get("language", "vi")`.
9. Wrap the generic 500-error strings in `routes.py`'s three handlers with
   `t(..., request.language)` (planner_chat has `request` in scope; the two
   utility endpoints stay Vietnamese-only, out of scope per above).
10. `pybabel compile -d locales` — commit both `.po` and `.mo` files.
11. Manual smoke test: send a `planner_chat` request with `language: "en"`
    for a fresh session and confirm the LLM reply, a guided question (trigger
    by omitting budget in the composed message), and a deliberately-triggered
    safe error all come back in English.

## Success Criteria

- [ ] Every string in the Scope list above is routed through `t()` /
      `SUPERVISOR_PROMPT_EN` / a parameterized prompt.
- [ ] `pytest` passes with **zero** existing assertion changes on the default
      (`language` omitted / `"vi"`) path — this is the hard gate for this
      phase; any red test on the default path means a `vi` msgstr drifted
      from the original literal and must be fixed before merging.
- [ ] New manual/automated check (Phase 5 formalizes this) confirms English
      output for each of the 8 scoped string categories.
- [ ] `locales/*/LC_MESSAGES/messages.mo` are committed and load without
      error (`gettext.translation()` doesn't raise `FileNotFoundError` for
      either language).

## Risk Assessment

- **Risk (highest in this plan):** editing ~120 real user-facing strings
  across 8 files is exactly the kind of mechanical sweep where a `vi` msgstr
  ends up NOT byte-identical to the original (extra/missing space, changed
  punctuation), silently breaking one of the ~700 existing Vietnamese test
  assertions or a subtler runtime behavior (e.g. `_has_budget_signal`'s
  regex matching against reply text, if any test greps reply content).
  **Mitigation:** step order wraps strings with `t()` but keeps the Python
  source `msgid` string literal EXACTLY as it was (the `t()` call's first
  argument IS the original string, unchanged) — the only new failure mode is
  the `vi.po` `msgstr` diverging from its own `msgid`, which is directly
  diffable (`msgid == msgstr` for every Vietnamese entry) and worth a small
  test in Phase 5 that parses the compiled `vi` catalog and asserts
  `msgid == msgstr` for all string keys, catching drift a code reviewer
  might miss.
- **Risk:** `next_question()`/adjustment-note functions gaining a `language`
  parameter changes their signature, breaking any test or caller that
  invokes them positionally without expecting a new arg. **Mitigation:**
  add `language: str = "vi"` as a keyword-only or trailing-default parameter
  (never inserted before existing positional args) so every existing call
  site compiles unchanged and defaults to current behavior.
- **Risk:** `SUPERVISOR_PROMPT_EN`'s translated instructions produce
  different LLM behavior than the Vietnamese original (tone, tool-call
  discipline) since it's a new prompt, not a mechanical transform.
  **Mitigation:** step 11's manual smoke test specifically exercises the
  tool-calling paths (recommend/select hotel, finalize) in English mode;
  Phase 5 adds at least one automated test per major intent (greeting,
  hotel-related, edit request) run with `language="en"`.
