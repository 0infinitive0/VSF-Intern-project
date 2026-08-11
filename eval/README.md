# RAGAS RAG evaluation harness

Measures retrieval quality (Layer 1) and end-to-end answer grounding (Layer 2) of the
trip-planner RAG pipeline with [RAGAS](https://docs.ragas.io/). See
`plans/260807-1400-ragas-rag-evaluation-harness/plan.md` for the full design.

## Why an isolated venv

`ragas` pulls in `datasets`, `pandas`, `pyarrow`, and `langchain-community` — none of which
the backend runtime needs. This harness runs in its own virtualenv
(`eval/.venv-eval`) with the backend's own `src/` added to `sys.path` at import time, so it can
call `src.services.supabase_search` and `src.agents.session` directly (in-process, not over
HTTP) without adding a single package to `backend/requirements.txt`.

There is also a pre-existing, broken global `ragas 0.1.22` install elsewhere on this machine
(`ModuleNotFoundError: No module named 'langchain_core.pydantic_v1'` — removed in
langchain-core 1.x). Always invoke the harness through `eval/.venv-eval/bin/python` explicitly;
never rely on whatever `python`/`ragas` resolves on `$PATH`.

## Setup

```bash
python3 -m venv eval/.venv-eval
eval/.venv-eval/bin/pip install -r eval/requirements-eval.txt
```

Confirm the isolation actually holds (should print `0.3.9` then a `1.5.x`, never `0.1.22`):

```bash
eval/.venv-eval/bin/python -c "import ragas, langchain_core; print(ragas.__version__, langchain_core.__version__)"
```

### A pin worth knowing about

`ragas==0.3.9`'s `ragas/llms/base.py` unconditionally imports
`langchain_community.chat_models.vertexai`, a module `langchain-community` deleted in `0.4.2`
(still present in `0.4.1`). `requirements-eval.txt` pins `langchain-community<0.4.2` to work
around this — `pip install`'s dependency *resolution* succeeding is not the same as the package
actually being importable; this only surfaces by running the smoke check below.

### Deviations from the plan's sketch, and why

The plan document is a design sketch, verified against the real `ragas==0.3.9` API at
implementation time (as its own Phase 1 instructs). Three corrections worth knowing if you're
reading the plan alongside the code:

- **`LLMContextPrecisionWithoutReference` → `LLMContextPrecisionWithReference`.** The former
  requires a `response` field; Layer 1 deliberately has no generated answer (see Phase 3's own
  sample-construction note). `LLMContextPrecisionWithReference` needs `reference` instead, which
  the sample already carries (`rationale`) — it's the metric that actually fits the plan's own
  sample shape.
- **`NonLLMContextPrecisionWithReference`/`NonLLMContextRecall` (fuzzy string match on
  ID-anchored strings) → `IDBasedContextPrecision`/`IDBasedContextRecall`.** This ragas version
  exposes ID-list-based variants (`retrieved_context_ids`/`reference_context_ids`) that do exact
  set comparison directly — strictly more correct than routing exact IDs through a fuzzy-string
  matcher and hoping the `[uuid]` prefix dominates the score, which was always a workaround for
  not having the ID-based metric in the first place.
- **`acceptable_ids` is applied asymmetrically**, per the golden dataset's own stated intent: for
  precision, the reference set is `expected_ids + acceptable_ids` (a defensible hit doesn't count
  as a false positive); for recall, it's `expected_ids` only (you don't get credit for finding an
  "acceptable" hotel when a specific one was required). Two separate `SingleTurnSample`s per
  record, not one shared reference set.

### A harness-only bug this plan's own execution found

`eval/harness/__init__.py` calls `load_dotenv(backend/.env)` itself, before putting `backend/` on
`sys.path`. This isn't redundant with `src/services/llm.py`'s own `load_dotenv()` call — it fixes
a real bug this plan's Phase 4 work hit: `src.config.get_settings()` is `@lru_cache`'d, and only
`src/services/llm.py` calls `load_dotenv()` in the backend itself. A harness script that imports
`src.agents.session` (or anything else that reaches `get_settings()`) before anything that happens
to import `src.services.llm` gets `Settings()` built from bare shell env — provider silently
defaults to `"ollama"`, model to `"llama3.1"` — and every OpenAI call then 404s
(`the model llama3.1 does not exist`) for the rest of the process, with no obvious link back to a
missing `.env` load. This is a harness-only fix (`eval/harness/__init__.py`, never
`backend/src/`) that removes the dependence on import order entirely.

## Judge key

The judge is OpenAI `gpt-4o-mini` at `temperature=0`, constructed via the app's own
`src/services/llm.py` factory (`get_llm(provider="openai", model="gpt-4o-mini")`), so eval and
app agree on how a provider is configured. It reads `OPENAI_API_KEY` from `backend/.env` — the
harness never has its own copy of the key. `python-dotenv`'s `load_dotenv()` inside `llm.py`
searches upward from that file's own location, so this resolves regardless of the directory the
harness is invoked from.

Embeddings (needed for `ResponseRelevancy`) come from `get_embeddings()`, which by default
resolves to the app's local Ollama `bge-m3` — a running Ollama server at `OLLAMA_URL` is
required for those metrics. Non-LLM metrics and `Faithfulness` do not need it.

## Judge response caching

`eval/harness/judge.py` wraps the judge and the embeddings in a `DiskCacheBackend`
(`eval/.ragas_cache/`, gitignored). Re-running an unchanged dataset costs nothing after the
first pass — a smoke-check run drops from ~3s/sample to ~0.01-0.08s/sample on a cache hit, with
identical scores.

## Smoke check (Phase 1 — do this first)

Before trusting any real dataset score, prove the judge wiring can actually discriminate:

```bash
eval/.venv-eval/bin/python eval/harness/smoke_check.py
```

Scores three hardcoded samples (obviously faithful, obviously hallucinated, Vietnamese) with
`Faithfulness()` and `NonLLMContextPrecisionWithReference()`. It asserts the hallucinated sample
scores at least 0.3 below the faithful one and that the Vietnamese sample is a real number, not
NaN. If either check fails, the judge wiring is broken — nothing downstream is trustworthy until
it passes.

## Running the full harness

```bash
# raw scores only, both layers, LLM metrics on
eval/.venv-eval/bin/python eval/run_ragas.py

# cheap iteration on one layer
eval/.venv-eval/bin/python eval/run_ragas.py --layer retrieval --limit 5 --no-llm-metrics

# turn a raw run into a report (recommended: pass hand-authored findings/caveats -
# see eval/harness/report.py's docstring for why these aren't auto-generated)
eval/.venv-eval/bin/python eval/harness/report.py eval/results/ragas-<ts>.json \
  --findings findings.md --caveats caveats.md

# freeze the current run as the committed regression baseline
eval/.venv-eval/bin/python eval/run_ragas.py --save-baseline

# diff a new run against the frozen baseline (refuses if the golden dataset changed)
eval/.venv-eval/bin/python eval/run_ragas.py --compare-baseline

# both steps chained, with placeholder findings/caveats (make -C backend eval-ragas)
make -C backend eval-ragas
```

`eval/run_ragas.py --layer e2e` replays the scripted conversations through the **real** agent
(`create_chat_session`/`process_chat_turn`) with a hook-less, `ragas-eval-`-prefixed session ID
— it never writes to the real session store. Expect this to take minutes, not seconds: it is
real LLM + real Supabase traffic per turn, not a mock.

## What a run costs

The 2026-08-11 baseline run: 44 retrieval queries (~197s of retrieval-side latency, judge-side
latency not separately measured) and 12 conversations (~380s of agent-turn latency). Cost is
reported as wall-clock + call count, not metered tokens — `ragas==0.3.9`'s token-usage parser
was not verified against this run's OpenAI client; see `eval/results/ragas-20260811-0342.md`'s
Run metadata and Caveats sections. The smoke check costs a handful of `gpt-4o-mini` calls —
negligible.

## Layout

```
eval/
  .venv-eval/          # gitignored — isolated Python env, ragas + backend src on sys.path
  .ragas_cache/         # gitignored — judge response cache
  requirements-eval.txt
  datasets/             # golden-retrieval.jsonl, golden-conversations.jsonl, README.md
  harness/
    judge.py            # judge LLM + embeddings, wired through src/services/llm.py
    dataset_loader.py    # strict-schema loaders for both golden datasets
    corpus_helper.py     # offline fixture filtering, authoring aid
    context_format.py    # as_context()/context_id() - ID-anchored string rendering
    context_recorder.py  # monkeypatches _execute_rpc for the duration of a turn
    retrieval_eval.py    # Layer 1 runner
    e2e_eval.py          # Layer 2 runner
    transcripts.py        # per-conversation markdown transcript writer
    report.py             # raw JSON -> report .md + .json, baseline diff, thresholds
    smoke_check.py         # Phase 1 sanity check — run this first
  run_ragas.py            # CLI entry: --layer retrieval|e2e|all, --save/--compare-baseline
  results/
    ragas-<ts>.json        # raw per-sample scores + diagnostics
    ragas-<ts>.md/-report.json  # report.py output
    baseline.json           # committed reference run
    transcripts/<conv-id>.md  # full e2e conversation transcripts
```
