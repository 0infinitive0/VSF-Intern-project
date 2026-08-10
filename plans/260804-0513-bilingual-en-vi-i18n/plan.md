---
title: "Bilingual EN/VI i18n"
description: "Add a manual English/Vietnamese language toggle across the frontend chat UI and the backend chat replies/AI prompts, using react-i18next on the frontend and Python gettext/Babel on the backend, while keeping the intake-form wire protocol to the backend Vietnamese so the existing NLU/closed-set matching is untouched."
status: pending
priority: P1
effort: "5-7d"
tags: [i18n, frontend, backend, react-i18next, gettext, langgraph, prompts]
blockedBy: []
blocks: []
created: 2026-08-04
updated: 2026-08-04
---

# Bilingual EN/VI i18n

## Overview

Today the app is Vietnamese-only end to end: `frontend/src/strings.ts` hardcodes
every UI string, and the backend's LLM system prompt
(`src/agents/prompts.py:6`, `:32`) hardcodes *"All your responses to the user
MUST be entirely in Vietnamese."* Deterministic backend reply text
(`TripIntakeState.next_question()`, the hotel budget question, trip-edit
adjustment notes) is likewise hardcoded Vietnamese.

This plan adds a manual EN/VI toggle (nav bar, persisted, defaults to
Vietnamese) that switches:
1. All static frontend UI chrome (labels, buttons, chip text, errors, empty
   states) — via `react-i18next`.
2. Backend-produced chat content: the LLM's replies/suggestions and the
   deterministic reply strings the chat turn returns — via a small
   `gettext`/Babel-backed catalog, with the selected language threaded from
   the frontend through `PlannerChatRequest` into `TripState`.

### Explicitly out of scope (confirmed with user)

Backend-*sourced dynamic* content — the destinations dropdown
(`IntakeStatus.available_destinations`) and hotel budget tier labels
(`IntakeStatus.budget_options`), plus the intake closed-set **wire values**
sent back to the backend (preferences/companions/pace/day-rhythm) — stays
Vietnamese regardless of the UI language. The intake form's *display* labels
for those closed-set chips DO translate; only the string actually sent to the
backend (via `composeIntakeMessage`) stays the canonical Vietnamese phrase the
backend's regex/closed-set matching expects
(`src/services/trip_intake.py:30-64`, `src/services/hotel_selection.py:509-531`).
This is a deliberate decoupling of *display label* from *wire value*, not a
gap — but the destinations/budget dropdowns showing Vietnamese text in an
English UI is a known, accepted limitation. A follow-up plan can close it by
making those backend-generated lists locale-aware if wanted later.

## Why this shape (key findings from codebase research)

- `frontend/src/strings.ts` is already commented *"This is the i18n seam: a
  bilingual retrofit becomes a translation task, not a sweep"* — it was built
  for exactly this. 12 files import it.
- `IntakeParametersForm`'s chip **state** stores the same Vietnamese string
  used as the **display label** (`S.intakePreferenceOptions` etc.), and
  `compose-intake-message.ts` joins those strings verbatim into one Vietnamese
  sentence the backend's `_llm_extract_intake_facts` / `_parse_free_text_budget`
  parse by regex/closed-set match. Translating the display label without
  decoupling it from the wire value would silently break intake extraction
  for English users.
- The LLM system prompt (`SUPERVISOR_PROMPT`) is a **static string** passed
  once to `create_react_agent(..., prompt=SUPERVISOR_PROMPT)` in
  `src/agents/graph.py:89-95`, at session-creation time
  (`create_chat_session`). LangGraph's prebuilt agent supports a **callable**
  `prompt` that receives graph state per invocation (confirmed against
  current LangGraph 1.2.9 docs) — this lets the prompt vary per turn from
  `state["language"]` without rebuilding the agent when the user toggles
  language mid-conversation.
- Grepping backend service files for Vietnamese text found ~270 diacritic-bearing
  lines across `trip_intake.py`, `hotel_selection.py`, `trip_planner.py`,
  `suggestions.py`, `schemas.py`, `session.py`, `routes.py`. Roughly 20 test
  files pin **700+** assertions containing Vietnamese text. Sampling showed
  most of those are either (a) input-side fixtures/parsed-value assertions
  (e.g. `updated.duration == "5 ngày"`) that don't change under this plan
  (wire protocol stays Vietnamese), or (b) genuine output-text assertions
  (e.g. `assert reply == "Đã cập nhật lịch trình."`) that DO need the backend
  change. **Design constraint to keep this safe:** every catalog `vi` value
  must be byte-identical to the current hardcoded string, and `language`
  must default to `"vi"` everywhere. That way the existing test suite keeps
  passing unmodified on the default path; only new English-path tests are
  net-new (Phase 5). This is the same "retrofit, not sweep" principle the
  frontend already used.
- `sanitize_system_error()` (`src/models/schemas.py:277-292`) means most
  `raise ValueError(...)` strings inside tool code are **never actually shown
  to the user** — anything not in `_SAFE_ERROR_PREFIXES` collapses to one
  generic message. Phase 4 only needs to localize the 5 safe-prefixed strings
  + the generic fallback, not every `ValueError` in the codebase.

## Goals

| # | Goal | Priority |
|---|------|----------|
| 1 | Manual EN/VI toggle in the nav, persisted (localStorage), defaults to Vietnamese | P1 |
| 2 | All static frontend UI text translated via `react-i18next`, zero hardcoded strings left in JSX | P1 |
| 3 | Intake chip wire values stay Vietnamese (backend NLU untouched) while display labels translate | P1 |
| 4 | LLM chat replies and suggestion chips follow the selected language | P1 |
| 5 | Deterministic backend reply text (guided questions, adjustment notes, safe error strings) follows the selected language | P1 |
| 6 | Existing test suite passes unmodified on the Vietnamese default path; new tests cover the English path | P1 |

## Phases

| # | Phase | Status |
|---|-------|--------|
| 1 | [Phase 1: Frontend i18n Foundation](./phase-01-start.md) | Pending |
| 2 | [Phase 2: Frontend String Migration & Wire-Protocol Decoupling](./phase-02-frontend-string-migration-wire-protocol-decoupling.md) | Pending |
| 3 | [Phase 3: Backend i18n Foundation & Language Plumbing](./phase-03-backend-i18n-foundation-language-plumbing.md) | Pending |
| 4 | [Phase 4: Backend Message Localization & Dynamic LLM Prompt](./phase-04-backend-message-localization-dynamic-llm-prompt.md) | Pending |
| 5 | [Phase 5: Testing, Verification & Regression Safety](./phase-05-testing-verification-regression-safety.md) | Pending |

## Architecture at a glance

```
Frontend                                   Backend
─────────────────────────────────────────  ──────────────────────────────────────────
i18next + react-i18next                    src/i18n/ (gettext + Babel catalogs)
  locales/en.json, locales/vi.json           locales/en/LC_MESSAGES/messages.po/.mo
  useTranslation() in every component        locales/vi/LC_MESSAGES/messages.po/.mo
  <LanguageToggle> in App.tsx nav            t(key, language, **kwargs) helper
  persisted to localStorage("vota-language")
                                            TripState.language: "vi" | "en" (default "vi")
IntakeFormState stores CANONICAL KEYS        initial_state() / process_chat_turn plumb it
  (e.g. "beach"), not display labels         from PlannerChatRequest.language
lib/intake-options.ts maps
  canonical key -> VI wire string          build_trip_agent(): prompt=callable reading
  (byte-identical to backend closed sets)     state["language"] instead of a static string
composeIntakeMessage() still emits the       (SUPERVISOR_PROMPT_VI / SUPERVISOR_PROMPT_EN)
  Vietnamese sentence the backend expects
                                            suggestions_for() / next_question() / adjustment
chat-client.ts sends {message, language}     notes / safe error strings -> t(key, language)
  on every /planner_chat call
```

## Success Criteria

- [ ] Toggling the nav language switch changes every static UI string immediately, no reload.
- [ ] Selected language persists across a page reload (localStorage).
- [ ] With language = English, submitting the intake form still produces a
      Vietnamese wire message the backend parses correctly (intake facts,
      preferences, budget all land in `session.intake_state`/`hotel_pref_state`
      exactly as before).
- [ ] With language = English, the LLM's chat reply and suggestion chips are
      in English; with language = Vietnamese (default), behavior is
      byte-identical to before this plan.
- [ ] `pytest` passes with zero changes required to existing assertions
      (default-language path only); new English-path tests pass.
- [ ] `npm run typecheck` and `npm run lint` (oxlint) pass in `frontend/`.
- [ ] No component in `frontend/src` contains a hardcoded user-facing string
      outside `locales/*.json` (spot-checked via `grep` for stray Vietnamese
      diacritics/ASCII UI text in `.tsx` files, excluding the wire-protocol
      layer which is intentionally Vietnamese).

## Open Questions

None — scope (UI + AI-generated content, not backend dynamic option data) and
switch UX (manual toggle, default Vietnamese) were confirmed with the user
before this plan was written.

<!-- slug: bilingual-en-vi-i18n -->
