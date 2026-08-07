"""SSE transport for streaming chat turns.

`POST /api/v1/planner_chat/stream` runs the same blocking `process_chat_turn`
as the plain POST endpoint inside a worker thread (handlers stay `def` / plain
blocking callables — Supabase/Ollama calls must not stall the event loop, see
routes.py docstring). This module is the one-way bridge from that worker
thread to the async SSE generator:

- `TurnEmitter` — `emit()` is called from deep inside the synchronous
  pipeline and must NEVER block: blocking here would deadlock the turn whose
  progress it is reporting. Delivery to the async side runs through
  `loop.call_soon_threadsafe` onto an `asyncio.Queue`, NOT a thread-blocking
  `queue.SimpleQueue` polled via `run_in_executor` — the earlier version of
  this module did exactly that, and it cost one MORE executor thread per
  active stream (on top of the one `_run_turn` already holds for the whole
  turn) just to poll, roughly once a second, for the turn's entire duration.
  `run_in_executor(None, ...)` draws from asyncio's own default
  `ThreadPoolExecutor(max_workers=min(32, cpu_count+4))` — 6 threads on a
  2-vCPU box — so a handful of concurrent streams could starve it: `_run_turn`
  threads pile up (1 per stream, held for the turn), and any executor slot
  the polling loop needs beyond that queues behind them, delaying phase/delta
  delivery (though `_run_turn` itself, not depending on `_poll`, still runs
  to completion). `call_soon_threadsafe` costs zero executor threads — it
  schedules a plain callback directly on the event loop from any thread.
- `sse_stream` — async generator that awaits the queue with a short timeout
  so heartbeats (`: heartbeat` comment frames every 15s, guarding against
  proxy idle timeouts) stay possible while the worker thread is busy.
  Client-disconnect detection is deliberately NOT done via
  `request.is_disconnected()`: under BaseHTTPMiddleware the request's receive
  channel is dead once call_next() returns, so calling it from inside the
  body iterator raises instead of reporting. Real servers (uvicorn) surface a
  disconnect by cancelling the response task / closing the generator, which
  terminates this loop without any extra code. The worker thread keeps
  running to completion either way (blocking calls can't be aborted
  mid-flight) and the small queue simply drains into a garbage-collected
  buffer, so session state stays valid server-side.

Frame format (contract: docs/chat_api_contract.md §Streaming, frozen by plan
260806-1602-streaming-chat-messages Phase 1):

    event: <name>\n
    data: <json, ensure_ascii=False>\n
    \n

Event names (shipped subset — `cancelled` is reserved by the plan but not
shipped; turn cancellation is out of scope, see phase-04, currently paused):
    phase | delta | reset | final | error
Every stream ends with EXACTLY ONE terminal frame: `final` or `error`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

#: Marks end-of-stream inside the emitter queue.
_SENTINEL = object()

HEARTBEAT_SECONDS = 15.0

#: Headers every streaming response must carry. `X-Accel-Buffering: no` asks
#: any nginx layer we don't own (Vite dev proxy, the repo's own nginx.conf is
#: handled separately) not to buffer SSE; `Cache-Control: no-cache` for
#: intermediaries in general.
STREAM_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


@dataclass
class StreamEvent:
    """One SSE event: `event` name + JSON-serializable `data` dict."""

    event: str  # "phase" | "delta" | "reset" | "final" | "error"
    data: dict[str, Any]


class TurnEmitter:
    """One-way channel from the worker thread (sync) to the SSE generator (async).

    `emit()` is called from deep inside the synchronous pipeline and NEVER
    blocks: it schedules delivery via `loop.call_soon_threadsafe`, which is
    safe to call from any thread and costs no executor slot (see module
    docstring for why that matters). `loop` MUST be the event loop that will
    run `sse_stream(this emitter)` — captured with `asyncio.get_running_loop()`
    in the async handler, before the worker thread starts.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._queue: asyncio.Queue[Any] = asyncio.Queue()

    def emit(self, event: str, **data: Any) -> None:
        self._loop.call_soon_threadsafe(self._queue.put_nowait, StreamEvent(event, data))

    async def get(self, timeout: float) -> Any:
        """Await one item with a timeout → StreamEvent | None on timeout;
        `_SENTINEL` once `close()` has run. Must be awaited from `loop`."""
        try:
            return await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except TimeoutError:
            return None

    def close(self) -> None:
        self._loop.call_soon_threadsafe(self._queue.put_nowait, _SENTINEL)


def format_sse(event: str, data: dict[str, Any]) -> str:
    """Format one SSE frame. `ensure_ascii=False` is mandatory: replies are
    Vietnamese, escaping to \\uXXXX would triple frame size."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# ---------------------------------------------------------------------------
# Turn-progress emitter plumbing (plan 260806-1602 Phase 2)
# ---------------------------------------------------------------------------

#: Emitter of the turn currently running in THIS context. Set inside the
#: worker thread that runs the turn (never in the async handler) — ContextVar
#: values are per-context, so two concurrent turns never see each other's
#: emitter, and a plain POST turn (no wrapping) sees None everywhere.
_current_emitter: ContextVar[TurnEmitter | None] = ContextVar("turn_emitter", default=None)


def emit_phase(key: str, **data: Any) -> None:
    """Emit one `phase` SSE event if the current turn is streaming; otherwise a
    no-op costing one ContextVar read.

    NEVER raises — a bug in the instrumentation path must not kill a chat
    turn. `key` is an opaque progress key (contract §Streaming — the frontend
    owns i18n labels); `data` carries optional extras like tool= / route=.
    """
    try:
        em = _current_emitter.get()
        if em is not None:
            em.emit("phase", key=key, at=time.time(), **data)
    except Exception:
        logger.debug("emit_phase failed for %s", key, exc_info=True)


@contextmanager
def emitting_to(emitter: TurnEmitter | None) -> Iterator[None]:
    """Bind `emitter` as the current turn's emitter for the block, then reset.

    MUST be entered inside the worker thread that runs the turn, NOT in the
    async SSE handler: run_in_executor does not propagate the handler's
    context — each worker thread gets its own, so set/reset here, exactly
    once per turn. The finally-reset also guarantees no emitter leaks into a
    reused thread-pool thread's next task.
    """
    token = _current_emitter.set(emitter)
    try:
        yield
    finally:
        _current_emitter.reset(token)


def emit_reset(reason: str) -> None:
    """Emit a `reset` frame: instructs the client to discard all buffered delta
    text (for the most recent streaming attempt) and re-render.

    Contract guarantees: sent before the retry/fallback that replaces flushed
    text, never on the plain POST path, never raises. Reasons currently
    emitted (all from `_run_chat_agent`, only when the gate had already
    flushed something): "discarded_tool_call_json" | "tool_error" |
    "provider_error" | "superseded_by_tool_response".
    """
    try:
        em = _current_emitter.get()
        if em is not None:
            em.emit("reset", reason=reason)
    except Exception:
        logger.debug("emit_reset failed (%s)", reason, exc_info=True)


# ---------------------------------------------------------------------------
# Token-stream delta gate (plan 260806-1602 Phase 3)
# ---------------------------------------------------------------------------


#: The one fixed prefix `_DeltaGate` watches for besides a bare `{`/`[`. Kept
#: as a module constant so the incremental prefix match in `_DeltaGate.feed()`
#: and the length check in `close()` can't drift apart from each other.
_SYSTEM_ERROR_PREFIX = "SYSTEM ERROR:"


class _DeltaGate:
    """Streams agent tokens as `delta` frames per feed() call (true per-token
    streaming, no batching, no fixed startup delay), gating the WHOLE attempt
    against tool-call JSON / internal error text as early as each new
    character makes that conclusively decidable.

    This is the fix for the two traps documented in plan
    260806-1602-streaming-chat-messages phase-03 ("Bẫy 1"/"Bẫy 2"):
    `_looks_like_textual_tool_call` (session.py) and `sanitize_system_error`
    (routes.py) both key off the response's *prefix* (`strip().startswith("{")`
    / a `"SYSTEM ERROR:"` lead-in) — but they only run once the full text is
    known, which for a stream is too late to un-send a frame. So the gate
    makes the same prefix decision itself, before forwarding anything: if the
    stripped content starts with `{`/`[`, or turns out to equal the literal
    `"SYSTEM ERROR:"` (13 chars) once enough of it has arrived, the attempt is
    muted for good — no delta is EVER emitted for it.

    The decision is made INCREMENTALLY, not after a fixed character count:
      - a `{`/`[` first real character decides "muted" immediately (1 char).
      - any other first real character that isn't `S` decides "safe"
        immediately (1 char) — the vast majority of replies.
      - a first character of `S` (and only that case) can be the start of
        `"SYSTEM ERROR:"`, so the gate keeps checking, char by char, whether
        the buffer is STILL a valid prefix of that literal string. The
        instant it diverges (e.g. second char isn't `Y`), "safe" is decided
        right there — it can never become `"SYSTEM ERROR:"` from that point.
        Only a genuine `"SYSTEM ERROR:"` lead-in pays the full 13-char wait.
    Measured on STRIPPED (non-whitespace) content — a leading run of
    whitespace never counts as "real" characters, so it can't shortcut a
    decision on zero real content (reproduced bug from an earlier, fixed-
    threshold version of this class: whitespace padding made the gate decide
    "open" on nothing, letting a `{...}` chunk fed right after stream through
    unchecked).

    Once the gate opens (decided True), every `feed()` call flushes
    immediately, whole and unsliced (never splitting a multi-byte UTF-8
    sequence — splitting only ever happens between whole fed chunks, so
    surrogate pairs / combining sequences are safe): true per-token/per-chunk
    streaming, matching how a real chat UI's typewriter effect works.

    Invariants (all test-asserted):
      - gate stays shut (no delta ever) for content starting with `{`, `[`,
        or `SYSTEM ERROR:`, even across many small feed() calls, even with
        leading whitespace, even when a chunk boundary lands mid-prefix
      - a first real character other than `{`/`[`/`S` opens the gate on
        that single character — no multi-char wait
      - concat(fed chunks) == concat(emitted delta texts) when the gate is
        open and close() runs
      - when no emitter is bound (plain POST turn), feed() only accumulates

    A discarded/superseded attempt does not call any method here to mute
    it — `_run_chat_agent` just drops the old instance and starts a fresh
    `_DeltaGate()` for what follows (see the tool_calls-detection reset),
    after emitting a `reset` frame if the old one had flushed_any.
    """

    def __init__(self) -> None:
        self._chunks: list[str] = []   # flushed (gate open only)
        self._buffer: list[str] = []   # accumulated, not yet flushed
        self._gate_open: bool | None = None  # None=undecided, False=muted for good
        self._closed = False
        self._generating_emitted = False

    def feed(self, chunk: str) -> None:
        if self._closed or not chunk:
            return
        self._buffer.append(chunk)
        if self._gate_open is False:
            return  # muted: keep accumulating (harmless), never flush
        if self._gate_open is None:
            self._decide()
            if self._gate_open is not True:
                return  # still muted, or still an ambiguous "SYSTEM ERROR:" prefix
        # Gate is open: flush this feed() call immediately, whatever its
        # size — true per-token streaming, no batching.
        self._flush()

    def close(self) -> None:
        """Flush the remaining buffer exactly once. Idempotent. Runs the same
        incremental check as feed() one last time — the only new fact at
        end-of-stream is that an ambiguous (still-growing, never-completed)
        `"SYSTEM ERROR:"` prefix (e.g. the entire reply is just "System") can
        now be resolved: since no more characters are coming, the full
        13-char literal never appeared and never will, so it was never
        actually `"SYSTEM ERROR:"` — safe to flush."""
        if self._closed:
            return
        self._closed = True
        if self._gate_open is None:
            self._decide()
            if self._gate_open is None:
                self._gate_open = True  # ambiguous prefix, but no more input coming
        if self._gate_open is not False:
            self._flush()

    @property
    def flushed_any(self) -> bool:
        """True once at least one delta frame actually reached the client —
        the rollback marker (reset frame) is only meaningful then."""
        return bool(self._chunks)

    def _decide(self) -> None:
        """Incremental prefix check, called from every feed() while
        `_gate_open` is still None. Leaves it None (ambiguous, keep
        buffering) only while the stripped buffer is still a valid,
        not-yet-complete prefix of `_SYSTEM_ERROR_PREFIX` — every other case
        resolves immediately, True or False, on the spot."""
        stripped = "".join(self._buffer).lstrip()
        if not stripped:
            return  # no real character yet — can't decide on nothing
        if stripped[0] in ("{", "["):
            self._gate_open = False
            return
        probe_len = min(len(stripped), len(_SYSTEM_ERROR_PREFIX))
        if stripped[:probe_len] == _SYSTEM_ERROR_PREFIX[:probe_len]:
            if len(stripped) >= len(_SYSTEM_ERROR_PREFIX):
                self._gate_open = False  # full "SYSTEM ERROR:" match
            # else: still a valid, growing prefix — stay None, keep waiting
            return
        self._gate_open = True  # diverged from the only watched prefix — safe

    def _flush(self) -> None:
        if self._gate_open is False or not self._buffer:
            return
        text = "".join(self._buffer)
        self._buffer = []
        self._chunks.append(text)
        try:
            em = _current_emitter.get()
            if em is None:
                return
            if not self._generating_emitted:
                # "generating" fires exactly once per attempt, immediately
                # before the first delta the gate actually lets through.
                self._generating_emitted = True
                em.emit("phase", key="generating", at=time.time())
            em.emit("delta", text=text)
        except Exception:
            logger.debug("delta emission failed", exc_info=True)


async def sse_stream(
    emitter: TurnEmitter,
    *,
    poll_timeout: float = 1.0,
) -> AsyncIterator[str]:
    """Yields SSE frames from the emitter until `close()`.

    Order guarantee comes from the emitter queue; a terminal frame (`final` /
    `error`) is always enqueued before `close()` by the endpoint worker.
    Client disconnect surfaces as task cancellation / generator close from the
    ASGI server, which ends this loop without explicit handling.
    """
    yield ": open\n\n"  # force proxies to flush headers immediately
    last_beat = time.monotonic()
    while True:
        item = await emitter.get(poll_timeout)
        if item is _SENTINEL:
            break
        if item is not None:
            try:
                frame = format_sse(item.event, item.data)
            except (TypeError, ValueError):
                # A non-JSON-serializable value in `data` must not crash this
                # generator with no terminal frame ever sent — every emit_*
                # call site passes only JSON-safe primitives today, but a
                # future one that doesn't must degrade to a dropped frame,
                # not a silently unterminated stream.
                logger.warning("Dropping non-serializable %s frame", item.event, exc_info=True)
                continue
            yield frame
            last_beat = time.monotonic()
        elif time.monotonic() - last_beat > HEARTBEAT_SECONDS:
            yield ": heartbeat\n\n"
            last_beat = time.monotonic()
