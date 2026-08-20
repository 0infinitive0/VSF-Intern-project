---
phase: 1
title: "Extract the turn runner"
status: pending
priority: P1
effort: "1d"
dependencies: []
---

# Phase 1: Extract the turn runner

## Overview

Move the graph turn-execution cluster out of `src/api/routes.py` into its own module so a
caller can run one conversation turn without importing the HTTP layer. Pure refactor — zero
behaviour change.

## Problem

Running one turn today means calling `routes._run_turn_via_graph`, a private function in a
1,356-line FastAPI module. That is what makes eval fragile: the harness either couples itself
to the HTTP layer's privates, or (as before the cutover) to `session.py` internals that a
refactor can delete without anything noticing.

The functions are not HTTP concerns. `_run_turn_via_graph` builds graph input, drives the
graph, handles `interrupt()` resume, persists, and shapes a response. The only genuinely
HTTP-layer things it touches are two module globals: `registry` (session lifecycle) and
`_persistence_enabled` (a settings flag read at import time, `routes.py:129`).

## Requirements

- Functional: one importable function runs a turn given a session id, message, language, and
  optional extra state, and returns a `PlannerChatResponse`.
- Functional: the caller supplies the graph app and the persistence policy; the module reaches
  for no globals of its own.
- Non-functional: no behaviour change. Streaming and plain POST must still answer identically.
- Non-functional: `backend/requirements.txt` untouched.

## Architecture

New module `src/agents/graph/turn_runner.py` holding the cluster currently at
`routes.py:790-1090`:

| Function | Current location | Moves? |
|---|---|---|
| `_fresh_turn_input` | `routes.py:790` | yes |
| `_drive_turn` | `routes.py:895` | yes |
| `_persist_turn` | `routes.py:987` | yes, with injected policy |
| `_run_turn_via_graph` | `routes.py:1019` | yes, becomes public `run_turn` |
| `_response_from_result` | `routes.py:1089` | yes |
| `_get_graph_v2` | `routes.py:773` | **no** — stays in `routes.py` |

`_get_graph_v2` stays put deliberately: it caches a process-global compiled app and reads
`registry.checkpointer`, both of which are server-lifecycle concerns. Eval wants a fresh
throwaway app instead, which is exactly why the app is a parameter rather than something
`run_turn` fetches.

**The two globals become parameters.** This is the whole point of the phase:

```python
def run_turn(
    app,                                  # compiled graph, caller-owned
    session_id: str,
    message: str,
    language: str,
    extra_state: dict | None = None,
    *,
    stream: bool = False,
    persist: Callable[[str, Any, dict, list | None], None] | None = None,
) -> PlannerChatResponse:
```

`persist=None` means "do not persist" — the same structural guarantee the pre-cutover harness
got from passing no `persist_hook`. `routes.py` passes a small closure that keeps today's
`registry` + `_persistence_enabled` behaviour; eval passes nothing and *cannot* write to the
session store even if `SESSION_PERSISTENCE_ENABLED=true`, which it is.

`routes.py` keeps thin wrappers so its 8 call sites and their comments do not churn:

```python
def _run_turn_via_graph(session_id, message, language, extra_state=None, *, stream=False):
    return run_turn(
        _get_graph_v2(), session_id, message, language, extra_state,
        stream=stream, persist=_persist_policy,
    )
```

### What must not change

Move function bodies verbatim. The only permitted edits are the parameter substitutions above.
The docstrings on `_run_turn_via_graph`, `_drive_turn` and `_persist_turn` carry hard-won
reasoning (the interrupt-resume branch, `unresolved_resume_text`, why state is read from
`get_state` rather than the `invoke()` result, the `emit_phase("received")` 5-second
first-frame fix) — move them with their functions. Do not summarise them.

## Related Code Files

- Create: `backend/src/agents/graph/turn_runner.py`
- Modify: `backend/src/api/routes.py` (remove moved bodies, add wrappers + persist closure)

## Implementation Steps

1. Run impact analysis on `_run_turn_via_graph` and report the blast radius before editing
   (project convention: `impact({target, direction: "upstream"})`).
2. Create `turn_runner.py`; move the five functions verbatim, with their docstrings.
3. Replace the `_persistence_enabled` / `registry` reads inside `_persist_turn` with the
   injected `persist` callable.
4. In `routes.py`, define `_persist_policy` wrapping today's `registry.get` +
   `session_store.persist_graph_session` + `_persistence_enabled` guard.
5. Add the thin `_run_turn_via_graph` wrapper; leave all 8 call sites untouched.
6. Verify no import cycle: `turn_runner` must not import `src.api.*`.
7. `make test`.

## Success Criteria

- [ ] `backend/src/agents/graph/turn_runner.py` exists and imports nothing from `src.api`.
- [ ] `eval/.venv-eval/bin/python -c "from src.agents.graph.turn_runner import run_turn"` works.
- [ ] `run_turn(..., persist=None)` performs no session-store write — verified by a Supabase
      `sessions` row count unchanged across a call, not by reading the code.
- [ ] `make test` green.
- [ ] `git diff` shows moved function bodies unchanged apart from the parameter substitutions.
- [ ] Every call site in `routes.py` still reads as it did — no churn in unrelated lines.

## Risk Assessment

**A "pure move" that quietly changes behaviour.** The streaming path (`_drive_turn`) is the
riskiest: it touches `emit_phase`, `_DeclineGate`, `PHASE_KEY_BY_NODE` and `STREAMING_NODES`.
If any of those resolve differently after the move, streaming turns change without a test
necessarily catching it. Mitigation: move verbatim, keep the imports pointing at the same
modules, and manually exercise one streaming turn before closing the phase.

**Import cycle.** `turn_runner` needs `PlannerChatResponse` from `src.models.schemas`, which is
safe, but pulling anything from `src.api` would cycle. Explicit success criterion above.

**Scope creep.** `routes.py` is 1,356 lines and there is more worth extracting. Do not. This
phase moves exactly what eval needs to call a turn.
