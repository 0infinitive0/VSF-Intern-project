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
    phase | delta | reasoning | final | error
Every stream ends with EXACTLY ONE terminal frame: `final` or `error`.
`reasoning` is never terminal, and a valid turn may carry none of it.

`reset` used to be a fifth name. It meant "discard the text streamed so far",
which only a producer that could stream text it might have to retract needed —
the old `_DeltaGate`, which guessed from a reply's first characters whether it
was really tool-call JSON. Nothing ever constructed that gate on the graph
plane, so neither it nor `reset` had run since the cutover, and node-level
filtering (`graph/phase_keys.py`) removes the guess that made retraction
necessary at all: text is decided streamable before any of it is sent.
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

    event: str  # "phase" | "delta" | "reasoning" | "final" | "error"
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
    owns i18n labels).

    `data` carries the step's facts: counts, ids, and field paths, never display
    text. Two producers supply them — `phase_facts` reads the dict a node just
    returned, and a service that knows more than its state delta shows emits its
    own (`hotel_node._result`, `routing.py`). The contract's phase-key table
    lists every field; anything not listed there must not be added here.
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


def emit_delta(text: str) -> None:
    """Emit one `delta` SSE event carrying a chunk of reply text.

    Symmetric with `emit_phase`: same no-emitter guard (a plain POST turn sees
    None and this costs one ContextVar read), same never-raises rule.

    There is no gate or prefix check here, and that is the design. Deciding
    what may be streamed happens once, structurally, by node name
    (`graph/phase_keys.py`'s `STREAMING_NODES`) before this is ever called —
    the predecessor of this function guessed at the text instead, because the
    plane it was written for could not tell which component was talking.
    """
    if not text:
        return
    try:
        em = _current_emitter.get()
        if em is not None:
            em.emit("delta", text=text)
    except Exception:
        logger.debug("emit_delta failed", exc_info=True)


def emit_reasoning(text: str, phase_key: str) -> None:
    """Emit one `reasoning` SSE event carrying the model's summary of its own
    reasoning.

    Deliberately NOT folded into `delta`. The contract says `delta` is a prefix
    of the reply `final` carries (docs/chat_api_contract.md §Streaming), and a
    reasoning summary is not part of the reply at all — mixing them would break
    an invariant clients rely on. A separate event also lets a client tell
    model-written prose from product-written prose, which matters here: this text
    is always English, even in a Vietnamese conversation.

    `phase_key` names the step the reasoning belongs to, and it is required
    rather than optional: these frames arrive WHILE the node runs, but the node's
    own `phase` frame is emitted only once it finishes. A client that attached
    the text to whichever step was open would file the model's thinking about
    composing an answer under whatever ran before it.

    Same guards as `emit_delta`: no-op without an emitter, never raises, drops
    the empty string — and empty is the COMMON case. A model emits a summary only
    when it actually reasons, and a tool-calling step has none to summarize.
    """
    if not text:
        return
    try:
        em = _current_emitter.get()
        if em is not None:
            em.emit("reasoning", text=text, key=phase_key)
    except Exception:
        logger.debug("emit_reasoning failed", exc_info=True)


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
