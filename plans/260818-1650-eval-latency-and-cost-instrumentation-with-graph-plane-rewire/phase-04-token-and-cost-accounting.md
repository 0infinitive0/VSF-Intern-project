---
phase: 4
title: "Token and cost accounting"
status: complete
priority: P1
effort: "1d"
dependencies: [1, 3]
---

# Phase 4: Token and cost accounting

## Overview

Turn Phase 1's proven capture mechanism into measured input/output tokens and a cost per request,
reported app-side and judge-side separately. This replaces `eval/README.md:141-148`'s standing
admission that cost is wall-clock and call-count only.

## Requirements

- Functional: per-call records of `(model, input_tokens, output_tokens, reasoning_tokens,
  cached_input_tokens, cache_hit, latency_s)` for every LLM call made during a run.
- Functional: totals and per-request costs reported under two separate headings — app-side
  (`gpt-5.1` / `gpt-5-mini`, the product's own spend) and judge-side (`gpt-4o-mini` plus
  embeddings, the eval's own spend). Never a single merged figure.
- Functional: "per request" is defined per layer and stated in the report — one retrieval query for
  Layer 1, one user turn for Layer 2, plus a per-conversation figure.
- Functional: a model with no entry in the price table aborts the cost section with a named error.
- Non-functional: prices live in a versioned, committed data file with a `source` and `as_of` date,
  not scattered constants.
- Non-functional: token counts are reported even when a price is unavailable — an unpriced model
  still has a measurable token footprint.
- Non-functional: no `backend/src/` file is modified *by this phase*. The plan's single production
  change (`stream_usage=True`) lands in Phase 1 and is already in place here.

## Architecture

**`eval/harness/usage_recorder.py`** — extended, not created here. Phase 3 built it as a
latency-only `BaseCallbackHandler` on a `ContextVar` with a `record_usage()` context manager. This
phase adds three things to that same handler: token capture, a `scope` tag, and the
`get_llm`-wrapping fallback if it is needed.

Token capture per call: the normalized `usage_metadata` with `input_token_details` and
`output_token_details` preserved whole, not flattened — the sub-fields are where reasoning and
cache-read live. Model name and cache-hit status are already recorded by Phase 3.

**Attribution: app-side vs judge-side.** The recorder tags each call with a scope. The reliable
discriminator is *when* the call happened, not which model ran it — the app and the judge could in
principle share a model, and inferring scope from the model name would then silently misattribute.
So scope is set by the enclosing context: `record_usage(scope="app")` wraps the retrieval call or
the agent turn; `record_usage(scope="judge")` wraps the ragas scoring call. `retrieval_eval.py`
and `e2e_eval.py` already separate those two regions cleanly (`_run_one` vs `score_llm`;
`_replay_conversation` vs `_score_conversation`), so the wrapping is mechanical.

**`eval/pricing/model-prices.json`** — a committed table:

```jsonc
{
  "version": 1,
  "as_of": "2026-08-18",
  "source": "<the live pricing page URL the numbers were read from>",
  "currency": "USD",
  "unit": "per_1m_tokens",
  "models": {
    "gpt-5.1-2025-11-13":    { "input": null, "cached_input": null, "output": null },
    "gpt-5-mini-2025-08-07": { "input": null, "cached_input": null, "output": null },
    "gpt-4o-mini":           { "input": null, "cached_input": null, "output": null }
  },
  "embeddings": {
    "@cf/baai/bge-m3": {
      "unpriced_by_design": true,
      "note": "Cloudflare Workers AI bills per neuron, not per token. Tokens are counted and reported; no dollar figure is derived. Excluded from rolled-up totals; never raises UnpricedModelError."
    }
  }
}
```

The `null`s are deliberate and are filled at implementation time by reading the current published
rates. **Do not carry rates over from memory or from another repo** — model prices change, and a
stale rate produces a confidently wrong cost figure, which is worse than no figure. A `null` rate
for a model that was actually called is the error condition described below.

Model-name matching is exact against the string the callback reports. A dated snapshot id
(`gpt-5.1-2025-11-13`) and its alias (`gpt-5.1`) are different keys; support an explicit `aliases`
map rather than prefix-matching, because prefix-matching `gpt-5` would happily price `gpt-5-mini`
at `gpt-5` rates.

**Fail loud on an unpriced model.** If a call's model has no rate, the cost section raises with the
model name and the call count, and the report emits token totals with cost marked
`UNPRICED: <model>`. It must never fall through to `0.0` — a `$0` line in a cost report reads as
"free", and that is the one wrong answer this whole phase exists to prevent.

**Cache hits.** A `DiskCacheBackend` hit means the tokens were paid for on an earlier run. Counting
it as zero understates the true cost of the eval; counting it as a full charge overstates the
cost of *this* run. Report both: `cost_this_run` (cache hits excluded) and
`cost_cold_cache` (every call priced as if it had missed), with the cache-hit count next to them.
Two honest numbers beat one ambiguous one.

**Reasoning tokens.** Per Phase 1 step 2's finding. If `output_token_details.reasoning` is
populated, report it as its own line under output tokens (it is billed at the output rate, so total
cost is unaffected — but a turn that spends 80% of its output budget on reasoning is a fact worth
seeing). If it is absent, say so in Caveats rather than reporting zero.

**Embeddings — token-counted, never priced** (user decision, 2026-08-18). Cloudflare Workers AI
bills per neuron, not per token, so multiplying embedding tokens by a token rate would produce a
figure that looks authoritative and measures nothing. Token counts are still real and still worth
having: they show embedding volume and how it scales as the golden set grows.

So embeddings get their own heading reporting `calls`, `input_tokens`, and cost literally rendered
as `UNPRICED (neuron-billed)` — not `0.0`, not omitted. They are excluded from every rolled-up
dollar total, and an embedding model must never trip the `UnpricedModelError` hard failure; that
guard exists for chat models, where a missing rate means a real cost is going unreported. Encode
this as a distinct `unpriced_by_design` flag on the price-file entry, so "we chose not to price
this" is machine-distinguishable from "someone forgot to fill in a rate".

Per Phase 1 step 7: if the embedding path emits no LLM callback, token counts come from wrapping
`get_embeddings()`'s returned object. If neither the callback nor the wrapper yields a token count,
report `calls` alone and say tokens were unavailable — an estimate from character counts would be a
fabrication.

## Related Code Files

- Modify: `eval/harness/usage_recorder.py` — add tokens and `scope` to Phase 3's recorder
- Create: `eval/pricing/model-prices.json`
- Create: `eval/harness/cost.py` — price lookup, cost computation, the unpriced-model error
- Modify: `eval/harness/retrieval_eval.py` — wrap `_run_one` (`scope="app"`) and `score_llm`
  (`scope="judge"`)
- Modify: `eval/harness/e2e_eval.py` — wrap `_replay_conversation` and `_score_conversation`
- Modify: `eval/run_ragas.py` — emit a top-level `usage` key
- Delete: `eval/harness/usage_probe.py` — Phase 1 scaffolding, superseded
- Read: `backend/src/services/llm.py`, `eval/harness/judge.py`

## Implementation Steps

1. Extend Phase 3's `usage_recorder.py`: capture `usage_metadata` per call and add the `scope`
   argument to `record_usage()`.
2. Assert at run start that a streaming call yields usage. Phase 1 set `stream_usage=True` in
   `llm.py` so this should already hold — but a regression here silently zeroes the cost of every
   `qa_node` / `intake_qa` turn, and a silent zero is indistinguishable from a cheap turn. Check
   it, do not trust it.
3. Write `model-prices.json` with real rates read from the current published pricing page, and put
   that URL in `source`.
4. Write `cost.py`: `price_calls(calls, table) -> dict` returning per-model and per-scope
   `{calls, cached_calls, input_tokens, cached_input_tokens, output_tokens, reasoning_tokens,
   cost_this_run, cost_cold_cache}`, raising `UnpricedModelError` naming the model when a rate is
   missing.
5. Wrap the four regions in `retrieval_eval.py` / `e2e_eval.py` with the correct scope.
6. Define and compute per-request cost: Layer 1 `cost / n_queries`; Layer 2 `cost / n_turns` and
   `cost / n_conversations`. Emit the divisor alongside each figure so the denominator is never
   ambiguous.
7. Emit a `usage` key in the raw run JSON holding the full per-call list plus the aggregates. The
   per-call list is what makes a cost figure auditable, the same way per-record `latency_s` makes a
   percentile auditable.
8. Add a redaction check: the per-call records must never carry prompt or response text. Extend
   `report.py::_SECRET_PATTERNS` coverage by asserting the `usage` block contains only numbers,
   model names, and timestamps.

## Success Criteria

- [x] A `--layer retrieval --limit 1` run reports non-zero input and output tokens for the app
      scope and for the judge scope, separately.
- [x] An e2e turn that hits a streaming node reports non-zero output tokens.
- [x] Removing a model from `model-prices.json` makes the run fail with that model's name in the
      message — verified deliberately, not assumed.
- [x] `cost_this_run` and `cost_cold_cache` differ on a warm-cache run and match on a cold one.
- [x] The raw JSON's `usage` block contains no prompt or response text.
- [x] Per-request cost figures print their divisor.
- [x] `eval/pricing/model-prices.json` has a real `source` URL and `as_of` date, no `null` rates
      for any chat model the run actually called.
- [x] Embedding tokens are reported with cost shown as `UNPRICED (neuron-billed)`, excluded from
      every dollar total, and do not raise `UnpricedModelError`.

## Risk Assessment

| Risk | Mitigation |
|---|---|
| Prices are transcribed wrong or go stale, and every downstream cost figure is confidently wrong | `as_of` + `source` are printed in the report's run metadata, so a reader can date-check the rates. Token counts are reported independently of price, so a bad rate never corrupts the token measurement |
| `ContextVar`-based scoping mis-attributes a call made on a worker thread inside the graph | Phase 1's probe and Phase 3's call-count cross-check settle whether propagation holds before any cost code depends on it. If it does not, scope falls back to an explicit wrapper on `get_llm` (mechanism B) for app calls and `judge.py` for judge calls — two narrow seams instead of one broad one |
| Reasoning-token cost for `gpt-5.1` is undercounted because the field is absent | Reasoning tokens bill at the output rate and are included in `output_tokens` regardless, so total cost stays correct; only the reasoning *breakdown* is lost. Stated in Caveats |
| Cached-input pricing is ignored, overstating input cost | `input_token_details.cache_read` is priced at the `cached_input` rate when both the field and the rate are present; when either is missing, all input is priced at the full rate and the report says so — an overstatement that is disclosed, not a silent one |
| Cloudflare embeddings are billed per neuron, not per token, so a token-based cost is category-wrong | Tokens counted and reported; cost rendered as `UNPRICED (neuron-billed)` and excluded from every dollar total, with the note carried from the price file. `unpriced_by_design: true` keeps this distinguishable from a forgotten rate |
| A future reader sees `UNPRICED` and "fixes" it by inventing a per-token rate | The price-file note states the billing model, and the flag name says the omission is deliberate. Pricing it correctly means adding neuron accounting, not a token rate |
| Adding a global callback changes app behavior under eval | Callbacks observe; they do not alter generation. There is no remaining eval-vs-production configuration difference — `stream_options.include_usage` is now on in production too (Phase 1), which is the point of having fixed it there rather than in the harness |

## Results (measured 2026-08-18)

Extended `usage_recorder.py` with token capture and scope; added `eval/harness/cost.py` and
`eval/pricing/model-prices.json`. `eval/harness/usage_probe.py` deleted — superseded.

### Rates, read live

Fetched from `https://developers.openai.com/api/docs/pricing` on 2026-08-18 (recorded as
`source` + `as_of`), not recalled from memory:

| model | input | cached input | output |
|---|---|---|---|
| gpt-5.1 | 1.25 | 0.125 | 10.00 |
| gpt-5-mini | 0.25 | 0.025 | 2.00 |
| gpt-4o-mini | 0.15 | 0.075 | 0.60 |

Matching is exact against the dated snapshot id the callback reports, via an explicit `aliases`
map — prefix-matching `gpt-5` would price `gpt-5-mini` at gpt-5 rates, a 5x error.

### Measured, app-side and judge-side separately

One `conv-nhatrang-couple-3d` replay with scoring:

| scope | model | calls | input | cached in | output | reasoning | cost |
|---|---|---|---|---|---|---|---|
| app | gpt-5.1-2025-11-13 | 4 | 4307 | 2048 | 538 | 200 | $0.008460 |
| app | gpt-5-mini-2025-08-07 | 1 | 256 | 0 | 113 | 64 | $0.000290 |
| judge | gpt-4o-mini-2024-07-18 | 3 | 1887 | 0 | 166 | 0 | $0.000382 |

App-side $0.002917/turn (n=3), $0.008750/conversation (n=1). Judge-side $0.000127/turn. Never
summed. Retrieval layer separately: 2 app calls, 510 in / 286 out, $0.0007/query.

**This corrects Phase 1 Results §5.** `output_token_details.reasoning` and
`input_token_details.cache_read` are not merely present-but-zero: real work produced **264
reasoning tokens** and **2048 cached input tokens**. The probe's zeros were an artefact of
two-word prompts. Cached input is priced at its own lower rate, with the cached portion
subtracted from the full-rate input rather than billed twice (pinned by test).

### Deviation: `cost_cold_cache` is an extrapolation, and says so

The plan specified "every call priced as if it had missed". That assumed cache hits are visible
calls; Phase 1 measured that they fire no callback, so a hit's tokens were **never observed** and
cannot be priced directly. `project_cold_cache_cost` therefore applies the mean cost of the
observed calls to the hit count and returns `estimated: true` with its method string. With a cold
cache there are no hits, the projection equals the measured cost, and it returns
`estimated: false` — so the criterion "match on a cold run" holds exactly (verified: cold run,
both $0.000382). On a fully-warm run where *every* operation hit, it returns `None` rather than
extrapolating from nothing (observed on the retrieval layer: 2 operations, 0 calls).

### Guards, verified deliberately rather than assumed

- Deleting `gpt-5.1` from the price table raises `UnpricedModelError: ... gpt-5.1-2025-11-13
  (1 call(s))`. Never `$0`.
- `@cf/baai/bge-m3` returns `cost_usd: None`, `unpriced_by_design: true`, and raises nothing.
- The committed per-call list carries only `scope`, `model`, `latency_s`, `usage_metadata`,
  `error` — `contains_only_safe_fields` fails the run if any other key appears, so prompt or
  response text cannot reach a committed file. Checked against the real run: clean.
- `assert_streaming_usage_enabled()` runs before the first query. It is a config check, not a
  live call: langchain enables streamed usage only when no custom `base_url` is set, so an
  `LLM_API_BASE` pointing at a proxy would silently cost every `qa_node`/`intake_qa` turn at
  zero. The backend's unit test pins the library default; this catches the environment, which
  that test cannot see.

10 tests in `backend/tests/test_eval_cost.py`.
