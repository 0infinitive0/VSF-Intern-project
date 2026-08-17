"""`NodeContract.emits_reply` — the obligation that a worker which finished
its job says something about it.

Before this contract existed, `respond` picked up whatever reply a worker
happened to leave in `task_results` and fell through to a generic
acknowledgement when it found none. A worker that built a five-day
itinerary and returned silently produced a successful turn answered with
"Đã cập nhật thông tin chuyến đi." — the safety net doing duty as the main
road. These tests pin the three things that keeps working:

- a silent worker is caught, not shrugged off;
- a worker that re-queued itself is *allowed* to be silent, because it is
  mid-job (the multi-day itinerary build, one day per invocation);
- `contract_enforcement_mode=log` degrades the catch to a log line, so the
  check that guards CI cannot cost a production user their turn.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from src.agents.graph import contracts as contracts_module
from src.agents.graph.contracts import CONTRACTS, ContractViolation, NodeContract, enforce_contract
from src.agents.graph.state import TravelGraphState, initial_graph_state
from src.config import get_settings

_FAKE_WORKER = "fake_worker"


@pytest.fixture
def speaking_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    """Register a throwaway worker that owes a reply and may write nothing."""
    monkeypatch.setitem(
        CONTRACTS,
        _FAKE_WORKER,
        NodeContract(reads=frozenset(), writes=frozenset(), emits_reply=True),
    )


@pytest.fixture
def strict_mode(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CONTRACT_ENFORCEMENT_MODE", "strict")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def log_mode(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CONTRACT_ENFORCEMENT_MODE", "log")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _state(**overrides: Any) -> TravelGraphState:
    state = initial_graph_state("t1")
    for key, value in overrides.items():
        state[key] = value  # type: ignore[literal-required]
    return state


class TestEmitsReplyInStrictMode:
    def test_a_worker_that_leaves_no_reply_is_a_violation(self, speaking_contract, strict_mode):
        def _silent(state):
            # The exact shape of the bug this contract exists for: real work
            # done (trip_data returned), task_results passed through untouched.
            return {"task_results": list(state.get("task_results") or []), "trip_data": {"x": 1}}

        with pytest.raises(ContractViolation, match="emits_reply"):
            enforce_contract(_FAKE_WORKER, _silent)(_state())

    def test_a_worker_that_appends_a_reply_passes(self, speaking_contract, strict_mode):
        def _speaking(state):
            return {
                "task_results": [
                    *(state.get("task_results") or []),
                    {"worker": _FAKE_WORKER, "status": "ok", "reply": "Đã dựng xong lịch trình 3 ngày."},
                ]
            }

        result = enforce_contract(_FAKE_WORKER, _speaking)(_state())
        assert result["task_results"][-1]["reply"].startswith("Đã dựng xong")

    def test_a_blank_reply_does_not_satisfy_the_contract(self, speaking_contract, strict_mode):
        def _whitespace(state):
            return {
                "task_results": [
                    *(state.get("task_results") or []),
                    {"worker": _FAKE_WORKER, "status": "ok", "reply": "   "},
                ]
            }

        with pytest.raises(ContractViolation, match="emits_reply"):
            enforce_contract(_FAKE_WORKER, _whitespace)(_state())

    def test_only_entries_added_this_call_count(self, speaking_contract, strict_mode):
        """A previous worker's reply is not this worker's."""

        def _silent(state):
            return {"task_results": list(state.get("task_results") or [])}

        prior = [{"worker": "hotel_node", "status": "ok", "reply": "Mình tìm được 3 khách sạn."}]
        with pytest.raises(ContractViolation, match="emits_reply"):
            enforce_contract(_FAKE_WORKER, _silent)(_state(task_results=prior))

    def test_a_worker_that_requeued_itself_may_stay_silent(self, speaking_contract, strict_mode):
        """The multi-day build: one day per invocation, speak once at the end."""

        def _mid_job(state):
            return {
                "pending_tasks": [_FAKE_WORKER],
                "task_results": list(state.get("task_results") or []),
                "rebuild_day_queue": [2, 3],
            }

        result = enforce_contract(_FAKE_WORKER, _mid_job)(_state())
        assert result["rebuild_day_queue"] == [2, 3]

    def test_a_discarded_turn_may_stay_silent(self, speaking_contract, strict_mode):
        """`unresolved_resume_text` marks the turn `_run_turn_via_graph`
        throws away and replays — its reply never reaches anyone."""

        def _unresolved(state):
            return {
                "task_results": [
                    *(state.get("task_results") or []),
                    {"worker": _FAKE_WORKER, "status": "center_unresolved", "reply": ""},
                ],
                "unresolved_resume_text": "khách sạn gần biển",
            }

        result = enforce_contract(_FAKE_WORKER, _unresolved)(_state())
        assert result["unresolved_resume_text"] == "khách sạn gần biển"

    def test_a_worker_without_the_obligation_may_stay_silent(self, strict_mode):
        def _silent(state):
            return {"task_results": list(state.get("task_results") or [])}

        # booking_node does not declare emits_reply in this test's scope.
        assert CONTRACTS["qa_node"].emits_reply is False
        enforce_contract("qa_node", _silent)(_state())


class TestLogMode:
    def test_a_silent_worker_is_logged_not_raised(
        self, speaking_contract, log_mode, caplog: pytest.LogCaptureFixture
    ):
        def _silent(state):
            return {"task_results": list(state.get("task_results") or []), "trip_data": {"x": 1}}

        with caplog.at_level(logging.ERROR, logger=contracts_module.__name__):
            result = enforce_contract(_FAKE_WORKER, _silent)(_state())

        # The update survives intact — the user still gets their turn.
        assert result["trip_data"] == {"x": 1}
        assert any("emits_reply" in record.getMessage() for record in caplog.records)

    def test_the_mode_covers_travel_state_violations_too(
        self, log_mode, caplog: pytest.LogCaptureFixture
    ):
        """One mode for both checks — same mechanism, same reason."""

        def _rogue_qa_node(state):
            travel_state = dict(state.get("travel_state") or {})
            travel_state["hotel_preferences.amenities"] = {"presence": "set", "value": ["pool"]}
            return {"travel_state": travel_state}

        with caplog.at_level(logging.ERROR, logger=contracts_module.__name__):
            result = enforce_contract("qa_node", _rogue_qa_node)(_state())

        assert result["travel_state"]["hotel_preferences.amenities"]["value"] == ["pool"]
        assert any("outside its contract" in record.getMessage() for record in caplog.records)


class TestDefaults:
    def test_the_obligation_is_opt_in(self):
        assert NodeContract(reads=frozenset(), writes=frozenset()).emits_reply is False

    def test_ci_runs_strict_by_default(self):
        """CI runs on defaults, so a new violation must fail the build there."""
        get_settings.cache_clear()
        assert get_settings().contract_enforcement_mode == "strict"


class TestDeclaredWorkers:
    @pytest.mark.parametrize("worker", ["hotel_node", "itinerary_node", "booking_node"])
    def test_every_user_facing_worker_owes_a_reply(self, worker: str):
        assert CONTRACTS[worker].emits_reply is True

    def test_qa_node_is_exempt(self):
        """`qa_node` is not wrapped by `enforce_contract` at all (graph.py)
        and answers through the `messages` channel, not `task_results`."""
        assert CONTRACTS["qa_node"].emits_reply is False
