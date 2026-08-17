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
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage

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

    @property
    def phase_keys(self) -> list[str]:
        return [str(frame.get("key")) for frame in self.of("phase")]


class _ToolCapableFake(GenericFakeChatModel):
    """`create_react_agent` calls `bind_tools()`; the stock fake raises."""

    def bind_tools(self, *_args, **_kwargs):
        return self


def _fake_llm(text: str) -> _ToolCapableFake:
    return _ToolCapableFake(messages=iter([AIMessage(content=text)] * 50))


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
    ) -> _RecordingEmitter:
        monkeypatch.setattr(
            intake_qa_module, "get_fast_llm", lambda **_k: _fake_llm("Tháng 7 hay mưa rải rác.")
        )
        monkeypatch.setattr(
            qa_node_module, "get_fast_llm", lambda **_k: _fake_llm("Có hồ bơi ngoài trời.")
        )
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
