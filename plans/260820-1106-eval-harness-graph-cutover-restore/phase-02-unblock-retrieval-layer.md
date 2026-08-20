---
phase: 2
title: "Unblock Layer 1"
status: pending
priority: P1
effort: "0.5d"
dependencies: []
---

# Phase 2: Unblock Layer 1

## Overview

Stop a broken Layer 2 from killing the whole CLI, and add the cheap test that would have caught
this breakage the day it landed.

## Problem

`eval/run_ragas.py:16` imports `e2e_eval` at module scope. `e2e_eval.py:18` raises
`ImportError`. So every invocation dies, including `--help` and `--layer retrieval` — a layer
whose own code is perfectly healthy and, as verified, executes fine against the live corpus.

This is a two-line structural fault with a disproportionate blast radius, and it is independent
of the real migration work. It lands first.

## Requirements

- Functional: `--layer retrieval` runs with Layer 2 still broken.
- Functional: `--layer e2e` fails with a message naming what is wrong, not a bare `ImportError`
  traceback from an unrelated line.
- Functional: a test in the normal suite fails when a harness module stops importing.
- Non-functional: the test must not make LLM calls, hit Supabase, or need Ollama.

## Architecture

**Defer the import.** Move `from harness.e2e_eval import ...` out of module scope and into the
branch that actually runs the e2e layer. Layer 1 then has no path to Layer 2's imports.

Wrap the deferred import so the failure is legible:

```python
def _load_e2e():
    try:
        from harness.e2e_eval import ConversationResult, run_e2e_eval
    except ImportError as exc:
        raise SystemExit(
            f"The e2e layer is unavailable: {exc}\n"
            "Layer 2 targets the graph turn runner; see "
            "plans/260820-1106-eval-harness-graph-cutover-restore/."
        ) from exc
    return ConversationResult, run_e2e_eval
```

Deferring an import to dodge a broken module is normally a smell. Here it is the correct
coupling: `--layer retrieval` has no business loading the e2e runner at all, and the current
top-level import is precisely what turned one broken layer into a dead CLI.

**Import smoke test.** A test that imports every `eval/harness/*.py` module and asserts no
`ImportError`. Pure import, no I/O, milliseconds. Had this existed, phase 11 of the cutover
plan would have gone red instead of silent.

Where it lives is a judgement call: `backend/tests/` runs in `make test` (so it actually guards
refactors) but `eval/` is a separate venv with different deps. Import the harness modules by
path and `skip` — not fail — when `ragas` is absent, so the backend suite stays runnable
without the eval venv while still catching a deleted backend symbol.

## Related Code Files

- Modify: `eval/run_ragas.py`
- Create: `backend/tests/test_eval_harness_imports.py`

## Implementation Steps

1. Move the `e2e_eval` import into `_load_e2e()`, called only on the e2e path.
2. Confirm `dataset_hash` (still needed by both layers) does not come from `e2e_eval`.
3. Write the import smoke test, skipping cleanly when `ragas` is unavailable.
4. Verify: `run_ragas.py --help` exits 0 while `e2e_eval.py` is still broken.
5. Run `--layer retrieval --limit 5 --no-llm-metrics` against the live corpus with Ollama up.

## Success Criteria

- [ ] `run_ragas.py --help` exits 0 with Layer 2 still broken.
- [ ] `--layer retrieval --limit 5 --no-llm-metrics` completes, 0 harness errors.
- [ ] `--layer e2e` prints the explanatory message, not a raw traceback.
- [ ] `test_eval_harness_imports.py` fails if any harness module stops importing, and skips
      (not fails) when `ragas` is missing.
- [ ] Full `--layer retrieval` over all 44 records completes with 0 harness errors.

## Risk Assessment

**Ollama must be running** for `bge-m3` embeddings — the live check in this plan's research
failed on exactly that. Environmental, not a code fault, but it blocks the success criteria
until the server is up.

**The smoke test could be neutered by an over-broad skip.** If the skip condition is wider than
"ragas not installed", the test silently passes forever and the guard is theatre. Assert that
the test actually *runs* (not skips) in the eval venv.

**Low risk overall.** Nothing here touches production code or the golden datasets.
