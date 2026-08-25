"""Run one graph turn without going through the HTTP layer.

Extracted from `src.api.routes` (plan 260820-1106-eval-harness-graph-cutover-restore,
phase 1). `_run_turn_via_graph` and its supporting cluster used to live in
`routes.py`, coupled to two module globals: the compiled graph app (via
`_get_graph_v2`) and the session-persistence policy (`registry` +
`_persistence_enabled`, read at import time). That coupling is exactly what
made the eval harness fragile across the graph cutover — restoring it here
means the harness can drive a turn without importing FastAPI at all.

Both globals are now parameters: `app` is caller-owned (the caller compiles
or looks up the graph), and `persist` is an injected callable that defaults
to `None` — "do not persist" is a structural guarantee, not a config read.
`routes.py` keeps thin wrappers over `run_turn` / `_persist_turn` /
`response_from_result` so its call sites are unchanged; eval passes its own
per-run app and no persist callable at all.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from src.agents.graph.phase_facts import phase_facts
from src.agents.graph.phase_keys import (
    PHASE_KEY_BY_NODE,
    STREAMING_NODES,
    SUBGRAPH_STREAMING_NODE,
)
from src.agents.graph.prompts import INTAKE_QA_NO_ANSWER_SENTINEL
from src.api.streaming import (
    collecting_trace,
    emit_delta,
    emit_phase,
    emit_reasoning,
    record_step,
)
from src.models.schemas import PlannerChatResponse
from src.services.llm import reasoning_text, response_text

logger = logging.getLogger(__name__)

#: `persist(session_id, app, config, thinking_trace)` — best-effort, called
#: only if not `None`. `None` means "eval mode": there is no code path from
#: `run_turn` to any session store.
PersistCallable = Callable[[str, Any, dict, list[dict[str, Any]] | None], None]
PersistScheduler = Callable[[Callable[[], None]], None]


def _fresh_turn_input(session_id: str, message: str, language: str, extra_state: dict | None = None) -> dict:
    return {
        "session_id": session_id,
        "language": language,
        # `at` is stamped here, once, because this is the moment the user
        # sent it. The transcript is re-written whole on every persist, so
        # a message that doesn't carry its own timestamp gets "now" on
        # every later turn and the conversation collapses to one instant.
        "messages": [
            HumanMessage(content=message, additional_kwargs={"at": datetime.now(UTC).isoformat()})
        ],
        **(extra_state or {}),
    }


def _task_result_update(chunk: dict) -> Any:
    """The dict a finished node returned, out of a `tasks` frame.

    LangGraph reports it as `result`, which is a sequence of (channel, value)
    writes rather than the dict the node handed back. `phase_facts` reads node
    return values, so the writes are folded back into one.
    """
    result = chunk.get("result")
    if isinstance(result, dict):
        return result
    if isinstance(result, (list, tuple)):
        merged: dict[str, Any] = {}
        for write in result:
            if isinstance(write, (list, tuple)) and len(write) == 2 and isinstance(write[0], str):
                merged[write[0]] = write[1]
        return merged
    return {}


class _DeclineGate:
    """Holds `intake_qa`'s opening tokens until they cannot be a decline.

    `intake_qa` streams as it writes, but whether the text is an answer at all
    is only settled once it is finished: the node replies with exactly
    `NO_ANSWER` when the message did not actually ask anything, and drops it.
    By then the tokens had already reached the user, so the sentinel appeared on
    screen and the turn then went quiet.

    Nothing is retracted here — an SSE stream has no way to unsay something, and
    the `reset` frame that once existed for exactly this was removed for exactly
    that reason (see `api/streaming.py`). Instead the opening tokens are held
    while they are still a prefix of the sentinel, and released the instant they
    diverge. A real answer is delayed by at most a few characters; a decline is
    never shown at all.

    Scoped to `intake_qa` because it is the only node with a sentinel. `qa_node`
    always answers, so gating it would delay every reply for nothing.
    """

    def __init__(self) -> None:
        self._held = ""
        self._open = False

    def feed(self, text: str) -> str:
        """What may be sent now — everything, once the gate has opened."""
        if self._open:
            return text
        if not text:
            return ""
        self._held += text
        probe = self._held.strip().upper()
        if probe and not INTAKE_QA_NO_ANSWER_SENTINEL.startswith(probe):
            self._open = True
            held, self._held = self._held, ""
            return held
        return ""

    def flush(self) -> str:
        """Whatever is still held when the stream ends.

        A buffer that never diverged is either the sentinel — dropped — or a
        short answer that happens to be a prefix of it, which must still be
        shown rather than swallowed along with the declines.
        """
        held, self._held = self._held, ""
        self._open = True
        if held.strip().upper() == INTAKE_QA_NO_ANSWER_SENTINEL:
            return ""
        return held


def _may_stream(namespace: tuple[str, ...] | None, node_name: str | None) -> bool:
    """Whether a `messages` chunk from this position may reach the user as `delta`.

    Two axes, because one is not enough. A plain node streams under the empty
    namespace and only has to be in `STREAMING_NODES`. A node that is a compiled
    subgraph — `qa_node` — streams under its own namespace, and being inside it
    is NOT sufficient: the agent's tokens are the reply, while the `tools` node
    beside it emits `ToolMessage` content that is real text and must never be
    shown (measured 2026-08-19; it was a tool error string).

    LangGraph namespaces a subgraph as `"<node>:<uuid>"`, so the node name is the
    part before the colon.
    """
    if not namespace:
        return node_name in STREAMING_NODES
    root = str(namespace[0]).split(":", 1)[0]
    return root in STREAMING_NODES and node_name == SUBGRAPH_STREAMING_NODE.get(root)


def _drive_turn(app, config: dict, turn_input, *, stream: bool) -> dict:
    """Run one turn and return its result dict, streaming or not.

    The two modes differ only here, which is the point: everything around this
    — building the input, the resume branch, interrupt handling, persistence,
    response assembly — is shared, so streaming and plain POST cannot answer
    the same message differently.

    `app.stream()` does not hand back a merged state the way `invoke()` does,
    so the final state is read from the checkpointer once the generator is
    drained. An interrupt arrives as an `__interrupt__` key in `updates` and is
    put back onto the result, giving both modes the same shape.

    Frames come from two stream modes at once:
    - `updates` names the node that just finished -> a `phase` frame, for the
      nodes worth reporting (`PHASE_KEY_BY_NODE`).
    - `messages` carries LLM tokens tagged with the node that produced them ->
      a `delta` frame, but only from `STREAMING_NODES`. That filter is the
      whole design: every other producer on this channel is either JSON
      (`extract_patch`, `supervisor`) or the finished reply itself (`respond`,
      which would otherwise be sent twice — once as deltas, once in `final`).
    """
    if not stream:
        return app.invoke(turn_input, config=config)

    interrupts: Any = None
    decline_gate = _DeclineGate()
    # `subgraphs=True` is what makes `qa_node` stream at all: it is a compiled
    # subgraph, and without this its tokens never surface — the drain saw one
    # finished message at the node boundary and the typewriter effect never ran
    # for the product's main answering node. It also changes the yielded shape
    # to (namespace, mode, chunk).
    for namespace, mode, chunk in app.stream(
        turn_input, config=config, stream_mode=["updates", "messages", "tasks"], subgraphs=True
    ):
        # Progress is a top-level concern: a phase key names a graph node, and a
        # subgraph's internal steps are not steps the user tracks.
        if mode in {"updates", "tasks"} and namespace:
            continue

        if mode == "tasks":
            # `updates` only fires once a node has FINISHED, so a UI built on it
            # can say "this step is done" and nothing else — it would spin on a
            # step that already ended while the one actually running stayed
            # unannounced. `tasks` reports both edges of every node.
            node_name = chunk.get("name")
            phase_key = PHASE_KEY_BY_NODE.get(str(node_name))
            if not phase_key:
                continue
            if "result" in chunk or "error" in chunk:
                facts = phase_facts(str(node_name), _task_result_update(chunk))
                emit_phase(phase_key, status="completed", **facts)
                # Only the completed edge is kept: the stored trace is what the
                # turn DID, and a step that opened carries nothing to describe.
                record_step(phase_key, facts)
            else:
                # No facts on the opening edge: the node has not returned yet,
                # and `input` is the state going in, not what this step found.
                emit_phase(phase_key, status="started")
        elif mode == "updates":
            # Kept solely for interrupts. Phase frames come from `tasks` now;
            # emitting here too would double every step.
            for node_name, update in chunk.items():
                if node_name == "__interrupt__":
                    interrupts = update
        elif mode == "messages":
            message_chunk, metadata = chunk
            node = metadata.get("langgraph_node")
            if _may_stream(namespace, node):
                text = response_text(message_chunk)
                if node == "intake_qa":
                    text = decline_gate.feed(text)
                emit_delta(text)
                # The reasoning frame names its own step: it is sent while the
                # node runs, whereas the node's `phase` frame lands only once it
                # finishes, so position in the stream cannot identify it.
                reasoning_key = PHASE_KEY_BY_NODE.get(
                    str(namespace[0]).split(":", 1)[0] if namespace else str(node)
                )
                if reasoning_key:
                    emit_reasoning(reasoning_text(message_chunk), reasoning_key)

    # A held-back opening that turned out to be a real answer still has to be
    # sent; one that was the sentinel is dropped here and never seen.
    emit_delta(decline_gate.flush())

    result = dict(app.get_state(config).values or {})
    if interrupts:
        result["__interrupt__"] = interrupts
    return result


def _persist_turn(
    session_id: str,
    app,
    config: dict,
    persist: PersistCallable | None,
    thinking_trace: list[dict[str, Any]] | None = None,
) -> None:
    """Write the turn's session row and transcript — best effort.

    `persist=None` (eval's default) means there is no code path to any
    session store at all — not "disabled by a setting", a guarantee that
    holds regardless of what `SESSION_PERSISTENCE_ENABLED` says.

    The reply is already computed by the time this runs, so a failure inside
    `persist` must cost a log line and nothing else; the same contract
    `supabase_persist_hook` held for the plane this replaces.
    """
    if persist is None:
        return
    try:
        persist(session_id, app, config, thinking_trace)
    except Exception:
        logger.exception("Unable to persist graph session %s; continuing in memory", session_id)


def run_turn(
    app,
    session_id: str,
    message: str,
    language: str,
    extra_state: dict | None = None,
    *,
    stream: bool = False,
    persist: PersistCallable | None = None,
    defer_persist: PersistScheduler | None = None,
) -> PlannerChatResponse:
    """Phase 7: a thread can be PAUSED at `interrupt()` (an ambiguous date --
    see `nodes/validate_patch.py`) from the previous turn. `get_state(...)
    .interrupts` is non-empty exactly then, and this turn's message must
    resume that paused node via `Command(resume=...)` rather than start a
    fresh turn -- which would re-run the pipeline from `load_context` and
    re-ask every slot already answered. A turn that itself pauses returns
    with `"__interrupt__"` in the result instead of `"response"` (`respond`
    never runs -- the graph stopped at `validate_patch`), so this builds the
    frozen response shape directly from the interrupt's own message.

    A resume reply that does NOT resolve the paused ambiguity (the user
    answered something else entirely, e.g. "thôi đổi điểm đến sang Huế"
    instead of naming a year) comes back with `unresolved_resume_text` set
    (see `nodes/validate_patch.py`) -- that text never reached
    `extract_patch` this turn (resuming re-executes only `validate_patch`,
    not the whole pipeline), so it is re-run here as one ordinary fresh
    turn. This is the fix for "a pending question isn't interruptible by a
    different intent" recreated one level down, inside the interrupt itself.

    `extra_state` (review finding F2) merges extra keys into this turn's
    `invoke()` input -- e.g. `selected_hotel_id` from `POST /hotels/select`,
    read deterministically by `hotel_node` rather than re-parsed out of the
    message text. Only applied on the fresh-turn path: a turn that resumes a
    paused `interrupt()` must resolve that ambiguity first, and threading a
    hotel pick through a resume is an edge case rare enough not to bother.

    `emit_phase("received")` (no-op on the plain POST path -- see
    `emit_phase`'s own no-emitter-bound guard) fires before anything else
    below: no graph_v2 node emits a `phase`/`delta` frame during an
    intake-stage turn (`extract_patch`'s LLM call is the graph's only slow
    step, and it is silent), so the client's `firstFrameTimeoutMs` (5s,
    `stream-client.ts`) previously had nothing to see but the filtered-out
    `: open` comment frame until `final` -- aborting the connection
    ("BodyStreamBuffer was aborted") on any turn whose extraction call ran
    past 5s, e.g. a compound "destination + dates + people + budget" message.
    """
    emit_phase("received")
    config = {"configurable": {"thread_id": session_id}}

    with collecting_trace() as trace:
        snapshot = app.get_state(config)
        if not snapshot.values:
            # Checkpoint TTL-evicted (SessionRegistry.evict_expired,
            # agents/session.py, default 2h idle) -- this thread's ONLY copy
            # of trip_data with the current (v3) schema. The itinerary/hotel
            # a guest already built are still durable in Supabase
            # (itineraries.session_id has no TTL), so recover it the same
            # way routes.py's restore_session does, rather than letting this
            # turn run as if the guest never built a trip at all (every tool
            # that reads trip_data from state -- modify_trip_plan included --
            # would otherwise report "Chưa có kế hoạch chuyến đi" for a trip
            # that, from the guest's chat transcript, plainly still exists).
            # extra_state is the existing "merge into this turn's input"
            # channel (selected_hotel_id from POST /hotels/select uses the
            # same one) -- reused here rather than adding a second path.
            # snapshot.interrupts is necessarily empty too when values is
            # empty, so this can't affect the resume branch below.
            #
            # Tries both durable copies (the itineraries table, then the
            # trip_data embedded in this session's own context_data) --
            # session_store.recover_trip_data's own doc comment has the
            # full story of why there are two, not one.
            from src.services import session_store

            recovered = session_store.recover_trip_data(session_id)
            if recovered:
                extra_state = {**(extra_state or {}), "trip_data": recovered}
        if snapshot.interrupts:
            result = _drive_turn(app, config, Command(resume=message), stream=stream)
            unresolved = result.get("unresolved_resume_text")
            if unresolved and "__interrupt__" not in result:
                result = _drive_turn(
                    app, config, _fresh_turn_input(session_id, unresolved, language, extra_state), stream=stream
                )
        else:
            result = _drive_turn(
                app, config, _fresh_turn_input(session_id, message, language, extra_state), stream=stream
            )

    # Before the interrupt branch below, so a turn that pauses waiting on a
    # clarification is persisted too — that exchange happened and must survive
    # a reload like any other.
    def persist_job() -> None:
        _persist_turn(session_id, app, config, persist, trace)

    if defer_persist is None:
        persist_job()
    else:
        defer_persist(persist_job)

    return response_from_result(session_id, result)


def response_from_result(session_id: str, result: dict) -> PlannerChatResponse:
    """Turn a graph result into the wire response.

    Shared by every graph entry point (`run_turn` and `routes.py`'s
    `change_hotel`/`_rerun_hotel_search`, which re-enter the graph via
    `Command(goto=...)` directly rather than through `run_turn`) rather than
    copied into each: a turn that stops at `interrupt()` returns
    `__interrupt__` in place of `response` — `respond` never ran — and two
    copies of that branch would drift the first time either entry point
    changed.
    """
    interrupts = result.get("__interrupt__")
    if interrupts:
        payload = interrupts[0].value or {}
        return PlannerChatResponse(session_id=session_id, reply=str(payload.get("message", "")), stage="intake")

    return PlannerChatResponse(**result["response"])
