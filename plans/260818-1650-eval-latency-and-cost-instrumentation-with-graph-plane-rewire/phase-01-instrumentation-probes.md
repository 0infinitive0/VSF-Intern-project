---
phase: 1
title: "Instrumentation probes"
status: complete
priority: P1
effort: "0.5d"
dependencies: []
---

# Phase 1: Instrumentation probes

## Overview

Prove — against the real installed stack, with real calls — that token usage can actually be
captured from every LLM path the harness will measure, before any aggregation, pricing, or
reporting code is written on top of that assumption. This mirrors what `smoke_check.py` does for
the judge: nothing downstream is trustworthy until the wiring is shown to work.

## Requirements

- Functional: a throwaway probe script demonstrates captured `input_tokens` / `output_tokens` for
  (a) a non-streaming OpenAI call, (b) a streaming OpenAI call, (c) a ragas judge call, and
  (d) a Cloudflare embedding call — or records, with evidence, that a given path cannot be
  captured.
- Functional: the probe reports whether `output_token_details.reasoning` and
  `input_token_details.cache_read` are populated for `gpt-5.1` / `gpt-5-mini`.
- Non-functional: total probe spend is a handful of calls, not a dataset pass. Use the smallest
  prompts that still exercise the path.
- Non-functional: the probe lives under `eval/harness/` and is scaffolding, not a deliverable.
  Phase 3 turns its mechanism into the durable `usage_recorder.py`; Phase 4 deletes the probe once
  the recorder also covers the cost paths this phase exercises.

## Architecture

Two capture mechanisms are candidates, and the probe decides between them on evidence:

**A. Global callback via `register_configure_hook`.** langchain-core 1.5.3 exposes
`register_configure_hook(context_var, inheritable, handle_class=None, env_var=None)` — the same
mechanism `get_openai_callback` uses. A `BaseCallbackHandler` bound to a `ContextVar` is picked up
by every LLM call made inside the context, including calls made deep inside LangGraph nodes the
harness never touches directly. This is the preferred mechanism: no monkeypatch, no per-call-site
plumbing, and it composes with the existing `record_contexts()` context manager.

The handler reads usage in `on_llm_end(response: LLMResult)`:
- primary source: `response.generations[0][0].message.usage_metadata` — the normalized
  `{input_tokens, output_tokens, total_tokens, input_token_details, output_token_details}` shape;
- fallback: `response.llm_output["token_usage"]`, for providers that don't populate the former.

It must also record the model name per call (from `response.llm_output["model_name"]` or the
serialized run) — cost cannot be computed without knowing which price applies, and the app uses
at least two different models in one turn.

**B. Wrapping `src.services.llm.get_llm`**, the `context_recorder.py` precedent. Falls back to
this only if A misses calls. Every app call site funnels through `get_llm` /
`get_fast_llm` / `get_reasoning_llm` (`backend/src/services/llm.py:75,282,315`), so a wrapper
that attaches a per-instance callback reaches all of them — but it does *not* reach the ragas
judge, which builds its LLM through `harness/judge.py`, so judge-side capture would need its own
path.

**The streaming fix — a production change, deliberately.** Independent of A vs B: `qa_node.py:114`
and `intake_qa.py:99` build their LLM with `streaming=True` and no `stream_usage`, which
`_should_stream_usage` resolves to `False` — those calls report zero tokens.

Fix it in `backend/src/services/llm.py` by setting `stream_usage=True` on the **real-OpenAI branch
only** (`llm.py:160`), rather than overriding it harness-side. A harness override would make the
eval measure a configuration production never runs, and every cost number this plan produces would
carry that asterisk permanently. Setting it in the app makes the two identical and gives production
its own token visibility for free.

Scope it to the real-OpenAI branch and leave OpenRouter (`llm.py:214`) and Cloudflare
(`_CloudflareChatOpenAI`) alone. All three build a `ChatOpenAI`-family object, but only real OpenAI
is verified to accept `stream_options.include_usage` — and `_CloudflareChatOpenAI` exists precisely
because that endpoint's schema diverges from OpenAI's (it rejects `content: null`). Assuming it
tolerates another OpenAI-specific option is the exact class of guess that class was written to
correct. Widening later is one line per branch, once someone measures those providers.

`stream_usage` is safe to set unconditionally on that branch: it is read only inside
`_stream`/`_astream`, so a non-streaming `invoke()` caller is unaffected. No separate
streaming/non-streaming code path is needed.

**Blast radius, stated plainly.** `impact(get_llm, upstream)` reports **CRITICAL** — 86 impacted
symbols, 59 direct callers, 27 execution flows, 6 modules. That figure measures the call graph, not
this change: the signature, return type, and non-streaming behavior are all unchanged, so 57 of
those 59 callers cannot observe it. The two that can are `qa_node.py:114` and `intake_qa.py:99`.
The trailing usage chunk they receive carries empty content, and `emit_delta`'s opening
`if not text: return` (`backend/src/api/streaming.py:189-190`) drops it before any SSE frame is
built — verified by reading the guard. Step 4a re-verifies it at runtime rather than resting on
that read.

## Related Code Files

- Create: `eval/harness/usage_probe.py` — throwaway; asserts and prints, does not export
- **Modify: `backend/src/services/llm.py`** — `stream_usage=True` on the real-OpenAI branch
  (`llm.py:160`). The only production file this plan touches
- Create/modify: a backend test asserting the default holds (see step 4b)
- Read: `backend/src/api/streaming.py:177-196` — `emit_delta`'s empty-text guard
- Read: `backend/src/agents/graph/nodes/qa_node.py:114`,
  `backend/src/agents/graph/nodes/intake_qa.py:99` — the two `streaming=True` sites
- Read: `eval/harness/judge.py`, `eval/harness/context_recorder.py` — the patterns to match

## Implementation Steps

1. Write `usage_probe.py` with a `UsageProbe(BaseCallbackHandler)` that appends
   `(model, usage_metadata, llm_output)` on every `on_llm_end`, registered through
   `register_configure_hook` against a module `ContextVar`.
2. Probe non-streaming: `get_fast_llm(temperature=0.0).invoke("say ok")`. Assert the probe
   captured exactly one call with non-zero `input_tokens` and `output_tokens`, and print the full
   `usage_metadata` including `input_token_details` / `output_token_details` so the reasoning and
   cache-read sub-fields are recorded as fact, not assumed.
3. Probe streaming **before** the change: `get_fast_llm(streaming=True, temperature=0.0)`, drain
   `.stream("say ok")`. Record whether usage arrived. Expected: it does not. Capture this baseline
   first — it is the evidence the change is necessary, and it is unrecoverable afterwards.
4. Make the production change: add `kwargs["stream_usage"] = True` to the real-OpenAI branch of
   `get_llm` (`llm.py:160`), with a comment naming `_should_stream_usage` and why the `None`
   default is not what a reader would expect. Re-run step 3 and confirm usage now arrives.
   4a. Verify the trailing chunk is inert end to end: drive one streamed turn through the graph
       (`qa_node` or `intake_qa`) and confirm the SSE frame count and content are unchanged versus
       before the edit. `emit_delta`'s guard should make this a no-op — confirm it, since this is
       the one user-visible surface the change could touch.
   4b. Add a backend regression test asserting a `get_llm(provider="openai", ...)` instance has
       `stream_usage is True`, and that OpenRouter and Cloudflare instances do not. The second half
       matters more than the first: it pins the deliberate scoping so a later "consistency" cleanup
       cannot silently widen it to endpoints that were never verified.
   4c. Run the existing backend streaming tests (`backend/tests/test_stream_modes.py` and any
       `qa_node` / `intake_qa` coverage) and confirm green.
5. Probe the judge: run one `Faithfulness` scoring call from `smoke_check.py`'s sample set through
   `build_judge()` inside the probe context. Confirm judge calls are captured too — they go through
   `LangchainLLMWrapper`, an extra layer between the metric and the model.
6. Probe a cache hit: repeat step 5 unchanged. Record how many `on_llm_end` events fire when
   `DiskCacheBackend` serves the response. This determines whether Phase 4 counts cache hits as
   zero-token calls (wrong — they were paid for once) or as a separate `cached_calls` counter.
7. Probe embeddings: call `get_embeddings().embed_query("test")` inside the probe context. Record
   whether `on_llm_end` fires at all for the Cloudflare embedding path — embeddings often do not
   emit LLM callbacks. The decision is fixed (token-counted, never priced), so what this probe
   settles is only *where the token count comes from*: the callback, a wrapper around
   `get_embeddings()`'s return value, or nowhere. Record which, and whether the Cloudflare response
   carries a token count at all — if it does not, Phase 4 reports calls only rather than estimating.
8. Write the findings into this file's own results section (or a short note in
   `plans/reports/`), because Phases 3-5 are written against them.

## Success Criteria

- [x] Every one of the four paths is recorded as CAPTURED or NOT-CAPTURED with the evidence that
      settled it — no path is left as "presumably works".
- [x] ~~The streaming gap is demonstrated *before* the fix and closed *after* it, both measured.~~
      **Void: there is no gap.** Measured before any edit — streamed calls already report usage.
      See Results §2.
- [x] ~~`stream_usage=True` is set on the real-OpenAI branch only~~ — already true without an edit;
      **OpenRouter and Cloudflare are unchanged, and a test pins that** (`test_llm_provider.py`).
- [x] ~~A streamed turn's SSE frames are byte-identical before and after the change.~~ Void — no
      change was made, so there is no before/after. The trailing usage chunk this criterion
      guarded against already flows in production today and is already absorbed by `emit_delta`.
- [x] Existing backend streaming tests pass (60 passed).
- [x] Cache-hit behavior under `DiskCacheBackend` is known: number of callback events per cached
      score.
- [x] Whether `reasoning` and `cache_read` token details are populated for the app's models is
      recorded as observed fact.
- [x] Total probe spend stays under a dollar's worth of calls (~15 calls, all under 500 tokens).

## Results (measured 2026-08-18)

Probe: `eval/harness/usage_probe.py`, stages `nonstream | stream | judge | embeddings | threads |
graph`. Run from `backend/` so `Settings(env_file=".env")` resolves `backend/.env`.

### 1. Capture mechanism: A confirmed, with a hard boundary

`register_configure_hook` + `ContextVar` captures every path tested — **including through
LangGraph's parallel supersteps** (3 nodes across 2 parallel branches → 3 `on_llm_end` events).
Mechanism B is not needed.

**The boundary that matters for Phases 2-3** — a `ContextVar` is per-thread:

| Call site | Captured |
|---|---|
| Same thread | ✅ 1 event |
| `graph.invoke()`, incl. parallel branches | ✅ 3/3 events |
| `asyncio.to_thread` | ✅ 1 event (copies context) |
| `ThreadPoolExecutor.submit` | ❌ **0 events** |
| `loop.run_in_executor` | ❌ **0 events** |

`routes._drive_turn` runs turns through `run_in_executor` (`streaming.py:160` documents the
non-propagation directly). **Phase 2 must drive turns synchronously in the harness's own thread**,
or Phase 3's recorder must attach the handler per-invocation via `config={"callbacks": [...]}`
instead of relying on the ContextVar. This is a constraint, not a preference — the failure mode is
silent zero, not an error.

### 2. The `stream_usage` premise was wrong — no production change was made

The plan's established fact read `ChatOpenAI.model_fields['stream_usage'].default` (`None`). The
field is set **after** construction: `validate_environment`
(`langchain_openai/chat_models/base.py:1227-1246`) sets `self.stream_usage = True` when
`stream_usage`, `openai_proxy` and every client field are unset *and* no custom `base_url` /
`OPENAI_BASE_URL` is configured.

Measured, on both installed versions (backend 1.4.1, eval 1.4.2):

- real-OpenAI instance → `stream_usage is True`; streamed `get_fast_llm(streaming=True)` reported
  8 in / 10 out over 5 chunks (4 empty-content);
- OpenRouter and Cloudflare instances (custom `base_url`) → `stream_usage is None`.

The scoping the phase wanted already holds, by the library's own heuristic. `qa_node` and
`intake_qa` are **not** invisible today, and the trailing empty usage chunk already flows in
production. **User decision 2026-08-18: skip the edit, pin the behavior with a test.**
`backend/src/services/llm.py` is unchanged; this plan now touches **no production file**.

Regression test added to `backend/tests/test_llm_provider.py`:
`test_openai_instance_reports_streamed_token_usage` (real OpenAI → `True`) and
`test_custom_base_url_providers_do_not_request_streamed_usage` (OpenRouter, Cloudflare → not
`True`). `OPENAI_BASE_URL` was added to the file's env-clearing fixture, or an ambient proxy URL
would flip the first assertion. The second test is the one that earns its keep: it fails a future
"consistency" cleanup that sets `stream_usage` unconditionally in `get_llm`.

### 3. Per-path capture results

| Path | Result | Evidence |
|---|---|---|
| Non-streaming OpenAI | **CAPTURED** | gpt-5-mini: 8 in / 10 out; gpt-5.1: 8 in / 10 out |
| Streaming OpenAI | **CAPTURED** | 8 in / 10 out, no code change needed |
| ragas judge (`LangchainLLMWrapper`) | **CAPTURED** | gpt-4o-mini, 368 in / 19 out, 1 event per score |
| Cloudflare embeddings | **NOT CAPTURED** | 0 `on_llm_end` events, and no token count exists on the wire |

### 4. Judge cache: a hit is invisible, not zero

Cold score → 1 event (368/19, 2.03s). Identical repeat → **0 events**, 0.01s, same score.

A `DiskCacheBackend` hit produces no callback at all. **Phase 4 must count cache hits with a
separate `cached_calls` counter** — treating them as zero-token calls would drag the mean
tokens-per-judge-call toward zero and misreport the eval's real cost.

### 5. Token detail sub-fields

Both `input_token_details.cache_read` and `output_token_details.reasoning` are **present and
populated** on every OpenAI call, for both gpt-5.1 and gpt-5-mini.

Both read `0` in every probe, including a deliberately reasoning-heavy prompt to gpt-5.1 — the app
pins `reasoning_effort="low"` (`llm.py:136`), and these prompts were short. The fields are real;
they were simply not exercised.

**Confirmed non-zero in Phase 4 on real work** (a single `conv-nhatrang-couple-3d` replay):
gpt-5.1 reported **2048 cached input tokens** and **200 reasoning tokens**, gpt-5-mini **64
reasoning tokens**. Both sub-fields carry real values under load; the probe's zeros were an
artefact of two-word prompts, not an absent field.

**No reasoning-token blind spot for Phase 4.** OpenAI counts reasoning tokens inside
`completion_tokens`, which is what `output_tokens` carries — pricing total output tokens at the
output rate is correct and complete. (Documented behavior, corroborated by the field being a
*sub*-total of `output_tokens`; not independently measured here, since every observed value was 0.)

### 6. Cloudflare embeddings carry no token count at all

The raw response for `@cf/baai/bge-m3` has top-level keys `['data', 'model', 'object']` — `usage`
is absent, and per-item keys are `['embedding', 'index', 'object']`.

**Phase 4 reports embedding calls only.** Not tokens, not an estimate, not a price. The plan's
"token-counted but unpriced" decision has to weaken by one notch: there is no token count to
report. Counting calls (and, if useful, characters submitted) is the honest measurement available.

### 7. Environment leak — fixed in the harness

The operator's shell exported `LLM_MODEL=gpt-4o-mini`, `EMBEDDING_PROVIDER=ollama`,
`EMBEDDING_MODEL=bge-m3`. `load_dotenv` never overrides an already-exported variable, so
`backend/.env` lost, and the first probe run **silently scored gpt-4o-mini in place of gpt-5.1**
with no error and no visible difference in its output. A published cost number produced that way
would have been wrong and unfalsifiable.

Fixed at the source (user decision 2026-08-18): `eval/harness/__init__.py` now calls
`load_dotenv(_BACKEND_DIR / ".env", override=True)`. Verified — with the ambient vars still
exported, the harness now resolves gpt-5.1, gpt-5-mini and Cloudflare embeddings.

### 8. Follow-ups for later phases

- **Phase 2:** drive turns synchronously; do not reuse `run_in_executor` (§1).
- **Phase 3:** if any driver must cross a raw thread, attach callbacks per-invocation rather than
  via the ContextVar (§1).
- **Phase 4:** separate `cached_calls` counter (§4); embeddings report calls, not tokens (§6).
- **Phase 6:** `eval/README.md` still claims Ollama embeddings — §7 shows the config now resolves
  to Cloudflare, so that correction is load-bearing rather than cosmetic.
- **Unrelated, pre-existing:** `resend>=2.0.0` is declared in `backend/requirements.txt` but was
  missing from the local env, which broke `tests/conftest.py` collection for the whole backend
  suite. Installed to run the tests.

## Risk Assessment

| Risk | Mitigation |
|---|---|
| `register_configure_hook` misses calls made in a LangGraph node running on another thread or in a `ThreadPoolExecutor` — `ContextVar` propagation is not automatic across raw threads | Step 5's judge probe and Phase 2's first real e2e turn cross-check the captured call count against an independent count (e.g. wrapping `get_llm`). A mismatch means fall back to mechanism B |
| `get_llm` is a CRITICAL-risk hub (86 symbols, 59 direct callers, 27 flows) | The change touches no signature, return type, or non-streaming path; `stream_usage` is read only in `_stream`/`_astream`. Only the 2 `streaming=True` call sites can observe it. Steps 4a-4c verify the streamed surface specifically rather than trusting the reasoning |
| The trailing usage chunk reaches the frontend as a stray empty delta | `emit_delta` returns early on falsy text (`streaming.py:189-190`), verified by reading it; step 4a confirms at runtime with a frame-level comparison |
| Cloudflare or OpenRouter rejects `stream_options.include_usage` | The change is scoped to the real-OpenAI branch and a test pins that scoping. `_CloudflareChatOpenAI` already documents that endpoint diverging from OpenAI's schema — that is the precedent for not assuming compatibility |
| A later refactor "unifies" the three branches and silently widens the option | Step 4b's test asserts OpenRouter and Cloudflare instances do **not** carry `stream_usage`, so the widening fails a test instead of failing in production |
| The probe leaves a registered global hook behind and pollutes later calls in the same process | Register once at module import against a `ContextVar` that defaults to `None`; capture is opt-in per `with` block, exactly like `record_contexts()` |
| Reasoning-token fields are absent, making `gpt-5.1` output cost undercount | Step 2 measures it directly. If absent, Phase 4 prices total output tokens at the output rate and states the reasoning-token blind spot in Caveats rather than silently assuming zero |
