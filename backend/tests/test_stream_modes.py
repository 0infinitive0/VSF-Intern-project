"""Streaming a turn through LangGraph's own stream modes.

No `delta` frame had ever been emitted on the graph plane: `_DeltaGate` was
the only producer and nothing constructed it, so the typewriter effect the
frontend implements never ran. `hotel_search` was in the same state — the
frontend waits for that phase to leave the intake panel, and nothing emitted
it, so a user who gave every fact in one sentence stayed on the intake screen
until `itinerary_build` fired, long after the hotels had been found.

The replacement filters by NODE, not by text prefix. That distinction is the
whole point: `_DeltaGate` guessed whether text was tool-call JSON by looking
at its first character, because the legacy plane had no idea which component
was talking. LangGraph does, so "is this streamable prose?" becomes a
structural fact instead of a heuristic.

`STREAMING_NODES` is a whitelist, not a blacklist: a node added later does not
stream until someone puts it in that set deliberately.
"""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

import src.agents.graph.graph as graph_module
import src.agents.graph.nodes.intake_qa as intake_qa_module
import src.agents.graph.nodes.qa_node as qa_node_module
import src.api.routes as routes
from src.agents.graph.phase_keys import PHASE_KEY_BY_NODE, STREAMING_NODES
from src.api.streaming import emitting_to
from src.domain.travel_state import TravelState, apply_patch


class _RecordingEmitter:
    """Stands in for `TurnEmitter` — same `emit(event, **data)` surface, no
    event loop needed."""

    def __init__(self) -> None:
        self.frames: list[tuple[str, dict[str, Any]]] = []

    def emit(self, event: str, **data: Any) -> None:
        self.frames.append((event, data))

    def of(self, event: str) -> list[dict[str, Any]]:
        return [data for name, data in self.frames if name == event]

    @property
    def delta_text(self) -> str:
        return "".join(str(frame.get("text", "")) for frame in self.of("delta"))

    def facts_for(self, key: str) -> list[dict[str, Any]]:
        return [
            {k: v for k, v in data.items() if k not in {"key", "at"}}
            for name, data in self.frames
            if name == "phase" and data.get("key") == key
        ]

    @property
    def phase_keys(self) -> list[str]:
        return [str(frame.get("key")) for frame in self.of("phase")]


class _ToolCapableFake(GenericFakeChatModel):
    """`create_react_agent` calls `bind_tools()`; the stock fake raises."""

    def bind_tools(self, *_args, **_kwargs):
        return self


def _fake_llm(text: str) -> _ToolCapableFake:
    return _ToolCapableFake(messages=iter([AIMessage(content=text)] * 50))


class _BlockStreamingFake(BaseChatModel):
    """A model that streams block-shaped `content`, one chunk per block.

    That is what the Responses API returns, and what any model langchain routes
    there returns — including ones nobody opted in: `_model_prefers_responses_api`
    switches on the model NAME (`gpt-5-pro`, anything containing `codex`), so a
    single env change is enough to reach this shape with no code change at all.

    `GenericFakeChatModel` cannot stand in here: its `_stream` raises
    `ValueError("Expected content to be a string")` on a list, which is the
    exact shape under test.
    """

    blocks: list[dict[str, Any]]

    @property
    def _llm_type(self) -> str:
        return "block-streaming-fake"

    def bind_tools(self, *_args, **_kwargs):
        return self

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        for block in self.blocks:
            yield ChatGenerationChunk(message=AIMessageChunk(content=[block]))

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content=list(self.blocks)))]
        )


def _fake_block_llm(blocks: list[dict[str, Any]]) -> _BlockStreamingFake:
    return _BlockStreamingFake(blocks=blocks)


def _travel_state(*, with_budget: bool) -> dict:
    changes: list[dict[str, Any]] = [
        {"path": "destination", "operation": "set", "value": "Đà Nẵng"},
        {"path": "people", "operation": "set", "value": 2},
        {"path": "dates.start", "operation": "set", "value": "2099-01-01"},
        {"path": "dates.end", "operation": "set", "value": "2099-01-05"},
    ]
    if with_budget:
        changes.append({"path": "budget.target", "operation": "set", "value": 1_000_000})
    return apply_patch(TravelState(), changes).state.to_dict()


@pytest.fixture
def streaming_turn(monkeypatch: pytest.MonkeyPatch):
    """Run one streaming turn and hand back the frames it produced."""

    def _run(
        *,
        message: str,
        thread: str,
        travel_state: dict,
        intent: str = "general_question",
        patch: list[dict[str, Any]] | None = None,
        force_worker: str | None = None,
        extractor=None,
        intake_llm=None,
        qa_llm=None,
    ) -> _RecordingEmitter:
        # `intake_llm` is a parameter rather than something a test monkeypatches
        # itself: this fixture patches inside `_run`, which executes AFTER the
        # test body, so a patch set in the body would be silently overwritten
        # here and the test would pass against the default model instead.
        intake_model = intake_llm or _fake_llm("Tháng 7 hay mưa rải rác.")
        monkeypatch.setattr(intake_qa_module, "get_fast_llm", lambda **_k: intake_model)
        qa_model = qa_llm or _fake_llm("Có hồ bơi ngoài trời.")
        monkeypatch.setattr(qa_node_module, "get_fast_llm", lambda **_k: qa_model)
        monkeypatch.setattr(
            graph_module,
            "extract_patch",
            extractor or (lambda _s: {"patch": patch or [], "intent": intent}),
        )
        if force_worker:
            monkeypatch.setattr(
                graph_module,
                "supervisor",
                lambda _s: {
                    "next_worker": force_worker,
                    "pending_tasks": [force_worker],
                    "task_description": "probe",
                    "routing_source": "forced",
                    "routing_reasoning": "test",
                },
            )

        app = graph_module.build_graph()
        monkeypatch.setattr(routes, "_get_graph_v2", lambda: app)
        monkeypatch.setattr(routes, "_persistence_enabled", False)

        emitter = _RecordingEmitter()
        with emitting_to(emitter):  # type: ignore[arg-type]
            routes._run_turn_via_graph(
                thread, message, "vi", extra_state={"travel_state": travel_state}, stream=True
            )
        return emitter

    return _run


class TestDeltaFrames:
    def test_an_intake_question_streams_its_answer(self, streaming_turn):
        emitter = streaming_turn(
            message="Đà Nẵng tháng 7 thời tiết thế nào?",
            thread="stream-intake-qa",
            travel_state=_travel_state(with_budget=False),
        )

        assert emitter.of("delta"), "no delta frame — the typewriter effect is still dead"
        assert "mưa" in emitter.delta_text

    def test_a_qa_turn_streams_its_answer(self, streaming_turn):
        emitter = streaming_turn(
            message="khách sạn này có hồ bơi không?",
            thread="stream-qa-node",
            travel_state=_travel_state(with_budget=True),
            force_worker="qa_node",
        )

        assert emitter.of("delta")
        assert "hồ bơi" in emitter.delta_text


class TestBlockShapedContent:
    """Deltas must survive a model that answers in content blocks.

    The guard this replaces asked `isinstance(content, str)` and emitted
    nothing when the answer was False. Nothing raised, nothing logged, and the
    user watched an empty screen for the whole turn — the worst shape a bug can
    take, because no test and no alert could see it.

    `intake_qa` itself already handles this shape (`_response_text`), so the
    turn still produced a correct reply — only the streamed copy vanished.
    That asymmetry is why the plain POST endpoint would have looked healthy.
    """

    def test_a_block_shaped_answer_still_reaches_the_client(self, streaming_turn):
        emitter = streaming_turn(
            message="Đà Nẵng tháng 7 thời tiết thế nào?",
            thread="stream-block-content",
            travel_state=_travel_state(with_budget=False),
            intake_llm=_fake_block_llm([{"type": "text", "text": "Tháng 7 hay mưa rải rác."}]),
        )

        assert emitter.of("delta"), "block-shaped content was swallowed silently"
        assert "mưa" in emitter.delta_text

    def test_whitespace_survives_the_join(self, streaming_turn):
        """Text arrives split across blocks; joining them must not eat the
        spaces that separate words."""
        emitter = streaming_turn(
            message="Đà Nẵng tháng 7 thời tiết thế nào?",
            thread="stream-block-whitespace",
            travel_state=_travel_state(with_budget=False),
            intake_llm=_fake_block_llm(
                [{"type": "text", "text": "Tháng 7 "}, {"type": "text", "text": "hay mưa."}]
            ),
        )

        assert "Tháng 7 hay mưa." in emitter.delta_text

    def test_a_non_text_block_emits_no_delta(self, streaming_turn):
        """A reasoning block is not the answer, and must not be streamed as
        one. Phase 4 of plan 260819-0931 gives it its own frame; until then it
        is dropped rather than shown as the reply."""
        emitter = streaming_turn(
            message="Đà Nẵng tháng 7 thời tiết thế nào?",
            thread="stream-block-reasoning-only",
            travel_state=_travel_state(with_budget=False),
            intake_llm=_fake_block_llm(
                [{"type": "reasoning", "reasoning": "Đang cân nhắc thời tiết…"}]
            ),
        )

        assert "cân nhắc" not in emitter.delta_text


class TestReasoningFrames:
    """Reasoning summaries ride their own SSE event, never `delta`.

    The contract makes `delta` a prefix of the reply `final` carries; a summary
    of the model's own reasoning is not part of the reply, and it is always
    English even in a Vietnamese conversation. Folding it into `delta` would
    break the first invariant and hide the second from clients.
    """

    def test_a_reasoning_block_is_emitted_on_its_own_event(self, streaming_turn):
        emitter = streaming_turn(
            message="Đà Nẵng tháng 7 thời tiết thế nào?",
            thread="stream-reasoning-frame",
            travel_state=_travel_state(with_budget=False),
            intake_llm=_fake_block_llm(
                [
                    {"type": "reasoning", "reasoning": "Checking the rainy season"},
                    {"type": "text", "text": "Tháng 7 hay mưa rải rác."},
                ]
            ),
        )

        assert [f["text"] for f in emitter.of("reasoning")] == ["Checking the rainy season"]
        assert "mưa" in emitter.delta_text

    def test_reasoning_never_leaks_into_delta(self, streaming_turn):
        emitter = streaming_turn(
            message="Đà Nẵng tháng 7 thời tiết thế nào?",
            thread="stream-reasoning-not-delta",
            travel_state=_travel_state(with_budget=False),
            intake_llm=_fake_block_llm(
                [
                    {"type": "reasoning", "reasoning": "Checking the rainy season"},
                    {"type": "text", "text": "Tháng 7 hay mưa rải rác."},
                ]
            ),
        )

        assert "Checking" not in emitter.delta_text

    def test_a_turn_with_no_reasoning_emits_no_reasoning_frame(self, streaming_turn):
        """The common case, not an edge one: a model summarizes its reasoning only
        when it actually reasons, and a tool-calling step never does."""
        emitter = streaming_turn(
            message="Đà Nẵng tháng 7 thời tiết thế nào?",
            thread="stream-reasoning-absent",
            travel_state=_travel_state(with_budget=False),
        )

        assert emitter.of("reasoning") == []
        assert emitter.of("delta")

    def test_the_reply_never_carries_the_reasoning_text(self, streaming_turn):
        """`final.reply` is built from graph state rather than from chunks, so
        this holds structurally — but it is the invariant that matters most, so
        it is locked rather than argued."""
        emitter = streaming_turn(
            message="Đà Nẵng tháng 7 thời tiết thế nào?",
            thread="stream-reasoning-not-in-reply",
            travel_state=_travel_state(with_budget=False),
            intake_llm=_fake_block_llm(
                [
                    {"type": "reasoning", "reasoning": "Checking the rainy season"},
                    {"type": "text", "text": "Tháng 7 hay mưa rải rác."},
                ]
            ),
        )

        assert emitter.of("reasoning")  # guard: the fixture really produced one
        replies = [f.get("reply", "") for f in emitter.of("final")]
        assert not any("Checking" in str(r) for r in replies)


class TestWhatMustNeverStream:
    def test_the_extractors_json_never_reaches_the_client(self, streaming_turn):
        """`extract_patch` emits JSON. Streaming it would show the user the
        machinery — this is a security/UX requirement, not a nicety. The
        whitelist makes it structural: `extract_patch` is not in it."""
        json_text = '{"intent": "update_trip", "changes": [{"path": "destination"}]}'

        def _extractor_that_talks(_state):
            # Speaks through a real LLM call, exactly as the node does — so the
            # tokens genuinely pass through the `messages` stream.
            intake_qa_module.get_fast_llm(temperature=0).invoke(json_text)
            return {"patch": [], "intent": "general_question"}

        emitter = streaming_turn(
            message="đi đà nẵng 4 ngày",
            thread="stream-no-extractor-json",
            travel_state=_travel_state(with_budget=True),
            extractor=_extractor_that_talks,
        )

        assert "{" not in emitter.delta_text
        assert "intent" not in emitter.delta_text

    def test_the_final_reply_is_not_also_streamed_as_deltas(self, streaming_turn):
        """`respond` writes its reply into the same `messages` channel, so an
        unfiltered stream would send the whole answer twice — once as deltas,
        once inside `final`."""
        emitter = streaming_turn(
            message="khách sạn này có hồ bơi không?",
            thread="stream-no-double-reply",
            travel_state=_travel_state(with_budget=True),
            force_worker="qa_node",
        )

        # `respond` re-sends qa_node's answer as the turn's reply; the streamed
        # text must be that answer exactly once, not twice.
        assert emitter.delta_text.count("Có hồ bơi ngoài trời.") <= 1


class TestPhaseFrames:
    def test_hotel_search_is_emitted_so_the_ui_can_leave_the_intake_panel(self, streaming_turn):
        emitter = streaming_turn(
            message="tìm khách sạn",
            thread="stream-hotel-phase",
            travel_state=_travel_state(with_budget=True),
            force_worker="hotel_node",
        )

        assert "hotel_search" in emitter.phase_keys

    def test_the_turn_still_opens_with_received(self, streaming_turn):
        emitter = streaming_turn(
            message="xin chào",
            thread="stream-received",
            travel_state=_travel_state(with_budget=True),
        )

        assert emitter.phase_keys[0] == "received"

    def test_phases_come_from_nodes_that_actually_ran(self, streaming_turn):
        emitter = streaming_turn(
            message="Đà Nẵng tháng 7 thời tiết thế nào?",
            thread="stream-real-phases",
            travel_state=_travel_state(with_budget=False),
        )

        assert "intake_check" in emitter.phase_keys  # extract_patch
        assert "generating" in emitter.phase_keys  # intake_qa


class TestPhaseFacts:
    """Progress frames carry the turn's real numbers, and only those."""

    def test_intake_check_reports_the_intent_and_the_fields_touched(self, streaming_turn):
        emitter = streaming_turn(
            message="đổi thành 3 người",
            thread="stream-facts-intake",
            travel_state=_travel_state(with_budget=True),
            patch=[{"path": "people", "operation": "set", "value": 3}],
            intent="update_trip",
        )

        assert emitter.facts_for("intake_check") == [
            {"status": "started"},
            {"status": "completed", "intent": "update_trip", "fields": ["people"]},
        ]

    def test_a_field_value_never_rides_along_with_its_path(self, streaming_turn):
        emitter = streaming_turn(
            message="ngân sách 8 triệu",
            thread="stream-facts-no-values",
            travel_state=_travel_state(with_budget=True),
            patch=[{"path": "budget.target", "operation": "set", "value": 8_000_000}],
            intent="update_trip",
        )

        assert "8000000" not in str(emitter.facts_for("intake_check"))

    def test_routing_reports_the_worker_but_not_the_prose_beside_it(self, streaming_turn):
        emitter = streaming_turn(
            message="tìm khách sạn",
            thread="stream-facts-routing",
            travel_state=_travel_state(with_budget=True),
            force_worker="hotel_node",
        )

        facts = emitter.facts_for("routing")
        assert {"status": "completed", "worker": "hotel_node"} in facts
        # `task_description` sits in the same update dict and is written by the LLM.
        assert "probe" not in str(facts)

    def test_hotel_search_is_emitted_exactly_once(self, streaming_turn):
        """`hotel_node` emits its own richer frame from inside `_result`, so it is
        absent from `PHASE_KEY_BY_NODE`. Mapping it as well would list the same
        step twice for the user — the frontend keys rows by `${key}-${at}`."""
        emitter = streaming_turn(
            message="tìm khách sạn",
            thread="stream-facts-hotel-once",
            travel_state=_travel_state(with_budget=True),
            force_worker="hotel_node",
        )

        # `hotel_node` is absent from PHASE_KEY_BY_NODE, so the only frame is
        # the one the node emits itself — no started/completed pair from `tasks`.
        assert emitter.phase_keys.count("hotel_search") == 1

    def test_a_phase_with_no_facts_still_sends_its_key(self, streaming_turn):
        """`compacting_history` has no facts to report; the step still happened."""
        emitter = streaming_turn(
            message="xin chào",
            thread="stream-facts-bare",
            travel_state=_travel_state(with_budget=True),
        )

        assert "compacting_history" in emitter.phase_keys
        assert emitter.facts_for("compacting_history") == [
            {"status": "started"},
            {"status": "completed"},
        ]


class TestStepEdges:
    """Every mapped node reports both edges: it started, and it finished.

    `updates` only fires on completion, so a client built on it could spin on a
    step that had already ended while the one actually running went unannounced.
    """

    def test_a_step_reports_started_before_completed(self, streaming_turn):
        emitter = streaming_turn(
            message="Đà Nẵng tháng 7 thời tiết thế nào?",
            thread="stream-step-edges",
            travel_state=_travel_state(with_budget=False),
        )

        statuses = [f.get("status") for f in emitter.facts_for("intake_check")]
        assert statuses == ["started", "completed"]

    def test_the_answering_step_opens_before_its_tokens_flow(self, streaming_turn):
        """The point of the whole change: `generating` used to arrive AFTER the
        reply had finished streaming, so the step the user was watching could
        never be the one producing the text."""
        emitter = streaming_turn(
            message="Đà Nẵng tháng 7 thời tiết thế nào?",
            thread="stream-generating-opens-first",
            travel_state=_travel_state(with_budget=False),
        )

        order = [
            name if name != "phase" else f"phase:{data['key']}:{data.get('status')}"
            for name, data in emitter.frames
        ]
        assert order.index("phase:generating:started") < order.index("delta")
        assert order.index("delta") < order.index("phase:generating:completed")

    def test_facts_ride_the_completed_edge_only(self, streaming_turn):
        """A node that has not returned yet has reported nothing to describe."""
        emitter = streaming_turn(
            message="đổi thành 3 người",
            thread="stream-facts-on-completion",
            travel_state=_travel_state(with_budget=True),
            patch=[{"path": "people", "operation": "set", "value": 3}],
            intent="update_trip",
        )

        started, completed = emitter.facts_for("intake_check")
        assert started == {"status": "started"}
        assert completed["intent"] == "update_trip"


class TestTheDeclineSentinelNeverReachesTheUser:
    """`intake_qa` answers with exactly `NO_ANSWER` when the message did not ask
    anything, and the node then drops it — but it streams as it writes, so the
    sentinel had already appeared on screen before the node decided.

    Reported from a real session. The stream cannot unsay it, so the opening
    tokens are held until they cannot be the sentinel.
    """

    def test_a_declined_turn_streams_nothing(self, streaming_turn):
        emitter = streaming_turn(
            message="ok",
            thread="stream-decline-hidden",
            travel_state=_travel_state(with_budget=False),
            intake_llm=_fake_llm("NO_ANSWER"),
        )

        assert emitter.delta_text == ""
        assert "NO_ANSWER" not in str(emitter.frames)

    def test_a_real_answer_is_delayed_but_never_lost(self, streaming_turn):
        emitter = streaming_turn(
            message="Đà Nẵng tháng 7 thời tiết thế nào?",
            thread="stream-decline-real-answer",
            travel_state=_travel_state(with_budget=False),
            intake_llm=_fake_llm("Tháng 7 hay mưa rải rác."),
        )

        assert emitter.delta_text == "Tháng 7 hay mưa rải rác."

    def test_an_answer_that_merely_starts_like_the_sentinel_still_arrives(self, streaming_turn):
        """"No" is a prefix of NO_ANSWER, so it is held — and must be released
        when the stream ends rather than swallowed with the declines."""
        emitter = streaming_turn(
            message="có mưa không?",
            thread="stream-decline-prefix",
            travel_state=_travel_state(with_budget=False),
            intake_llm=_fake_llm("No"),
        )

        assert emitter.delta_text == "No"


class TestMappingIntegrity:
    def test_every_streaming_node_is_a_real_graph_node(self):
        assert STREAMING_NODES <= set(graph_module.build_graph().nodes)

    def test_every_mapped_node_is_a_real_graph_node(self):
        assert set(PHASE_KEY_BY_NODE) <= set(graph_module.build_graph().nodes)

    def test_every_phase_key_exists_in_the_frontend_union(self):
        """A key the frontend has no label for renders as a blank progress row."""
        import re
        from pathlib import Path

        # `PhaseKey` is one of the few types still hand-written on the frontend:
        # FastAPI describes the stream endpoint's response as a stream, not its
        # frame shapes, so codegen cannot reach it.
        types_ts = Path(__file__).resolve().parents[2] / "frontend" / "src" / "types" / "index.ts"
        block = re.search(r"export type PhaseKey =(.*?)\n\n", types_ts.read_text(), re.S)
        assert block, "could not find the PhaseKey union in types/index.ts"
        frontend_keys = set(re.findall(r"'([a-z_]+)'", block.group(1)))

        emitted = set(PHASE_KEY_BY_NODE.values()) | {"received"}
        assert emitted <= frontend_keys, f"backend emits keys the frontend cannot label: {emitted - frontend_keys}"


class TestBlockingPathUnchanged:
    def test_a_plain_post_turn_emits_nothing_and_still_answers(self, streaming_turn, monkeypatch):
        """The non-streaming endpoint shares this code path; binding no emitter
        must leave it silent rather than erroring."""
        monkeypatch.setattr(
            intake_qa_module, "get_fast_llm", lambda **_k: _fake_llm("Tháng 7 hay mưa rải rác.")
        )
        monkeypatch.setattr(graph_module, "extract_patch", lambda _s: {"patch": [], "intent": "general_question"})
        app = graph_module.build_graph()
        monkeypatch.setattr(routes, "_get_graph_v2", lambda: app)
        monkeypatch.setattr(routes, "_persistence_enabled", False)

        response = routes._run_turn_via_graph(
            "stream-plain-post",
            "xin chào",
            "vi",
            extra_state={"travel_state": _travel_state(with_budget=True)},
        )

        assert response.reply


class TestQaNodeStreamsTokenByToken:
    """`qa_node` is a compiled subgraph, so its tokens only surface when the
    drain streams with `subgraphs=True`.

    Before that, the drain saw a single finished `AIMessage` at the node
    boundary: one `delta` frame carrying the whole answer, for the node that
    writes most of what a user reads. Nothing failed — `intake_qa`, a plain
    node, streamed normally — so only a frame COUNT catches it. Asserting that
    deltas merely exist is what let it survive.
    """

    def test_the_answer_arrives_across_many_frames_not_one(self, streaming_turn):
        emitter = streaming_turn(
            message="khách sạn này có hồ bơi không?",
            thread="stream-qa-token-by-token",
            travel_state=_travel_state(with_budget=True),
            force_worker="qa_node",
            qa_llm=_fake_block_llm(
                [{"type": "text", "text": tok} for tok in ["Có ", "hồ ", "bơi ", "ngoài ", "trời."]]
            ),
        )

        assert len(emitter.of("delta")) > 1, "qa_node is back to one bulk frame"
        assert emitter.delta_text == "Có hồ bơi ngoài trời."


class TestToolOutputNeverStreams:
    """The `tools` node lives inside qa_node's subgraph, and `subgraphs=True`
    exposes it alongside the agent.

    Its `ToolMessage` content is real text — measured 2026-08-19, a tool error
    string — so a filter that allowed the subgraph by name would have handed
    that to the user. Membership is by (subgraph, inner node) for this reason.
    """

    def test_a_tool_message_is_not_part_of_the_reply(self):
        from src.agents.graph.turn_runner import _may_stream

        assert _may_stream(("qa_node:abc-123",), "agent") is True
        assert _may_stream(("qa_node:abc-123",), "tools") is False

    def test_a_subgraph_the_whitelist_does_not_name_streams_nothing(self):
        from src.agents.graph.turn_runner import _may_stream

        assert _may_stream(("itinerary_node:xyz",), "agent") is False

    def test_a_plain_node_is_matched_by_name_alone(self):
        from src.agents.graph.turn_runner import _may_stream

        assert _may_stream((), "intake_qa") is True
        assert _may_stream(None, "respond") is False


