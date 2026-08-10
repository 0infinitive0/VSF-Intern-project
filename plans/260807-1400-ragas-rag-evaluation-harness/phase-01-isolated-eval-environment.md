---
phase: 1
title: "Isolated eval environment"
status: pending
priority: P1
effort: "0.5d"
dependencies: []
---

# Phase 1: Isolated eval environment

## Overview

Stand up a working RAGAS installation that is isolated from the backend runtime, wire the judge
LLM and embeddings through the project's own model factory, and prove the whole thing scores a
hand-written three-sample dataset before any real data is involved.

## Requirements

- Functional: `eval/.venv-eval` runs `ragas==0.3.9` and scores a trivial dataset with a real judge.
- Functional: judge and embeddings are constructed from `src.services.llm`, not hardcoded clients.
- Functional: judge responses are disk-cached so re-runs cost nothing.
- Non-functional: `backend/requirements.txt` unchanged; backend imports unaffected.
- Non-functional: no secrets in committed files; the harness reads `backend/.env`.

## Architecture

Two Python environments coexist:

- `backend/` runtime — unchanged, no ragas.
- `eval/.venv-eval` — ragas plus the backend's own source on `PYTHONPATH`, so the harness can call
  `src.services.supabase_search` and `src.agents.session` directly rather than over HTTP. Calling
  in-process is what makes Phase 4's context recorder possible at all.

The pre-existing global `ragas 0.1.22` is broken here (see plan's established facts) and must be
shadowed by the venv, never repaired in place — repairing it would mean downgrading
`langchain-core` below what the app needs.

Judge construction reuses `src/services/llm.py`'s factory so the eval and the app agree on how a
provider is configured:

```python
# eval/harness/judge.py
from ragas.cache import DiskCacheBackend
from ragas.embeddings import LangchainEmbeddingsWrapper
from ragas.llms import LangchainLLMWrapper

from src.services.llm import get_embeddings, get_llm

_CACHE = DiskCacheBackend(cache_dir=".ragas_cache")

def build_judge():
    """gpt-4o-mini at temperature 0 — deterministic enough to compare runs."""
    return LangchainLLMWrapper(
        get_llm(provider="openai", model="gpt-4o-mini", temperature=0.0),
        cache=_CACHE,
    )

def build_judge_embeddings():
    """ResponseRelevancy needs embeddings; reuse the app's configured model."""
    return LangchainEmbeddingsWrapper(get_embeddings())
```

Verify `DiskCacheBackend`'s constructor signature and whether `LangchainLLMWrapper` takes `cache=`
in 0.3.9 at implementation time — adjust to whatever that version actually exposes rather than to
this sketch.

## Related Code Files

- Create: `eval/requirements-eval.txt`
- Create: `eval/harness/__init__.py`, `eval/harness/judge.py`
- Create: `eval/harness/smoke_check.py`
- Create: `eval/README.md`
- Modify: `.gitignore` — add `eval/.venv-eval/`, `eval/**/.ragas_cache/`
- Modify: `backend/Makefile` — add `eval-ragas` target
- Read only: `backend/src/services/llm.py`, `backend/.env`

## Implementation Steps

1. Create `eval/requirements-eval.txt`:
   ```
   ragas==0.3.9
   rapidfuzz>=3.9          # NonLLMContextPrecisionWithReference needs it
   python-dotenv>=1.0.0
   langchain-openai>=1.4.0
   langchain-ollama>=1.1.0 # embeddings factory imports it
   ```
2. `python3 -m venv eval/.venv-eval && eval/.venv-eval/bin/pip install -r eval/requirements-eval.txt`.
3. Confirm the isolation actually holds: `eval/.venv-eval/bin/python -c "import ragas, langchain_core; print(ragas.__version__, langchain_core.__version__)"`
   must print `0.3.9` and a `1.5.x` — if it prints `0.1.22`, the venv is leaking to the pyenv global
   and needs `--no-site-packages` behaviour confirmed.
4. Write `eval/harness/judge.py` as above. Load `backend/.env` via `dotenv` so `OPENAI_API_KEY`
   resolves without duplicating the file.
5. Write `eval/harness/smoke_check.py`: three hardcoded `SingleTurnSample`s (one obviously
   faithful, one obviously hallucinated, one Vietnamese) scored with `Faithfulness()` and
   `NonLLMContextPrecisionWithReference()`.
6. Run it. **The hallucinated sample must score materially lower than the faithful one.** If all
   three come back identical or NaN, the judge wiring is wrong — stop here, do not proceed to
   Phase 2 on a judge that cannot discriminate.
7. Re-run and confirm the second run is visibly faster (cache hit) and returns identical scores.
8. Add `eval-ragas` to `backend/Makefile` pointing at `eval/.venv-eval/bin/python eval/run_ragas.py`
   (the script arrives in Phase 3; the target may fail until then).
9. Write `eval/README.md`: setup commands, why the venv is separate, how to set the judge key,
   what a run costs.

## Success Criteria

- [ ] `eval/.venv-eval/bin/python -c "import ragas; print(ragas.__version__)"` prints `0.3.9`.
- [ ] `smoke_check.py` scores the hallucinated sample at least 0.3 below the faithful one.
- [ ] The Vietnamese sample returns a real number, not NaN — proving the judge handles VI.
- [ ] Second run of `smoke_check.py` returns identical scores and completes faster.
- [ ] `git diff backend/requirements.txt` is empty.
- [ ] `eval/.venv-eval/` and cache dirs are gitignored; `git status` stays clean after a run.

## Risk Assessment

- **The broken global `ragas 0.1.22` shadows the venv** if the harness is ever run with the wrong
  interpreter. Every documented command uses the explicit `eval/.venv-eval/bin/python` path; the
  Makefile target does too. Step 3 is the check that catches this.
- **`get_llm(provider="openai", ...)` may not accept exactly these kwargs.** Read
  `backend/src/services/llm.py:67` before writing `judge.py` and match the real signature.
- **`get_embeddings()` defaults to Ollama `bge-m3`** — if the Ollama server is down,
  `ResponseRelevancy` fails while faithfulness still works. Make the smoke check report which
  backend the embeddings resolved to.
- **Judge determinism is approximate.** `temperature=0` is not a guarantee across API-side model
  updates. Cache makes within-window re-runs exact; cross-window drift is a reporting caveat, not a
  bug to chase.
