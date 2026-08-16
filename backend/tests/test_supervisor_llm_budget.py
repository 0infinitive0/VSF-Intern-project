"""How many LLM calls the supervisor spends deciding a delegation.

`WORKER_ORDER` already fixes the order workers run in, and it fixes it for a
causal reason: the hotel anchors the itinerary, so rebuilding the itinerary
first would schedule around a hotel that is about to change. The supervisor
then constrains the model to choose from that same ordered list. So on a
first delegation the model is being asked a question the table has already
answered, and of its three possible answers — `workers[0]`, a
later-in-order worker, or something off-list — one matches the table, one is
off-list and gets rejected back to the table, and the remaining one is
simply the wrong order.

The LLM path stays for recovery (`task_results` non-empty), where a worker
has already failed and a static table no longer has enough information.
"""

from __future__ import annotations

import pytest

import src.agents.graph.nodes.supervisor as supervisor_module
from src.agents.graph.nodes.supervisor import SupervisorDecision, supervisor
from src.agents.graph.state import initial_graph_state


def _state(**overrides):
    state = initial_graph_state("t1")
    state.update(overrides)
    return state


class _CountingLLM:
    """Records every `get_fast_llm` call the turn makes."""

    def __init__(self, calls: list[str], decision: SupervisorDecision):
        self._calls = calls
        self._decision = decision

    def with_structured_output(self, _model):
        return self

    def invoke(self, _prompt):
        self._calls.append("invoke")
        return self._decision


@pytest.fixture
def llm_calls(monkeypatch):
    calls: list[str] = []
    decision = SupervisorDecision(next_worker="hotel_node", task_description="x", reasoning="x")

    def _factory(**_kwargs):
        calls.append("get_fast_llm")
        return _CountingLLM(calls, decision)

    monkeypatch.setattr(supervisor_module, "get_fast_llm", _factory)
    return calls


def _multi_workflow_state(**overrides):
    """"đổi khách sạn và làm lại lịch trình" — one message, both workflows
    impacted, a trip already in place so both workers are genuinely
    eligible."""
    base = dict(
        pending_tasks=["hotel_node", "itinerary_node"],
        task_results=[],
        travel_state={"destination": {"presence": "set", "value": "Da Nang"}},
        trip_data={"destination": "Da Nang"},
    )
    base.update(overrides)
    return _state(**base)


class TestFirstDelegationSpendsNoLLMCall:
    def test_a_multi_worker_turn_delegates_from_the_table(self, llm_calls):
        result = supervisor(_multi_workflow_state())

        assert llm_calls == []
        assert result["next_worker"] == "hotel_node"
        assert result["routing_source"] == "impact_map"

    def test_a_single_worker_turn_still_spends_nothing(self, llm_calls):
        result = supervisor(_multi_workflow_state(pending_tasks=["hotel_node"]))

        assert llm_calls == []
        assert result["routing_source"] == "impact_map"

    def test_the_delegation_order_is_worker_order(self, llm_calls):
        """Same answer whichever way `pending_tasks` happens to be ordered —
        the table decides, not the queue's insertion order."""
        reversed_pending = supervisor(
            _multi_workflow_state(pending_tasks=["itinerary_node", "hotel_node"])
        )

        assert llm_calls == []
        assert reversed_pending["next_worker"] == "hotel_node"


class TestRecoveryStillReasons:
    def test_a_turn_after_a_worker_reported_goes_through_the_llm(self, llm_calls):
        """The boundary is `task_results`: empty means first delegation (the
        table is enough), non-empty means something already ran and may have
        failed (it isn't)."""
        result = supervisor(
            _multi_workflow_state(task_results=[{"worker": "hotel_node", "status": "error"}])
        )

        assert llm_calls == ["get_fast_llm", "invoke"]
        assert result["routing_source"] == "supervisor"
