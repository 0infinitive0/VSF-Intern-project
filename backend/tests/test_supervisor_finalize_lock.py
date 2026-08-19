"""The finalized-trip lock guard in `nodes/supervisor.py` — refuses whichever
writer worker a turn wanted once `trip_data`'s itinerary is `Finalized`,
in words, rather than silently dropping the work.

Checked ahead of `_eligible_workers` deliberately, not via `_IMPOSSIBLE`:
marking a worker impossible only removes it from the eligible set, and
nothing then fills `task_results` with a reply — `respond` would fall
through to its generic "Đã cập nhật thông tin chuyến đi" acknowledgement
for a turn that changed nothing. These tests assert the refusal itself,
not just that the writer never ran.

No test here calls a real model — `get_fast_llm` is monkeypatched (and
asserted un-called, matching test_supervisor_routing.py's convention) in
every case, since the lock guard must short-circuit before either the fast
path or the LLM path gets a chance to run.
"""

from __future__ import annotations

import src.agents.graph.nodes.supervisor as supervisor_module
from src.agents.graph.nodes.supervisor import supervisor
from src.agents.graph.state import initial_graph_state


def _finalized_trip_data() -> dict:
    return {"hotel": {"id": "h1"}, "itineraries": [{"id": "itin-1", "status": "Finalized"}], "itinerary_items": []}


def _state(**overrides):
    state = initial_graph_state("t1")
    state.update(overrides)
    return state


def _unreachable_llm_factory(*_args, **_kwargs):
    raise AssertionError("the lock guard must short-circuit before any LLM path is reached")


class TestWriterRefusedWhenFinalized:
    def test_hotel_node_is_refused_with_a_reply_not_silently_dropped(self, monkeypatch):
        monkeypatch.setattr(supervisor_module, "get_fast_llm", _unreachable_llm_factory)

        state = _state(pending_tasks=["hotel_node"], task_results=[], trip_data=_finalized_trip_data())
        result = supervisor(state)

        assert result["next_worker"] == "respond"
        assert result["routing_source"] == "trip_finalized"
        assert result["task_results"][-1]["status"] == "locked"
        assert result["task_results"][-1]["reply"]  # a real message, not empty
        assert "hotel_node" not in result["pending_tasks"]

    def test_itinerary_node_is_refused_the_same_way(self, monkeypatch):
        monkeypatch.setattr(supervisor_module, "get_fast_llm", _unreachable_llm_factory)

        state = _state(pending_tasks=["itinerary_node"], task_results=[], trip_data=_finalized_trip_data())
        result = supervisor(state)

        assert result["next_worker"] == "respond"
        assert result["routing_source"] == "trip_finalized"
        assert "itinerary_node" not in result["pending_tasks"]

    def test_reply_language_follows_the_session(self, monkeypatch):
        monkeypatch.setattr(supervisor_module, "get_fast_llm", _unreachable_llm_factory)

        state = _state(
            pending_tasks=["hotel_node"], task_results=[], trip_data=_finalized_trip_data(), language="en"
        )
        result = supervisor(state)

        reply = result["task_results"][-1]["reply"]
        assert "khoá" not in reply  # not Vietnamese
        assert reply  # a real English message

    def test_preexisting_task_results_are_preserved_not_replaced(self, monkeypatch):
        monkeypatch.setattr(supervisor_module, "get_fast_llm", _unreachable_llm_factory)

        state = _state(
            pending_tasks=["hotel_node"],
            task_results=[{"worker": "qa_node", "status": "ok", "reply": "earlier answer"}],
            trip_data=_finalized_trip_data(),
        )
        result = supervisor(state)

        workers = [entry["worker"] for entry in result["task_results"]]
        assert workers == ["qa_node", "supervisor"]


class TestReadOnlyTurnsUnaffected:
    """The lock only ever fires on `pending_tasks` naming a WRITER worker
    (`CONTRACTS[worker].writes` non-empty) -- a pure question turn never
    populates `pending_tasks` at all (see `WORKFLOW_TO_WORKER`), so it must
    reach the ordinary qa_node path completely untouched by a finalized
    trip."""

    def test_a_question_turn_still_reaches_qa_node(self, monkeypatch):
        from src.agents.graph.nodes.supervisor import SupervisorDecision

        class _FakeStructuredLLM:
            def invoke(self, _prompt):
                return SupervisorDecision(next_worker="qa_node", task_description="answer a question", reasoning="x")

        class _FakeLLM:
            def with_structured_output(self, _model):
                return _FakeStructuredLLM()

        monkeypatch.setattr(supervisor_module, "get_fast_llm", lambda **_kwargs: _FakeLLM())

        state = _state(pending_tasks=[], task_results=[], trip_data=_finalized_trip_data())
        result = supervisor(state)

        assert result["next_worker"] == "qa_node"
        assert result["routing_source"] == "supervisor"

    def test_booking_node_pending_alone_is_unaffected_by_the_lock(self, monkeypatch):
        """booking_node's own `CONTRACTS.writes` is empty (it never actually
        writes anything -- it only ever declines), so it is not what this
        guard exists to catch; `_IMPOSSIBLE['booking_node']` already blocks
        it unconditionally, finalized or not."""
        monkeypatch.setattr(supervisor_module, "get_fast_llm", _unreachable_llm_factory)

        state = _state(pending_tasks=["booking_node"], task_results=[], trip_data=_finalized_trip_data())
        result = supervisor(state)

        assert result["routing_source"] != "trip_finalized"


class TestNotFinalizedIsUnaffected:
    def test_a_draft_trip_goes_through_the_ordinary_fast_path(self, monkeypatch):
        monkeypatch.setattr(supervisor_module, "get_fast_llm", _unreachable_llm_factory)

        state = _state(
            pending_tasks=["hotel_node"],
            task_results=[],
            trip_data={"itineraries": [{"id": "itin-1", "status": "Draft"}]},
        )
        result = supervisor(state)

        assert result["next_worker"] == "hotel_node"
        assert result["routing_source"] == "impact_map"

    def test_no_trip_data_at_all_goes_through_the_ordinary_fast_path(self, monkeypatch):
        monkeypatch.setattr(supervisor_module, "get_fast_llm", _unreachable_llm_factory)

        state = _state(pending_tasks=["hotel_node"], task_results=[])
        result = supervisor(state)

        assert result["next_worker"] == "hotel_node"
        assert result["routing_source"] == "impact_map"
