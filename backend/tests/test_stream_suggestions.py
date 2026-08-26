"""Phase 2 of plan 260819-1554-llm-grounded-chat-suggestions: the SSE
`suggestions` frame that `_run_stream_turn` emits AFTER `final`.

Same fixture shape as `test_stream_modes.py`'s `streaming_turn`: a compiled
graph, a `_RecordingEmitter` bound via `emitting_to`, and node functions
monkeypatched on `graph_module` before `build_graph()` runs (so the compiled
graph closes over the patched names). `_run_stream_turn` is driven directly
rather than through the FastAPI endpoint -- it is the whole worker-thread
body `planner_chat_stream` hands to `run_in_executor`, extracted to a
top-level function for exactly this reason.
"""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

import src.agents.graph.graph as graph_module
import src.agents.graph.nodes.qa_node as qa_node_module
import src.agents.session as session_module
import src.api.routes as routes
import src.services.suggestions as suggestions_module
from src.domain.travel_state import TravelState, apply_patch


class _RecordingEmitter:
    """Stands in for `TurnEmitter` -- same `emit(event, **data)` surface plus
    `close()`, no event loop needed."""

    def __init__(self) -> None:
        self.frames: list[tuple[str, dict[str, Any]]] = []
        self.closed = False

    def emit(self, event: str, **data: Any) -> None:
        self.frames.append((event, data))

    def close(self) -> None:
        self.closed = True

    @property
    def event_names(self) -> list[str]:
        return [name for name, _data in self.frames]

    def of(self, event: str) -> list[dict[str, Any]]:
        return [data for name, data in self.frames if name == event]


class _ToolCapableFake(GenericFakeChatModel):
    """`create_react_agent` calls `bind_tools()`; the stock fake raises."""

    def bind_tools(self, *_args, **_kwargs):
        return self


def _fake_llm(text: str) -> _ToolCapableFake:
    return _ToolCapableFake(messages=iter([AIMessage(content=text)] * 50))


def _travel_state() -> dict:
    changes = [
        {"path": "destination", "operation": "set", "value": "Đà Nẵng"},
        {"path": "people", "operation": "set", "value": 2},
        {"path": "dates.start", "operation": "set", "value": "2099-01-01"},
        {"path": "dates.end", "operation": "set", "value": "2099-01-05"},
        {"path": "budget.target", "operation": "set", "value": 1_000_000},
        {"path": "preferences.themes", "operation": "set", "value": None},
    ]
    return apply_patch(TravelState(), changes).state.to_dict()


def _stub_hotel_node_ok(_state):
    return {
        "pending_tasks": [],
        "task_results": [
            {
                "worker": "hotel_node",
                "status": "ok",
                "reply": "Đây là 2 khách sạn phù hợp.",
                "hotel_search_result": {
                    "options": [
                        {"name": "Khách sạn A", "average_nightly_price": 800000, "review_score": 8.5},
                        {"name": "Khách sạn B", "average_nightly_price": 1200000, "review_score": 9.1},
                    ],
                    "active_preferences": [],
                },
            }
        ],
    }


@pytest.fixture
def run_stream_turn(monkeypatch: pytest.MonkeyPatch):
    """Run one `_run_stream_turn` call and hand back the recording emitter."""

    def _run(
        *,
        thread: str,
        message: str = "tìm khách sạn",
        force_worker: str | None = None,
        hotel_node_stub=None,
        suggestions_result=None,
        suggestions_exc: Exception | None = None,
    ) -> _RecordingEmitter:
        monkeypatch.setattr(
            graph_module, "extract_patch", lambda _s: {"patch": [], "intent": "general_question"}
        )
        if hotel_node_stub is not None:
            monkeypatch.setattr(graph_module, "hotel_node", hotel_node_stub)
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
        if force_worker == "qa_node":
            monkeypatch.setattr(
                qa_node_module, "get_fast_llm", lambda **_k: _fake_llm("Có hồ bơi ngoài trời.")
            )

        app = graph_module.build_graph()
        monkeypatch.setattr(routes, "_get_graph_v2", lambda: app)
        monkeypatch.setattr(routes, "_persistence_enabled", False)

        if suggestions_exc is not None:
            def _raise(_context):
                raise suggestions_exc

            monkeypatch.setattr(routes, "generate_next_chat_suggestions", _raise)
        elif suggestions_result is not None:
            monkeypatch.setattr(
                routes, "generate_next_chat_suggestions", lambda _context: suggestions_result
            )
        else:
            def _unreachable(_context):
                raise AssertionError("generate_next_chat_suggestions must not be called for this turn")

            monkeypatch.setattr(routes, "generate_next_chat_suggestions", _unreachable)

        emitter = _RecordingEmitter()
        session = session_module.TripSession(thread, {})
        routes._run_stream_turn(
            session,
            thread,
            message,
            "vi",
            emitter,
            extra_state={"travel_state": _travel_state()},
        )
        return emitter

    return _run


def test_a_hotel_turn_emits_final_then_suggestions_in_order(run_stream_turn):
    emitter = run_stream_turn(
        thread="suggest-order",
        force_worker="hotel_node",
        hotel_node_stub=_stub_hotel_node_ok,
        suggestions_result=["Lọc khách sạn có điểm đánh giá trên 9", "Xem chi tiết Khách sạn B"],
    )

    names = emitter.event_names
    assert "final" in names and "suggestions" in names
    assert names.index("final") < names.index("suggestions")
    assert names[-1] == "suggestions"

    frame = emitter.of("suggestions")[0]
    assert frame["suggestions"] == [
        {"label": "Lọc khách sạn có điểm đánh giá trên 9", "value": "Lọc khách sạn có điểm đánh giá trên 9"},
        {"label": "Xem chi tiết Khách sạn B", "value": "Xem chi tiết Khách sạn B"},
    ]


def test_an_empty_suggestions_result_emits_no_frame(run_stream_turn):
    emitter = run_stream_turn(
        thread="suggest-empty",
        force_worker="hotel_node",
        hotel_node_stub=_stub_hotel_node_ok,
        suggestions_result=[],
    )

    assert "final" in emitter.event_names
    assert emitter.of("suggestions") == []


def test_a_qa_node_turn_never_calls_the_suggestion_llm(run_stream_turn):
    """`qa_node` writes no `task_results` entry, so `last_worker_from_task_results`
    is `None` and `_suggestion_context` returns `None` before any LLM call."""
    emitter = run_stream_turn(thread="suggest-qa-skip", message="khách sạn này có hồ bơi không?", force_worker="qa_node")

    assert "final" in emitter.event_names
    assert emitter.of("suggestions") == []


def test_suggestion_generation_failure_does_not_break_the_stream(run_stream_turn):
    emitter = run_stream_turn(
        thread="suggest-llm-broken",
        force_worker="hotel_node",
        hotel_node_stub=_stub_hotel_node_ok,
        suggestions_exc=RuntimeError("boom"),
    )

    assert "final" in emitter.event_names
    assert emitter.of("suggestions") == []
    assert emitter.of("error") == []
    assert emitter.closed


def test_the_plain_post_endpoint_always_returns_empty_suggestions(monkeypatch):
    """`respond` sets `suggestions: []` unconditionally now (Phase 2 rewrite) --
    the non-streaming path never runs the SSE suggestion worker at all."""
    monkeypatch.setattr(
        graph_module, "extract_patch", lambda _s: {"patch": [], "intent": "general_question"}
    )
    app = graph_module.build_graph()
    monkeypatch.setattr(routes, "_get_graph_v2", lambda: app)
    monkeypatch.setattr(routes, "_persistence_enabled", False)

    response = routes._run_turn_via_graph(
        "suggest-plain-post",
        "xin chào",
        "vi",
        extra_state={"travel_state": _travel_state()},
    )

    assert response.suggestions == []


# ── `_suggestion_context` unit coverage ──────────────────────────────────
# The tests above only prove the emit wiring (they monkeypatch
# `generate_next_chat_suggestions` itself); these exercise the gating and
# field-mapping logic of `_suggestion_context` directly, with a fake graph
# app standing in for `app.get_state(config).values`.


class _FakeStateSnapshot:
    def __init__(self, values: dict) -> None:
        self.values = values


class _FakeApp:
    def __init__(self, values: dict) -> None:
        self._values = values

    def get_state(self, _config):
        return _FakeStateSnapshot(self._values)


def _response(**overrides) -> routes.PlannerChatResponse:
    base: dict[str, Any] = dict(
        session_id="s1",
        reply="Đây là 2 khách sạn phù hợp.",
        stage="hotel_options",
        hotel_options=[
            {"index": 1, "id": "h1", "name": "Khách sạn A", "average_nightly_price": 800000, "review_score": 8.5},
            {"index": 2, "id": "h2", "name": "Khách sạn B", "average_nightly_price": 1200000, "review_score": 9.1},
        ],
        hotel_amenities=[
            {"id": "pool", "label_vi": "Hồ bơi", "label_en": "Pool", "category": "leisure"},
        ],
        active_preferences=[{"id": "pool", "label": "Hồ bơi"}],
        trip_plan=None,
        intake={"destination": "Đà Nẵng"},
    )
    base.update(overrides)
    return routes.PlannerChatResponse(**base)


def _state(worker: str | None, status: str = "ok", *, language: str = "vi") -> dict:
    task_results = [{"worker": worker, "status": status}] if worker else []
    return {"task_results": task_results, "language": language}


class TestSuggestionContext:
    def test_none_when_no_worker_ran(self):
        assert routes._suggestion_context(_FakeApp(_state(None)), {}, _response()) is None

    def test_none_when_worker_is_not_gated(self):
        """`scope_guard`/`qa_node` are not in `_SUGGESTION_WORKERS`."""
        app = _FakeApp(_state("scope_guard", "blocked"))
        assert routes._suggestion_context(app, {}, _response()) is None

    def test_none_when_status_is_in_skip_statuses(self):
        for status in ("no_destination", "unknown_destination", "error", "partial_error", "declined", "blocked"):
            app = _FakeApp(_state("hotel_node", status))
            assert routes._suggestion_context(app, {}, _response()) is None, status

    def test_none_when_hotel_selection_failed_or_already_paid(self):
        """These carry no usable new grounding (failed pick / locked choice) --
        added after code review flagged their absence from the original skip
        list."""
        for status in ("hotel_selection_failed", "already_paid"):
            app = _FakeApp(_state("hotel_node", status))
            assert routes._suggestion_context(app, {}, _response()) is None, status

    def test_a_business_outcome_status_is_not_skipped(self):
        """`over_budget`/`no_results` still have real destination/dates/filters
        to ground a chip in -- validation decision #6 is about missing data,
        not about the worker's business verdict."""
        app = _FakeApp(_state("budget_check", "over_budget"))
        ctx = routes._suggestion_context(app, {}, _response(stage="planned"))
        assert ctx is not None
        assert ctx.status == "over_budget"

    def test_itinerary_node_and_budget_check_are_gated_in(self):
        for worker in ("itinerary_node", "budget_check"):
            app = _FakeApp(_state(worker, "ok"))
            assert routes._suggestion_context(app, {}, _response()) is not None, worker

    def test_hotel_card_fields_are_mapped_from_response(self):
        app = _FakeApp(_state("hotel_node", "ok"))
        ctx = routes._suggestion_context(app, {}, _response())

        assert ctx is not None
        assert ctx.hotel_cards == (
            suggestions_module.SuggestionHotelCard(name="Khách sạn A", price=800000, review_score=8.5),
            suggestions_module.SuggestionHotelCard(name="Khách sạn B", price=1200000, review_score=9.1),
        )
        assert ctx.destination == "Đà Nẵng"
        assert ctx.active_filter_labels == ("Hồ bơi",)

    def test_vietnamese_language_uses_label_vi_for_amenities(self):
        app = _FakeApp(_state("hotel_node", "ok", language="vi"))
        ctx = routes._suggestion_context(app, {}, _response())
        assert ctx is not None
        assert ctx.hotel_amenity_labels == ("Hồ bơi",)
        assert ctx.language == "vi"

    def test_english_language_uses_label_en_for_amenities(self):
        app = _FakeApp(_state("hotel_node", "ok", language="en"))
        ctx = routes._suggestion_context(app, {}, _response())
        assert ctx is not None
        assert ctx.hotel_amenity_labels == ("Pool",)
        assert ctx.language == "en"

    def test_trip_duration_comes_from_trip_plan(self):
        app = _FakeApp(_state("itinerary_node", "ok"))
        response = _response(
            trip_plan={"status": "Draft", "duration_days": 4, "budget_currency": "VND"},
            hotel_options=[],
            hotel_amenities=[],
        )
        ctx = routes._suggestion_context(app, {}, response)
        assert ctx is not None
        assert ctx.trip_duration_days == 4

    def test_trip_duration_is_none_without_a_trip_plan(self):
        app = _FakeApp(_state("budget_check", "ok"))
        ctx = routes._suggestion_context(app, {}, _response(trip_plan=None))
        assert ctx is not None
        assert ctx.trip_duration_days is None

    def test_itinerary_days_are_mapped_from_the_trip_plan(self):
        app = _FakeApp(_state("itinerary_node", "ok"))
        response = _response(
            trip_plan={
                "status": "Draft",
                "duration_days": 2,
                "budget_currency": "VND",
                "days": [
                    {
                        "day_number": 1,
                        "theme": "Khám phá trung tâm",
                        "items": [
                            {"order_index": 0, "activity": "Tham quan Cầu Rồng"},
                            {"order_index": 1, "activity": "Ăn tối"},
                        ],
                    },
                    {
                        "day_number": 2,
                        "theme": "Biển",
                        "items": [{"order_index": 0, "activity": "Tắm biển Mỹ Khê"}],
                    },
                ],
            },
            hotel_options=[],
            hotel_amenities=[],
        )

        ctx = routes._suggestion_context(app, {}, response)

        assert ctx is not None
        assert ctx.itinerary_days == (
            suggestions_module.SuggestionDay(
                day_number=1,
                theme="Khám phá trung tâm",
                activities=("Tham quan Cầu Rồng", "Ăn tối"),
            ),
            suggestions_module.SuggestionDay(
                day_number=2, theme="Biển", activities=("Tắm biển Mỹ Khê",)
            ),
        )

    def test_itinerary_days_is_empty_when_there_is_no_trip_plan(self):
        app = _FakeApp(_state("itinerary_node", "ok"))
        ctx = routes._suggestion_context(app, {}, _response(trip_plan=None))
        assert ctx is not None
        assert ctx.itinerary_days == ()
        assert ctx.trip_duration_days is None
