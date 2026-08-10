---
phase: 1
title: "Freeze the contract, clean the tree"
status: pending
priority: P1
effort: "3h"
dependencies: []
---

# Phase 1: Freeze the contract, clean the tree

## Overview

Write down the HTTP contract so Phases 3 and 4 can proceed in parallel; revert the
working tree so the broken `/ask` endpoint goes away and the working `GET /chat` page
comes back; and delete the two dead blocks in `process_chat_turn` so the contract
describes code that actually executes.

No refactoring here. This phase produces a frozen interface and a tree with no failing
endpoints and no unreachable branches.

> Supersedes the 2026-07-29 version of this phase, which assumed reverting `main.py`
> only dropped a static-page hook. It now also **restores** `GET /chat` — see D8.

## Requirements

- Functional: `docs/chat_api_contract.md` covers all four endpoints, every `stage`
  value, `hotel_options`, `trip_plan`, `suggestions`, and error semantics.
- Functional: no endpoint in the tree raises `TypeError` on a normal request.
- Functional: `GET /chat` works after the revert — it is the only UI until Phase 4.
- Functional: the CLI flow still works end to end.
- Non-functional: quality gate per D11 — no new test failures, `ruff` clean on the
  files this phase edits.

## Architecture

**The revert (decision D6) cuts both ways.** The working tree diff is:

| File | Working-tree delta vs HEAD | Effect of reverting |
|---|---|---|
| `src/api/routes.py` | `+58` — adds `GET /ask` | Drops the broken endpoint |
| `src/main.py` | `-10` — removes `Jinja2Templates`, the `templates` global, and `GET /chat` | **Restores the working chat page** |
| `src/api/static/chat.html` | untracked | Not touched by `git checkout`; delete explicitly |

Reverting both files with `git checkout HEAD -- src/api/routes.py src/main.py` is one
move. Confirm the `main.py` restore is what you want *before* running it — an engineer
reading only the 2026-07-29 plan text would expect the revert to remove a UI, when it
adds one back.

`/ask` depends on three things `supabase_search.py` does not provide: the `filters=`
kwarg on `search_attractions`, a `search_type="auto"` branch in
`extract_search_filters`, and diacritic-insensitive destination matching. All three
re-verified 2026-07-30; see `plan.md`. HEAD's `/search_attractions` and
`/search_hotels` are unaffected — they never pass `filters`.

**What is deliberately not restored.** The diacritic-folding fix (`_fold`,
`_get_destinations`) is a genuine bug fix still recoverable from `stash@{0}`: without
it `_get_destination_id_by_name` uses `ilike %name%` (`supabase_search.py:85-92`), so
"Ho Chi Minh" silently fails to match "Hồ Chí Minh" and the city filter is dropped. It
applies to the search path this plan is deleting, so it is out of scope — but it still
affects `/search_hotels`. Raise it as its own ticket; do not silently drop the
knowledge, and do not run `git stash drop`.

**Dead-code removal is a prerequisite for the contract, not a nicety.** Two blocks in
`process_chat_turn` never execute:

- `chat_session.py:300` — `if False and session.pending_trip_change is not None:`
- `chat_session.py:313-321` — `change_intent = None` immediately followed by
  `if is_saved_plan_edit and change_intent is not None:`

A contract derived by reading the source as it stands would document a deterministic
scope-clarification turn and a deterministic modification turn that no user can ever
reach. Delete them first, then document what is left.

Deleting them also orphans `session.pending_trip_change`, `_scope_question`,
`_saved_duration_days`, and the `parse_day_scope` / `modify_trip_plan` imports.
**Check each before removing** — `modify_trip_plan` is still in the agent's tool list
(`planner_tools.py:571`) and must stay importable there; only the direct call from
`chat_session.py` goes.

**Contract note.** The contract extends the shipped `PlannerChatResponse` (D10) rather
than inventing a parallel model. `reply` and `suggestions` keep their exact current
meaning, because `GET /chat` reads them and must keep working through Phase 4.

## Related Code Files

- Modify: `src/api/routes.py` — revert to HEAD (drops `/ask`)
- Modify: `src/main.py` — revert to HEAD (restores `GET /chat` and the Jinja2 setup)
- Modify: `src/services/chat_session.py` — delete the two dead blocks and whatever
  they orphan
- Delete: `src/api/static/chat.html` and the now-empty `src/api/static/`
- Create: `docs/chat_api_contract.md`
- Read only: `src/services/chat_session.py` (source of truth for the state machine),
  `src/cli/planner_tools.py`, `src/services/hotel_selection.py`,
  `src/services/guided_question.py`, `src/models/schemas.py`

## Implementation Steps

1. Record the D11 baseline before touching anything, and commit it to the phase notes:
   ```
   pytest tests -q --ignore=tests/test_qdrant_schema.py   # expect 5 failed, 193 passed
   ruff check src | tail -3                               # expect 937 errors
   ```
2. Confirm nothing besides the working-tree diff references `/ask` or the static page:
   `grep -rn "/ask\|api/static" src/ docs/ --include="*.py" --include="*.md" --include="*.html"`.
3. Open a tracking issue quoting the three `/ask` regressions from `plan.md` verbatim,
   so the knowledge survives the revert. The stash entry stays; do not drop it.
4. Revert: `git checkout HEAD -- src/api/routes.py src/main.py`. Confirm `GET /chat`
   came back — this is the intended, non-obvious half of the revert.
5. Delete `src/api/static/chat.html` and the now-empty `src/api/static/`.
6. Delete the two dead blocks in `chat_session.py`. Then, for each of
   `pending_trip_change`, `_scope_question`, `_saved_duration_days`, `parse_day_scope`,
   run `findReferences` (or `grep -rn`) and remove only what has no remaining caller.
   Leave `modify_trip_plan` importable — it is still an agent tool.
7. Verify the app still imports and serves: `uvicorn src.main:app` → `/health`,
   `/api/v1/status`, `/docs`, and `GET /chat` all respond.
8. Drive `GET /chat` through one full conversation in a browser: intake → hotel prefs →
   hotel list → pick a chip → itinerary. This is the regression net for step 6.
9. Write `docs/chat_api_contract.md` from the `plan.md` contract section. It must
   include: the four endpoints; the **seven-branch** routing order including sub-branches
   1a/1b/1c; the `stage` derivation table; the `hotel_options` shape; the relationship
   between `suggestions[].value` and `hotel_options[].index`; and error semantics.
   Derive the branch order by reading `chat_session.py:241,264,270,279,323,338,354`
   directly — do not copy it from memory or from the pre-2026-07-30 plan text.
10. Run the CLI once to confirm this phase changed nothing there:
    `python scripts/poc_trip_planner.py` → intake → hotel list → pick → itinerary.
11. Re-run the D11 checks from step 1 and diff against the recorded baseline.

## Success Criteria

- [ ] `git diff HEAD -- src/api/ src/main.py` is empty
- [ ] `src/api/static/` no longer exists
- [ ] `uvicorn src.main:app` starts; `/health`, `/api/v1/status` and `GET /chat` all 200
- [ ] A full conversation completes in the browser via `GET /chat`
- [ ] `grep -n "if False" src/services/chat_session.py` returns nothing
- [ ] No unreachable branch remains in `process_chat_turn`; no orphaned helper left behind
- [ ] `docs/chat_api_contract.md` documents 4 endpoints, 6 stage values, the 7-branch
      routing order with sub-branches, the `stage` derivation table, and both payloads
- [ ] CLI completes intake → hotel pick → itinerary unchanged
- [ ] D11 gate: same 5 test failures as baseline, no new ones; `ruff check` clean on
      `src/services/chat_session.py`
- [ ] A tracking issue exists for the diacritic-folding regression

## Risk Assessment

| Risk | Mitigation |
|---|---|
| **The revert is executed expecting it only removes things** and the `GET /chat` restore is a surprise | Step 4 names it explicitly; the file table above shows the sign of each delta. D8 records that keeping `/chat` alive until React ships is deliberate |
| Someone is using `/ask` for demos and loses it without warning | It is broken today (`TypeError` on the attraction path); call it out in the commit message and the tracking issue |
| `stash@{0}` gets dropped and the search fix is lost for good | Step 3 files a tracking issue quoting the exact regressions; instruct not to run `git stash drop` |
| Dead-code removal takes a live helper with it | Step 6 requires a reference check per symbol; step 8's browser run exercises the surviving paths |
| The contract is written from the stale four-branch description | Step 9 derives it from named line numbers in the current file, and lists sub-branches 1a/1b/1c which did not exist in July |
| Branch 1c (drop the pending list) is omitted from the contract, so Phase 3 reintroduces the hotel-list trap | Named explicitly in step 9 and in `plan.md`'s state machine; it is the fix commit `3bd9e80` shipped |
| Reverting `main.py` breaks an unrelated working-tree change | `git diff src/main.py` confirms the only delta is the Jinja2 import, the `templates` global and the `/chat` route |
