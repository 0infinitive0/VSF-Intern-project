---
title: "Eval refresh — graph-plane rewire, latency percentiles, token cost"
description: "Rewire the broken Layer 2 e2e eval onto the LangGraph plane, add P50/P95/P99 latency and input/output-token cost accounting to both layers, then publish a refreshed report and baseline."
status: in-progress
priority: P1
branch: "main"
tags: [eval, ragas, latency, cost, observability, langgraph]
blockedBy: []
blocks: []
effort: "3-4d"
created: 2026-08-18
---

# Eval refresh — graph-plane rewire, latency percentiles, token cost

## Overview

`eval/` scores retrieval (Layer 1) and end-to-end conversations (Layer 2) with RAGAS. Two
things are wrong with it today:

1. **Layer 2 does not import.** `eval/harness/e2e_eval.py:18` imports `create_chat_session`,
   `derive_stage`, `handle_frontend_hotel_selection`, and `process_chat_turn` from
   `src.agents.session`. The graph cutover deleted three of the four — `session.py:39-45`
   documents the removal in its own comment. No e2e number can be refreshed until the harness
   is rewired onto the LangGraph plane that replaced them.
2. **Performance and cost are not measured.** Latency is recorded per record but only ever
   *summed* (`report.py:204-205`); there are no percentiles. Token spend is not captured at
   all — `eval/README.md:141-148` states outright that cost is reported as wall-clock plus
   call count.

This plan fixes both and re-runs the harness so the committed report and baseline describe the
system as it exists now, not as it existed on 2026-08-11.

## Decisions already made

| Decision | Choice | Why |
|---|---|---|
| Layer 2 scope | Rewire onto the graph plane, not delete | e2e is where a hallucinated hotel surfaces; retrieval-only eval cannot see it |
| Cost attribution | App-side and judge-side measured and reported **separately**, never summed | They answer different questions: "what does a user turn cost" vs "what does an eval pass cost". One merged figure answers neither |
| Latency/cost thresholds | Observe and propose only, gate nothing | Matches how `report.py::threshold_candidates` already treats retrieval floors; latency over live Supabase + OpenAI has no measured distribution yet, so a ceiling would be a coin flip |
| Instrumentation location | **Harness-only, no exception** (revised 2026-08-18 after Phase 1) | The planned `llm.py` exception turned out to be unnecessary — the library already enables streamed usage for OpenAI-hosted endpoints and already leaves the custom-base-URL providers off. The `context_recorder.py` precedent now governs without exception: this plan touches no production file |
| Streamed-usage reporting | Neither a production change nor a harness override — **already on**, pinned by test (user decision, 2026-08-18) | Measurement replaced the premise. Eval and production are identical in streaming today, so no asterisk arises. What was worth keeping from the original reasoning is the *scoping*: a test now pins that OpenRouter and Cloudflare stay off, so a later cleanup cannot widen `include_usage` to endpoints nobody verified |
| Unpriced model | Hard failure, never a silent `$0` | A model missing from the price table must abort the cost section, not quietly report free |
| Language scope | Vietnamese only; EN mirrors filtered out, BR-10 crosslang probes kept | User decision. Filtering by "is a mirror" rather than by `language` is what keeps BR-10 measurable — see the scope constraint below |
| How EN is excluded | Loader-level filter, records left in the files | Reversible with a flag. Deleting would throw away the 14-record EN rationale rewrite from the 2026-08-11 pass and make re-enabling a re-authoring job |

## Scope constraint — Vietnamese only

**The eval scores Vietnamese only** (user decision, 2026-08-18). The 14 English mirror records are
excluded from every run.

**Excluded — 14 EN mirrors + 1 EN conversation.** A mirror is a straight translation of a VI record
(`hotel-nhatrang-city-vi` → `hotel-nhatrang-city-en`, "khách sạn ở Nha Trang" → "a hotel in Nha
Trang"). They test English-language retrieval, which is out of scope.

**Kept — all 5 `hotel-crosslang-*` probes, including the 2 whose `language` field says `en`.**
These are not mirrors. They test BR-10 (`docs/design/brd-requirements-and-wireframe-prompts.md:18`
— *hiểu truy vấn trộn VI/EN*, priority 2-3): a brand name appearing in the query's non-native
language. Two run VI-sentence-with-EN-name (`hotel-crosslang-hyatt-vi`), two run
EN-sentence-with-VI-name (`hotel-crosslang-khachsan-en`: *"find me a room at Khách Sạn Mường Thanh
Luxury in Nha Trang"*). A mixed query is a Vietnamese-user scenario, so it stays in scope — and
filtering on `language == "vi"` would have silently deleted half of BR-10's only evidence as
collateral damage. **Filter on "is an EN mirror", never on the `language` field.**

Resulting run size: retrieval **44 → 30** records (28 vi + 2 EN-sentence crosslang), conversations
**10 → 9** (`conv-hcm-luxury-en` excluded).

**Non-destructive.** The excluded records stay in the `.jsonl` files; the loader filters them out.
Deleting them would discard the EN thin-reference fix that the 2026-08-11 pass spent finding 3 on
(14 records rewritten), and make re-enabling English a re-authoring job instead of a flag. VI-only
is the default; an explicit opt-in flag restores the full set.

**Consequence for BR-10 reporting:** `report.py::cross_language_pairs()` only emits a pair when a
`pair_id` has ≥2 members. With mirrors filtered out every pair drops to one member, so that
function returns empty and the report's BR-10 subsection would silently render blank — looking like
"no cross-language coverage" rather than "coverage moved". Phase 5 repoints that subsection at the
5 standalone probes.

## Execution constraint — one sample by default

**Every harness invocation in this plan runs `--limit 1` unless the user explicitly asks for a
full run.** This applies to every phase, including Phase 6's "refresh run": the machinery is built
and verified against a single sample per layer, and the full dataset pass is a separate, explicitly
requested step.

- Default for any verification step: `--limit 1`, and `--no-llm-metrics` wherever the step is
  checking wiring rather than scores.
- A phase's success criteria are met by a `--limit 1` run unless the criterion cannot be
  demonstrated on one sample (percentile spread, BR-10 probe coverage) — those criteria say so
  explicitly and wait for the user.
- Never widen the limit to "get better numbers", and never chain into a full run because a
  one-sample run looked fine. Ask.

Reason: a full pass is 30 retrieval queries plus 9 conversations of real LLM and Supabase traffic
(`eval/README.md:141-148`) — minutes of wall clock and real spend, repeated every time a bug is
found mid-build. One sample proves the wiring; only the user decides when to pay for the
distribution.

## Established facts (verified 2026-08-18, not assumed)

- **Three of Layer 2's four entry points no longer exist.** `grep` of
  `backend/src/agents/session.py` finds `create_chat_session` (line 224) and nothing else;
  `process_chat_turn`, `derive_stage`, `handle_frontend_hotel_selection`, and `TurnResult`
  are gone, replaced by the graph plane (`session.py:39-45`).
- **`finalized` is no longer an emittable stage.** `agents/graph/response_payload.py::derive_stage`
  returns only `error | intake | planned | hotel_options`. Two golden conversations
  (`conv-hcm-finalize-4d`, `conv-hue-finalize-2d`) declare `expected_stage: finalized` and are
  therefore unachievable by construction — they will report as harness failures for a reason that
  has nothing to do with agent quality.
- **The production turn driver is `routes._run_turn_via_graph`** (`backend/src/api/routes.py:748`),
  which owns the interrupt/resume branch, `extra_state` merging, and `_response_from_result`.
  Rebuilding that logic in the harness would let eval and production answer the same message
  differently.
- **Hotel selection is now `extra_state={"selected_hotel_id": ...}`** through the same driver
  (`routes.py:552-570`), not a separate `handle_frontend_hotel_selection` call.
- **Persistence is togglable at module scope** — `routes._persistence_enabled` (line 105) is read
  from `_settings.session_persistence_enabled`, so the harness can keep its runs out of the real
  session store the way `create_chat_session(session_id)` with no `persist_hook` used to.
- **The graph compiles hermetically for eval.** `_get_graph_v2()` (`routes.py:640`) falls back to
  a process-local `MemorySaver` when `registry.checkpointer` is unset.
- **`register_configure_hook` exists in the installed langchain-core 1.5.3** (verified by import
  in `eval/.venv-eval`), signature `(context_var, inheritable, handle_class=None, env_var=None)` —
  the supported way to attach a callback handler globally without editing app code.
- ~~**Streamed OpenAI calls emit no usage metadata as the app is configured.**~~
  **CORRECTED by Phase 1 measurement, 2026-08-18 — this was wrong, and no production change was
  made.** The `None` above is the *field default*; `validate_environment`
  (`langchain_openai/chat_models/base.py:1227-1246`) sets `stream_usage = True` after construction
  whenever no custom `base_url` / `OPENAI_BASE_URL` and no custom client are configured. Measured
  on both installed versions: real-OpenAI instances already have `stream_usage is True` and
  streamed calls already report usage (8 in / 10 out); OpenRouter and Cloudflare, which do set a
  `base_url`, already have it off. `qa_node.py:113` and `intake_qa.py:99` were never invisible.
  Pinned by regression tests in `backend/tests/test_llm_provider.py`; `llm.py` is untouched.
- **The trailing usage chunk is already absorbed by the streaming layer.** With
  `stream_options.include_usage` on, OpenAI sends a final chunk carrying `usage_metadata` and
  empty content. `_drive_turn` (`routes.py:698-708`) forwards chunk content to `emit_delta`, and
  `emit_delta` opens with `if not text: return` (`backend/src/api/streaming.py:189-190`) — so the
  usage chunk produces no SSE frame and no frontend change. Per the correction above this is
  describing production **as it already runs**, not a consequence of any change in this plan.
- **A `ContextVar`-based callback does not cross a raw worker thread** (measured, Phase 1).
  Capture survives `graph.invoke()` including parallel supersteps, and `asyncio.to_thread`; it is
  lost entirely — silently, as zero — through `ThreadPoolExecutor.submit` and
  `loop.run_in_executor`. `routes._drive_turn` uses the latter, so **Phase 2 must drive turns
  synchronously in the harness's own thread**.
- **A ragas `DiskCacheBackend` hit fires zero callbacks** (measured, Phase 1): cold score = 1
  event, identical repeat = 0 events, same score. Cache hits need their own counter, not a
  zero-token call record.
- **Cloudflare's embedding response carries no `usage` field at all** (measured, Phase 1):
  top-level keys are `['data', 'model', 'object']`. There is no embedding token count to report.
- **The operator's shell can silently override `backend/.env`.** `load_dotenv` does not override
  exported variables; an ambient `LLM_MODEL=gpt-4o-mini` made the first probe run score the wrong
  model with no error. Fixed in `eval/harness/__init__.py` with `override=True` (Phase 1).
- **`get_llm` is a hub: 86 impacted symbols, 59 direct callers, 27 execution flows, 6 modules —
  CRITICAL by call-graph reach.** The semantic reach of *this* change is far narrower: no
  signature, return type, or non-streaming behavior changes, and `stream_usage` is read only
  inside `_stream`/`_astream`. The two call sites that can observe it are `qa_node.py:114` and
  `intake_qa.py:99`. Phase 1 carries the mitigation.
- **Three branches of `get_llm` construct a `ChatOpenAI`-family object**: real OpenAI
  (`llm.py:160`), OpenRouter (`llm.py:214`), and Cloudflare via `_CloudflareChatOpenAI`. Each
  builds its own kwargs dict, so the change is per-branch and does not fan out implicitly.
- **The app runs reasoning models.** `backend/.env` sets `LLM_MODEL=gpt-5.1-2025-11-13` and
  `LLM_FAST_MODEL=gpt-5-mini-2025-08-07`; reasoning tokens bill as output tokens, and cached
  input bills at a different rate, so a two-field `input/output` cost model undercounts.
- **Embeddings moved to Cloudflare.** `backend/.env` sets `EMBEDDING_PROVIDER=cloudflare`,
  `EMBEDDING_MODEL=@cf/baai/bge-m3`. `eval/README.md:86-88` still tells the reader they resolve to
  local Ollama.
- **The judge is unchanged**: `gpt-4o-mini` at `temperature=0`, disk-cached
  (`eval/harness/judge.py`). A cache hit costs nothing, which the cost report must not confuse
  with a cheap model.

## Goals

| # | Goal | Priority |
|---|------|----------|
| 1 | Layer 2 runs again, driving turns through the same code path production uses | P1 |
| 2 | Every measured latency reports P50/P95/P99, not just a sum | P1 |
| 3 | Input/output tokens and cost per request are measured, app-side and judge-side separately | P1 |
| 4 | The committed report and baseline describe the current system | P1 |
| 5 | Latency and cost floors/ceilings are *proposed* with reasoning, not enforced | P2 |

## Phases

| # | Phase | Status | Depends on |
|---|-------|--------|------------|
| 1 | [Instrumentation probes](./phase-01-instrumentation-probes.md) | **Complete** (2026-08-18) | — |
| 2 | [Layer 2 graph-plane rewire](./phase-02-e2e-graph-plane-rewire.md) | **Complete** (2026-08-18) | — |
| 3 | [Latency percentiles](./phase-03-latency-percentiles.md) | **Complete** (2026-08-18) | 1 |
| 4 | [Token and cost accounting](./phase-04-token-and-cost-accounting.md) | **Complete** (2026-08-18) | 1, 3 |
| 5 | [Report and baseline schema](./phase-05-report-and-baseline-schema.md) | **Complete** (2026-08-18) | 2, 3, 4 |
| 6 | [Refresh run and publish](./phase-06-refresh-run-and-publish.md) | **Steps 1-4 complete**; full pass gated on user request | 5 |

Phases 1 and 2 are independent and may run in parallel. Phase 3 creates
`eval/harness/usage_recorder.py` as a latency-only recorder and Phase 4 extends that same module
with token, scope, and cost capture — one callback handler, two measurements, built in that order
so the cheap and reversible half lands first.

## Success Criteria

- [x] `eval/.venv-eval/bin/python eval/run_ragas.py --layer e2e --limit 1 --no-llm-metrics`
      completes without an ImportError and without writing to the real session store —
      with one measured exception: `trip_planner`'s FK pre-insert adds one **empty**
      `sessions` row per conversation, accepted by user decision (Phase 2 Results §3).
      No transcript/`chat_messages` write occurs.
- [ ] Every latency family in the report carries P50/P95/P99 plus n, alongside the existing sum.
- [ ] The report shows app-side and judge-side token totals and cost per request as separate
      figures, with the price table version and per-model rates printed.
- [ ] A model absent from the price table aborts the cost section with a named error; it never
      reports as `$0`.
- [ ] Cached judge responses are counted as cache hits, not as zero-token calls.
- [ ] `eval/results/baseline.json` carries the new latency/cost fields and the current
      `dataset_hash`. **Requires a full run — blocked until the user asks for one.**
- [ ] `eval/README.md` no longer claims Ollama embeddings or "cost is not token-metered".
- [x] Streamed OpenAI calls report non-zero output tokens in both eval and production paths, and a
      regression test pins that OpenRouter and Cloudflare stay off (`test_llm_provider.py`).
      Achieved without editing `llm.py` — see Phase 1 Results §2.
- [x] No caveat in the published report describes an eval-vs-production configuration difference
      in streaming — because there never was one.
- [ ] Proposed latency/cost bounds appear in the report labelled as proposals, and no run fails
      because of them.
- [x] A default run scores 30 retrieval records and 9 conversations; the 14 EN mirrors and
      `conv-hcm-luxury-en` are excluded, and all 5 `hotel-crosslang-*` probes still run.
- [ ] The report's BR-10 subsection shows the 5 standalone crosslang probes, not a blank section.
- [x] The excluded records are still present in the `.jsonl` files, and one flag restores them
      (`--include-en-mirrors`), pinned by `backend/tests/test_golden_dataset_filter.py`.

## Non-goals

- Enforcing latency or cost in CI (explicitly deferred — see Decisions).
- Changing retrieval or agent behavior to improve any number this plan measures.
- Adding token accounting, cost computation, or usage persistence to the backend runtime. **As of
  Phase 1 this plan changes no production file at all** — the one planned exception proved
  unnecessary. The app does not gain a recorder, a price table, or a metrics sink from this plan.
  Consuming the `usage_metadata` that streamed calls already return is a separate piece of work.
- Rewriting the golden datasets beyond the stage re-adjudication Phase 2 forces.

## Open questions

~~1. Are `conv-hcm-finalize-4d` / `conv-hue-finalize-2d` re-pointed at `planned`, or does the graph
   plane need to emit a `finalized` stage again?~~ **Resolved 2026-08-18: both re-pointed at
   `planned`**, with the adjudication in `eval/datasets/README.md`. The stage is gone by design
   (`respond.py` documents the removal; `ChatStage` no longer contains it), so the records were
   unachievable by construction. **The replay also surfaced two real defects, filed not fixed:**
   `"Chốt lịch trình"` fails in `itinerary_node` (`lock_days received an empty days_to_lock`) and
   leaves the itinerary `Draft` while the stage check still passes; and `"trong 1 ngày"` is
   rejected at intake (`end date must be after the trip's start date`), because `"trong N ngày"`
   resolves to an end date `N-1` days out. See Phase 2 Results §4.
~~2. Should Cloudflare embedding calls carry a price?~~ **Resolved 2026-08-18: token-counted but
   unpriced.** Cloudflare Workers AI bills per neuron, not per token, so a token-derived dollar
   figure would be category-wrong — a number that looks authoritative and measures nothing. Token
   counts are still real and still worth reporting: they show embedding volume and how it scales
   with the dataset. Phase 4 reports embedding tokens under their own heading with cost marked
   `UNPRICED (neuron-billed)`, and this never trips the unpriced-model hard failure, which applies
   to chat models only.
   **Amended 2026-08-18 after Phase 1 measured it: there is no token count to report.** The
   Cloudflare response omits `usage` entirely (keys: `data`, `model`, `object`). Phase 4 reports
   embedding **calls** under that heading, still marked `UNPRICED (neuron-billed)`. Deriving a
   token estimate locally would invent the number this resolution was written to avoid.
