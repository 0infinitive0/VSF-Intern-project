---
phase: 5
title: "Testing, Verification & Regression Safety"
status: pending
priority: P1
effort: "1.5d"
dependencies: [4]
---

# Phase 5: Testing, Verification & Regression Safety

## Overview

Prove the default (Vietnamese) path is unchanged, add focused coverage for
the new English path, and do one end-to-end manual pass through the running
app with the language toggle. This phase is verification, not new features —
if it surfaces a regression, the fix belongs in whichever earlier phase owns
the broken area, not here.

## Requirements

- Functional: full existing `pytest` suite passes with no assertion changes.
- Functional: `npm run typecheck && npm run lint && npm run build` pass in
  `frontend/`.
- Functional: new tests exist for the English path covering the areas listed
  in Phase 4's Scope section.
- Manual: a human (or a browser-automation pass, only if the user explicitly
  asks for one per this repo's CLAUDE.md browser-automation rule) walks
  through: toggle to English → submit intake form → receive an English LLM
  reply → select a hotel → confirm itinerary text/adjustments render in
  English → toggle back to Vietnamese → confirm no leftover English strings.

## Test Plan

### Backend

1. **Regression gate:** run the full existing suite unmodified —
   `pytest tests/` — must be 100% green. This is the primary safety net for
   Phases 3-4's "byte-identical vi msgstr" constraint.
2. **New: catalog integrity test** (new file, e.g.
   `tests/test_i18n_catalog.py`) — parses the compiled `vi` `.mo` (or the
   `.po` source directly via `polib`/`babel.messages.pofile`, whichever adds
   less new dependency weight — prefer `babel.messages.pofile` since `Babel`
   is already a dependency from Phase 3) and asserts every entry's
   `msgstr == msgid` for the Vietnamese catalog. Also asserts every `vi`
   msgid has a **non-empty** `en` msgstr (catches an untranslated entry
   before it ships, since an empty `en` msgstr falls back to showing raw
   Vietnamese in "English" mode).
3. **New: English-path integration tests**, one per Phase 4 scope item,
   using `language="en"` in the request/session setup:
   - a fresh session's greeting/first guided question is in English
     (`next_question()` with `language="en"`)
   - the hotel budget question prompt is in English
   - a deliberately triggered safe error (e.g. missing plan when finalizing)
     returns the English string
   - `suggestions_for()` with `language="en"` produces English suggestion
     labels (mock the LLM call per existing test patterns in
     `tests/test_hotel_flow_tools.py`/similar — check how existing tests
     stub `get_llm`/agent calls before writing new ones, don't invent a new
     mocking approach)
   - a full `process_chat_turn` with `language="en"` on a message that
     triggers `_run_chat_agent` (the ReAct path) returns an English reply —
     mock the LLM response per existing conventions in
     `tests/test_chat_session.py`/`tests/test_agents/test_supervisor.py`
4. **New: wire-protocol invariance test** — confirm that regardless of
   `language`, `TripIntakeState`/`HotelPreferenceState` extraction from a
   Vietnamese-composed message (i.e. what `composeIntakeMessage()` produces)
   is unaffected. This is largely already covered by existing
   `test_trip_intake.py`/`test_hotel_selection.py` continuing to pass
   unmodified (Requirement above) — add one new test only if Phase 4 touched
   any function those tests exercise with a new `language` parameter, to
   confirm the default keyword argument path matches old positional-call
   behavior.

### Frontend

5. **New: `compose-intake-message` canonical-key regression test** — build
   an `IntakeFormState` using the new canonical keys (Phase 2) with a fixed
   set of values, call `composeIntakeMessage()`, and assert the output
   string matches EXACTLY what the pre-Phase-2 test (if one exists — check
   `frontend/` for existing intake message tests before writing a new
   fixture from scratch) produced for the equivalent Vietnamese-label input.
   This is the frontend half of Phase 4's "wire protocol invariance"
   guarantee.
6. Run `npm run typecheck`, `npm run lint`, `npm run build` — all must pass.
7. If a frontend test runner exists in this repo (check `frontend/package.json`
   scripts and any existing `*.test.ts`/`*.test.tsx` files — none were found
   during this plan's research, meaning frontend currently has no automated
   test runner configured), do NOT introduce a new testing framework as part
   of this plan; a Vitest setup is a separate concern. If none exists, step 5
   becomes a `ts-node`/`tsx`-run assertion script instead of a proper test
   file, OR is verified manually via the browser pass (step 9) plus the
   Python-side characterization test in step 4. Confirm which applies before
   writing step 5 and note the decision in the phase's implementation notes.

### Manual end-to-end pass

8. Start backend (`uvicorn`/whatever the project's dev script is — check
   existing docs/scripts before assuming) and `npm run dev` in `frontend/`.
9. Walk the flow described in "Manual" under Requirements above. Take note
   of anything that still shows Vietnamese in English mode — cross-check
   against the plan's "Explicitly out of scope" list (destinations dropdown,
   budget option chip labels) to confirm any remaining Vietnamese text is
   expected, not missed.

## Related Code Files

- Create: `tests/test_i18n_catalog.py`
- Create: new English-path test cases (append to existing files per their
  current organization — e.g. `tests/test_trip_intake.py`,
  `tests/test_hotel_selection.py`, `tests/test_chat_session.py`,
  `tests/test_api/test_chat_flow.py` — do not create parallel
  `test_*_en.py` files if the existing convention is one file per module;
  match existing structure).
- Modify: none required outside test files (this phase should not need
  production-code changes if Phases 1-4 were done correctly; if it does,
  that's a signal to fix the owning phase, not patch around it here).

## Implementation Steps

1. Run `pytest tests/` before writing anything new — confirm baseline green
   (catches any Phase 3/4 regression immediately, before this phase's own
   tests could mask it).
2. Write `tests/test_i18n_catalog.py` (catalog integrity, per Test Plan #2).
3. Add English-path integration tests per Test Plan #3, matching each
   existing test file's current mocking/fixture conventions (read the
   nearby existing tests before writing new ones — this repo's test suite
   has strong, deliberate conventions per its own module docstrings).
4. Add the wire-protocol invariance check per Test Plan #4/#5 (backend
   and/or frontend, per what step 7's investigation finds).
5. Run `pytest tests/` again — full suite green, including new tests.
6. Run `npm run typecheck && npm run lint && npm run build` in `frontend/`.
7. Do the manual end-to-end pass (steps 8-9 above); log any finding as a
   follow-up note in this plan rather than silently patching without
   updating the relevant phase's Success Criteria.

## Success Criteria

- [ ] `pytest tests/` green, including new tests, on the default and
      English paths.
- [ ] `frontend/`: `npm run typecheck`, `npm run lint`, `npm run build` all
      green.
- [ ] Catalog integrity test confirms no untranslated (empty `en` msgstr)
      entries ship.
- [ ] Manual pass confirms: toggle works instantly, persists on reload,
      intake form submission in English mode still reaches the backend
      correctly, LLM reply/suggestions/guided questions are in English, and
      the only remaining Vietnamese text in English mode is the documented
      out-of-scope destinations/budget-option content.

## Risk Assessment

- **Risk:** "no frontend test runner exists" (a real possibility per this
  plan's research — no `*.test.ts` files were found) means Phase 2's
  `composeIntakeMessage` refactor has no automated regression guard.
  **Mitigation:** step 7 makes the decision explicit rather than silently
  skipping coverage; at minimum, the Python-side characterization test
  already covering the composed-message shape from the backend's receiving
  end (`tests/test_intake_form_characterization.py`) partially covers this
  indirectly, and the manual pass (step 9) exercises the real path.
- **Risk:** mocked-LLM tests for the English path assert on exact English
  wording that's brittle to future prompt-copy tweaks. **Mitigation:** favor
  asserting on structural/functional properties (e.g. "reply does not
  contain Vietnamese diacritics" via a regex, "reply is non-empty",
  "the correct tool was called") over pinning exact English sentences,
  matching how the existing Vietnamese tests already tend to assert on
  substrings/keywords (e.g. `"bao lâu" in reply.lower()`) rather than full
  reply equality in most places sampled during research.
