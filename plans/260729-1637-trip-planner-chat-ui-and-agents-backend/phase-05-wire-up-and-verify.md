---
phase: 5
title: "Wire up, verify, retire the Jinja page"
status: pending
priority: P1
effort: "5h"
dependencies: [3, 4]
---

# Phase 5: Wire up, verify, retire the Jinja page

## Overview

Point the React app at the real backend, close the environment gaps that only appear
when both halves run together, retire the interim server-rendered chat page, and update
the docs this work makes wrong.

> Supersedes the 2026-07-29 version. Its lead item — "the root dependency manifest is
> missing" — was **resolved upstream** in commit `bff186c`; the task is now to verify
> the restored manifest, not to author one. The Jinja-page retirement (D8) is new.

## Requirements

- Functional: full flow against the real backend — intake → guided preferences → hotel
  pick → plan → modify → finalize, in two concurrent browser sessions.
- Functional: `docker compose up` yields a backend whose chat model is present.
- Functional: the restored root `requirements.txt` actually installs a working app.
- Functional: `GET /chat`, `src/templates/`, and the Jinja2 dependency are gone (D8).
- Non-functional: quality gate per D11.
- Non-functional: a new developer runs both halves from the setup guide alone.

## Architecture

**Verify the dependency manifest; do not author one.** Commit `0ba866f` deleted the root
`requirements.txt`; `bff186c` restored it (538 bytes). What is unverified is whether it
is *sufficient* — it was restored, not regenerated, so it may predate upstream's
additions: `langgraph`, the `langchain-*` split packages, `supabase`,
`pydantic-settings`, and OpenRouter's client path in `src/services/llm.py`. Prove it in a
**fresh** venv, not the working one, which has accumulated whatever was installed by hand
since July.

Removing Jinja2 in this phase means `fastapi.templating`'s dependency (`jinja2`) may
become unused — check before pruning it, since other tooling may pull it in.

**Retiring `GET /chat` (D8).** The page was the only UI between Phase 1 and Phase 4. Once
React completes the full flow against the real backend, remove:

- the `GET /chat` route and the `Jinja2Templates` setup in `src/main.py`
- `src/templates/chat.html` and the `src/templates/` directory
- `jinja2` from `requirements.txt` if nothing else needs it

Do this **after** step 1 proves React works end to end, not before. Confirm with the team
first — `plan.md` lists "does anything outside the repo consume `GET /chat`?" as an open
question, and a demo bookmark is a cheap thing to break.

**The compose gap is real.** `docker-compose.yml`'s `ollama-pull` pulls only `bge-m3`
(embeddings). The chat model — `llama3.1` by default per `config.py` — is never pulled,
so a fresh `docker compose up` gives a backend that embeds fine and cannot chat. Fix
`ollama-pull` to pull both, and record the cost: `llama3.1` 8B is ~4.7GB. On the recorded
t3.micro target (~900Mi RAM, swap-dependent) that is not viable, which is why the
provider is configurable.

**Environment matrix to state plainly in the setup guide:**

| Setting | Local dev | Deployed |
|---|---|---|
| `LLM_PROVIDER` | `ollama` | `openai` / `openrouter` |
| `LLM_MODEL` | `llama3.1` | `gpt-4o-mini` or an OpenRouter id |
| `EMBEDDING_PROVIDER` | `ollama` (`bge-m3`) | `ollama` (`bge-m3`) |
| Frontend | Vite dev server + `/api` proxy | built assets, host TBD |

Embeddings have no cloud fallback here: 1024-dim `bge-m3` is locked into both vector
stores. Ollama is required in every environment; only the *chat* model is swappable.

## Related Code Files

- Modify: `requirements.txt` (root) — verify and top up; prune `jinja2` if now unused
- Modify: `docker-compose.yml` — `ollama-pull` pulls the chat model too
- Modify: `src/main.py` — remove the `GET /chat` route and Jinja2 setup
- Delete: `src/templates/chat.html`, `src/templates/`
- Modify: `.env.example` — `SESSION_TTL_SECONDS`, `MAX_SESSIONS`, `DEBUG_TRIP_PLAN_FILE`
  (`LLM_PROVIDER`, `LLM_MODEL`, `EMBEDDING_PROVIDER` are already there — verify, don't
  duplicate)
- Modify: `docs/setup/` — running both halves, the matrix above, the 120s proxy note
- Modify: `ARCHITECTURE.md` — agent / vector store / frontend sections
- Modify: `README.md` — quickstart for both halves
- Create: `tests/test_api/test_chat_flow.py`
- Read only: `Dockerfile`, `plans/260723-1015-v-ota-poc-master-roadmap/phase-05-web-chat-ui.md`

## Implementation Steps

1. Run the frontend against the real backend. Fix contract drift **in whichever side
   deviated from `docs/chat_api_contract.md`** — do not amend the contract to match a bug.
2. Verify the root `requirements.txt` in a **fresh** venv: `pip install -r
   requirements.txt`, then `python -c "import src.main, src.agents"` and boot uvicorn.
   Add whatever is missing; do not regenerate from `pip freeze` on the working venv.
3. Fix `ollama-pull` to pull the chat model as well as `bge-m3`; verify a chat turn
   succeeds from a clean `docker compose up`.
4. Add the new session settings to `.env.example` with comments; verify
   `LLM_PROVIDER=openai` works with no code change.
5. Concurrency check: two browsers, two destinations, both reaching different hotel lists
   and different itineraries, with neither request blocking the other.
6. Add `tests/test_api/test_chat_flow.py` covering the full turn sequence with the
   planner mocked — intake question → guided preference questions → hotel options →
   selection → plan → modify → finalize → reset.
7. **Retire the Jinja page (D8)**, only now that step 1 has proven React works: confirm
   with the team, then remove the route, the templates directory, and `jinja2` if unused.
   Re-run step 2's fresh-venv check afterwards.
8. Run the D11 gate: `pytest tests -q --ignore=tests/test_qdrant_schema.py` against the
   Phase 1 baseline, and `ruff check` on every file this plan touched. Fix regressions;
   leave the 5 known failures and the 937-error backlog alone.
9. Update `ARCHITECTURE.md`: the AI Agent and Vector Store sections are still unfilled
   template text, and "Frontend (React/Next.js)" now has a real answer — settle it in
   favour of Vite. Document the `services / agents / cli / api` layering and the one-way
   import rule.
10. Update the setup guide with both run commands, the environment matrix, and the 120s
    proxy-timeout note from Phase 3.
11. Run `detect_changes({scope: "compare", base_ref: "main"})` per `CLAUDE.md` before
    committing; report affected symbols and flows.

## Success Criteria

- [ ] Full flow passes against the real backend from a clean checkout
- [ ] `pip install -r requirements.txt` in a **fresh** venv is sufficient to boot the app
- [ ] Clean `docker compose up` produces a backend that can chat, not only embed
- [ ] Two concurrent sessions verified independent, including their hotel lists
- [ ] `GET /chat` returns 404; `src/templates/` no longer exists
- [ ] Nothing in the tree imports `Jinja2Templates`
- [ ] D11 gate: no new test failures vs the Phase 1 baseline; `ruff` clean on touched files
- [ ] `ARCHITECTURE.md` has no `[mô tả]` / `[choice]` placeholders in touched sections
- [ ] `ARCHITECTURE.md` documents the layering and the one-way import rule
- [ ] The setup guide gets a new developer running both halves unaided
- [ ] `docs/chat_api_contract.md` matches the shipped implementation field for field

## Risk Assessment

| Risk | Mitigation |
|---|---|
| Contract drift resolved by editing the doc instead of the code | Step 1 states the direction; the doc is the frozen artefact |
| **The Jinja page is removed before React actually works**, leaving no UI | Step 7 is explicitly gated on step 1 passing, and on team confirmation. It is the last functional change in the plan |
| Something outside the repo bookmarks `GET /chat` | Listed as an open question in `plan.md`; step 7 requires confirming with the team, not just grepping the repo |
| The restored `requirements.txt` is assumed complete because it exists | Step 2 proves it in a *fresh* venv. "Restored" is not "verified" — it was brought back by `bff186c`, not regenerated against current imports |
| Pruning `jinja2` breaks something that pulls it in transitively | Step 7 re-runs the fresh-venv check after removal |
| `llama3.1` pull makes compose startup slow or fails on small disks | Document the ~4.7GB cost and the cloud-provider escape hatch |
| Deployment target cannot run the chat model | Provider is already configurable upstream; step 4 proves the cloud path with no code change |
| The D11 gate is read as "make it green" and the phase absorbs 937 lint errors | The gate compares against a recorded baseline and scopes lint to touched files; the backlog is an explicit non-goal |
| Doc updates sprawl into a repo-wide rewrite | Only sections this work makes wrong. The 2026-07-29 draft deferred the rest to `plans/260723-0910-docs-consolidation-audit/`, which **does not exist** — there is no owner for the wider docs backlog, so resist absorbing it here and raise it separately if it blocks |
| `ENABLE_ITINERARY_REUSE` path untested in server mode | Leave default-off; if enabled, verify one reuse hit and one miss before merge |
