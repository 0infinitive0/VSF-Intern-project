"""Records every LLM call made inside a `with record_usage(...)` block.

The durable home for the mechanism Phase 1's `usage_probe.py` proved: a
`BaseCallbackHandler` bound to a `ContextVar` and registered through
`register_configure_hook`, which langchain consults when it builds the callback
manager for *any* LLM call. No monkeypatch, no per-call-site plumbing, and it reaches
calls made deep inside a LangGraph node the harness never touches directly.

Shaped like `context_recorder.record_contexts()`: capture is opt-in per block, the
ContextVar defaults to `None`, so importing this module instruments nothing.

**One measured limitation, and it decides how callers must drive their work.** A
`ContextVar` is per-thread. Capture survives `graph.invoke()` (including parallel
supersteps) and `asyncio.to_thread`, but a call made through
`ThreadPoolExecutor.submit` or `loop.run_in_executor` is invisible — it records
nothing and raises nothing, so the failure looks like a free turn. Measured in Phase 1;
`api/routes.py`'s streaming path uses `run_in_executor`, which is why the e2e harness
drives turns synchronously in its own thread.

**Cache hits are not observable here.** A ragas `DiskCacheBackend` hit fires *zero*
callbacks (measured, Phase 1) — there is no call to tag. So cache state is not a field
on a call record; it is derived by the caller, which knows how many scoring operations
it asked for and can compare that against how many calls this recorder actually saw.
`cache_hits_from(...)` below does that subtraction in one place.
"""

from __future__ import annotations

import contextlib
import time
from contextvars import ContextVar
from typing import Any

from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_core.outputs import LLMResult
from langchain_core.tracers.context import register_configure_hook


class UsageRecorder(BaseCallbackHandler):
    """Collects one record per completed LLM call, tagged with the block's scope.

    `scope` is set by the enclosing context rather than inferred from the model name.
    The app and the judge could in principle run the same model, and a name-based rule
    would then misattribute spend between "what a user turn costs" and "what an eval
    pass costs" — the exact two numbers this separation exists to keep apart.
    """

    def __init__(self, scope: str) -> None:
        self.scope = scope
        self.calls: list[dict[str, Any]] = []
        self._started_at: dict[Any, float] = {}

    # Both start hooks matter: a chat model reports through `on_chat_model_start`, a
    # plain LLM through `on_llm_start`, and both finish through `on_llm_end`.
    def on_llm_start(self, serialized: dict, prompts: list[str], *, run_id: Any = None, **kwargs: Any) -> None:
        self._started_at[run_id] = time.perf_counter()

    def on_chat_model_start(self, serialized: dict, messages: list, *, run_id: Any = None, **kwargs: Any) -> None:
        self._started_at[run_id] = time.perf_counter()

    def on_llm_end(self, response: LLMResult, *, run_id: Any = None, **kwargs: Any) -> None:
        self.calls.append(self._record(response, run_id, error=None))

    def on_llm_error(self, error: BaseException, *, run_id: Any = None, **kwargs: Any) -> None:
        # A failed call still consumed wall clock, and often input tokens. Dropping it
        # would make a run of failures look faster and cheaper than it was.
        self.calls.append(
            {
                "scope": self.scope,
                "model": None,
                "latency_s": self._elapsed(run_id),
                "usage_metadata": None,
                "error": f"{type(error).__name__}: {error}",
            }
        )

    def _elapsed(self, run_id: Any) -> float | None:
        started = self._started_at.pop(run_id, None)
        return None if started is None else round(time.perf_counter() - started, 4)

    def _record(self, response: LLMResult, run_id: Any, error: str | None) -> dict[str, Any]:
        message = None
        try:
            message = getattr(response.generations[0][0], "message", None)
        except IndexError:
            pass

        llm_output = response.llm_output or {}
        response_metadata = getattr(message, "response_metadata", None) or {}

        return {
            "scope": self.scope,
            # Cost cannot be computed without knowing which price applies, and the app
            # uses two different models within a single turn.
            "model": llm_output.get("model_name") or response_metadata.get("model_name"),
            "latency_s": self._elapsed(run_id),
            # Kept whole rather than flattened: `input_token_details.cache_read` and
            # `output_token_details.reasoning` are sub-fields, and Phase 4 prices from them.
            "usage_metadata": getattr(message, "usage_metadata", None),
            "error": error,
        }


_recorder_var: ContextVar[UsageRecorder | None] = ContextVar("usage_recorder", default=None)

# handle_class=None makes langchain's `_configure` dedup by pointer identity, so a
# nested callback manager cannot add the same recorder twice.
register_configure_hook(_recorder_var, True)

#: Calls from every completed block this process has run, in order. `take_usage()`
#: drains it, which is how a layer collects its own calls without threading a
#: collector object through every function between here and the call site.
_RUN_CALLS: list[dict[str, Any]] = []

#: Judge scoring operations requested since the last drain. Counted at the call site
#: because it is the only place that knows an operation was *asked for*; whether it
#: reached a model is what `_RUN_CALLS` says, and the difference is the cache hits.
_RUN_SCORING_OPS = 0


@contextlib.contextmanager
def record_usage(scope: str):
    """Yields a `UsageRecorder` capturing every LLM call made inside the block."""
    recorder = UsageRecorder(scope)
    token = _recorder_var.set(recorder)
    try:
        yield recorder
    finally:
        # Reset in `finally` is not optional: a leaked ContextVar would attribute every
        # later call in this process to a scope it never ran in.
        _recorder_var.reset(token)
        _RUN_CALLS.extend(recorder.calls)


def note_scoring_operations(n: int) -> None:
    """Record that `n` judge scoring operations were requested."""
    global _RUN_SCORING_OPS
    _RUN_SCORING_OPS += n


def take_usage() -> dict[str, Any]:
    """Everything recorded since the last drain, and clears the buffers.

    Drained per layer so retrieval and e2e keep separate figures; pooling them would
    average two distributions that describe different things.
    """
    global _RUN_SCORING_OPS
    usage = {"calls": list(_RUN_CALLS), "scoring_operations": _RUN_SCORING_OPS}
    _RUN_CALLS.clear()
    _RUN_SCORING_OPS = 0
    return usage


def assert_streaming_usage_enabled() -> None:
    """Fail the run if a streamed app call would report no tokens.

    `qa_node` and `intake_qa` build their model with `streaming=True`. langchain-openai
    enables `stream_options.include_usage` for OpenAI-hosted endpoints automatically,
    but **only** when no custom `base_url` / `OPENAI_BASE_URL` is configured — point
    `LLM_API_BASE` at a proxy and streamed usage silently switches off. The cost of
    every streaming-node turn then reads as zero, which is indistinguishable from a
    cheap turn and corrupts the cost report without any error.

    A config check, not a live call: it costs nothing and runs before the first query.
    The backend's own regression test pins the library default; this catches the
    environment, which that test cannot see.
    """
    from src.services.llm import get_fast_llm  # noqa: PLC0415  (backend import, harness-time only)

    llm = get_fast_llm(temperature=0.0, streaming=True)
    if not getattr(llm, "stream_usage", None):
        raise RuntimeError(
            f"{type(llm).__name__} for the streaming nodes has stream_usage="
            f"{getattr(llm, 'stream_usage', None)!r}: streamed calls would report no token "
            "usage and every qa_node/intake_qa turn would be costed at zero. Usually caused by "
            "LLM_API_BASE/OPENAI_BASE_URL pointing at a non-OpenAI endpoint."
        )


def cache_hits_from(scoring_operations: int, observed_calls: int) -> int:
    """Scoring operations that never reached a model, i.e. `DiskCacheBackend` hits.

    Derived by subtraction because a cache hit fires no callback at all. Clamped at
    zero: one scoring operation can legitimately make several model calls (a ragas
    metric with multiple internal steps), which would otherwise read as negative hits.
    """
    return max(0, scoring_operations - observed_calls)


def cache_state(scoring_operations: int, observed_calls: int) -> str:
    """`cold` | `warm` | `mixed` | `n/a` — the label a judge latency table needs.

    A cached judge answers in ~0.01s against ~2s cold, so an unlabelled judge p50 is a
    measurement of the disk cache rather than of the judge.
    """
    if scoring_operations == 0:
        return "n/a"
    hits = cache_hits_from(scoring_operations, observed_calls)
    if hits == 0:
        return "cold"
    if hits >= scoring_operations:
        return "warm"
    return "mixed"
