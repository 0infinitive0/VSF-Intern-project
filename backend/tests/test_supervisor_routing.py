"""Phase 5 (260812-0927-langgraph-orchestration-state-patch-and-interrupts):
the supervisor's three delegation paths (fast path / LLM / IMPACT_MAP
fallback), the possibility guard, and the max-iteration bound. No test here
calls a real model — `get_fast_llm` is monkeypatched on the supervisor
module in every case that could reach it, and asserted un-called where the
fast path/edge predicate is supposed to skip the LLM entirely.
"""

from __future__ import annotations

import src.agents.graph.nodes.supervisor as supervisor_module
from src.agents.graph.nodes.supervisor import MAX_SUPERVISOR_ITERATIONS, SupervisorDecision, supervisor
from src.agents.graph.routing import all_tasks_done
from src.agents.graph.state import initial_graph_state


def _state(**overrides):
    state = initial_graph_state("t1")
    state.update(overrides)
    return state


class _FakeStructuredLLM:
    def __init__(self, decision: SupervisorDecision | None, exc: Exception | None):
        self._decision = decision
        self._exc = exc

    def invoke(self, _prompt):
        if self._exc is not None:
            raise self._exc
        return self._decision


class _FakeLLM:
    def __init__(self, decision: SupervisorDecision | None = None, exc: Exception | None = None):
        self._decision = decision
        self._exc = exc

    def with_structured_output(self, _model):
        return _FakeStructuredLLM(self._decision, self._exc)


def _unreachable_llm_factory(*_args, **_kwargs):
    raise AssertionError("fast path / completion predicate must never call get_fast_llm")


# --- Fast path: zero LLM calls -----------------------------------------------


def test_fast_path_delegates_without_any_llm_call(monkeypatch):
    monkeypatch.setattr(supervisor_module, "get_fast_llm", _unreachable_llm_factory)

    state = _state(pending_tasks=["hotel_node"], task_results=[])
    result = supervisor(state)

    assert result["next_worker"] == "hotel_node"
    assert result["routing_source"] == "impact_map"
    assert result["supervisor_iterations"] == 1


def test_fast_path_does_not_apply_once_a_worker_has_already_reported(monkeypatch):
    """After the first worker completes, task_results is non-empty -- even
    a single remaining pending task must go through the LLM path, matching
    the doc's "multi-task turns add more calls" trade-off."""
    decision = SupervisorDecision(next_worker="itinerary_node", task_description="continue", reasoning="x")
    monkeypatch.setattr(supervisor_module, "get_fast_llm", lambda **_kwargs: _FakeLLM(decision=decision))

    state = _state(
        pending_tasks=["itinerary_node"],
        task_results=[{"worker": "hotel_node", "status": "stub_pass_through"}],
        travel_state={"destination": {"presence": "set", "value": "Da Nang"}},
    )
    result = supervisor(state)

    assert result["next_worker"] == "itinerary_node"
    assert result["routing_source"] == "supervisor"


# --- LLM path for genuine multi-workflow turns ------------------------------


def test_multi_workflow_turn_uses_the_llm_and_honors_its_choice(monkeypatch):
    decision = SupervisorDecision(next_worker="hotel_node", task_description="search hotels", reasoning="x")
    monkeypatch.setattr(supervisor_module, "get_fast_llm", lambda **_kwargs: _FakeLLM(decision=decision))

    state = _state(
        pending_tasks=["hotel_node", "itinerary_node"],
        task_results=[],
        travel_state={"destination": {"presence": "set", "value": "Da Nang"}},
    )
    result = supervisor(state)

    assert result["next_worker"] == "hotel_node"
    assert result["routing_source"] == "supervisor"
    assert result["routing_reasoning"] == "x"


# --- IMPACT_MAP fallback on LLM failure -------------------------------------


def test_llm_failure_falls_back_to_impact_map_with_a_real_worker_node_name(monkeypatch):
    monkeypatch.setattr(
        supervisor_module, "get_fast_llm", lambda **_kwargs: _FakeLLM(exc=RuntimeError("model unreachable"))
    )

    state = _state(
        pending_tasks=["hotel_node", "itinerary_node"],
        task_results=[{"worker": "x"}],
        travel_state={"destination": {"presence": "set", "value": "Da Nang"}},
    )
    result = supervisor(state)

    # Never a bare Workflow label ("hotel"/"itinerary") -- always a node name.
    assert result["next_worker"] in ("hotel_node", "itinerary_node")
    assert result["routing_source"] == "impact_map_fallback"


def test_llm_failure_with_nothing_pending_falls_back_to_respond(monkeypatch):
    monkeypatch.setattr(
        supervisor_module, "get_fast_llm", lambda **_kwargs: _FakeLLM(exc=RuntimeError("model unreachable"))
    )

    state = _state(pending_tasks=[], task_results=[])
    result = supervisor(state)

    assert result["next_worker"] == "respond"
    assert result["routing_source"] == "impact_map_fallback"


# --- Possibility guard --------------------------------------------------------


def test_supervisor_rejects_an_impossible_proposal_and_reroutes(monkeypatch):
    """itinerary_node is impossible with no trip data. A hallucinating LLM
    proposing it must be rejected -- not trusted as a fact -- and the turn
    must still land on a real, possible worker."""
    decision = SupervisorDecision(next_worker="itinerary_node", task_description="x", reasoning="x")
    monkeypatch.setattr(supervisor_module, "get_fast_llm", lambda **_kwargs: _FakeLLM(decision=decision))

    state = _state(
        pending_tasks=["hotel_node", "itinerary_node"],
        task_results=[{"worker": "x"}],
        travel_state={},  # no destination -> itinerary_node is impossible
    )
    result = supervisor(state)

    assert result["next_worker"] == "hotel_node"
    assert result["routing_source"] == "impact_map_fallback"


def test_supervisor_rejects_a_proposal_outside_this_turns_pending_tasks(monkeypatch):
    """A worker that already reported (or was never impacted) pops nothing
    off `pending_tasks` if delegated again -- `all_tasks_done` never trips
    and the turn burns its iteration cap without ever running the
    genuinely pending worker. The LLM proposing `hotel_node` while only
    `itinerary_node` is still pending must be rejected exactly like an
    impossible proposal, not accepted as a valid label."""
    decision = SupervisorDecision(next_worker="hotel_node", task_description="x", reasoning="x")
    monkeypatch.setattr(supervisor_module, "get_fast_llm", lambda **_kwargs: _FakeLLM(decision=decision))

    state = _state(
        pending_tasks=["itinerary_node"],
        task_results=[{"worker": "hotel_node", "status": "stub_pass_through"}],
        travel_state={"destination": {"presence": "set", "value": "Da Nang"}},
    )
    result = supervisor(state)

    assert result["next_worker"] == "itinerary_node"
    assert result["routing_source"] == "impact_map_fallback"


def test_supervisor_allows_any_proposal_when_nothing_is_pending(monkeypatch):
    """With an empty `pending_tasks` (a pure question turn), there is no
    IMPACT_MAP-derived queue to constrain against -- qa_node (or any
    non-impossible worker) must stay reachable."""
    decision = SupervisorDecision(next_worker="qa_node", task_description="answer a question", reasoning="x")
    monkeypatch.setattr(supervisor_module, "get_fast_llm", lambda **_kwargs: _FakeLLM(decision=decision))

    state = _state(pending_tasks=[], task_results=[])
    result = supervisor(state)

    assert result["next_worker"] == "qa_node"
    assert result["routing_source"] == "supervisor"


def test_booking_node_is_never_eligible_via_impact_map():
    """`_IMPOSSIBLE['booking_node']` is unconditionally True -- the
    IMPACT_MAP-derived eligible-worker list (what both the fast path and
    the LLM-failure fallback delegate from) never includes it, even when
    it is sitting right there in `pending_tasks`."""
    state = _state(pending_tasks=["booking_node", "hotel_node"])
    eligible = supervisor_module._eligible_workers(state)
    assert "booking_node" not in eligible
    assert "hotel_node" in eligible


# --- Iteration bound -----------------------------------------------------------


def test_supervisor_loop_terminates_at_the_max_iteration_bound(monkeypatch):
    monkeypatch.setattr(supervisor_module, "get_fast_llm", _unreachable_llm_factory)

    state = _state(supervisor_iterations=MAX_SUPERVISOR_ITERATIONS, pending_tasks=["hotel_node", "itinerary_node"])
    result = supervisor(state)

    assert result["next_worker"] == "respond"
    assert result["routing_source"] == "max_iterations"


def test_supervisor_never_exceeds_max_iterations_when_a_worker_never_reports_done(monkeypatch):
    """Worst case: `pending_tasks` never shrinks (a worker that never
    signals completion) and the LLM is permanently down, so every call
    falls back to the same `IMPACT_MAP`-derived worker. The iteration
    counter must still hit the cap and force `respond` -- never spin
    forever chasing the same delegation."""
    monkeypatch.setattr(supervisor_module, "get_fast_llm", lambda **_kwargs: _FakeLLM(exc=RuntimeError("down")))

    state = _state(
        pending_tasks=["hotel_node"],
        task_results=[{"worker": "x"}],  # non-empty -> fast path never applies
        travel_state={"destination": {"presence": "set", "value": "Da Nang"}},
    )

    seen_sources: list[str] = []
    for _ in range(MAX_SUPERVISOR_ITERATIONS + 3):
        update = supervisor(state)
        state.update(update)
        seen_sources.append(update["routing_source"])
        if update["routing_source"] == "max_iterations":
            break

    assert state["next_worker"] == "respond"
    assert seen_sources[-1] == "max_iterations"
    assert state["supervisor_iterations"] >= MAX_SUPERVISOR_ITERATIONS
    # every call before the cap kicked in used the deterministic fallback --
    # it never silently stopped delegating before the counter forced it to.
    assert seen_sources[:-1] == ["impact_map_fallback"] * (len(seen_sources) - 1)


# --- all_tasks_done: plain predicate, no LLM ---------------------------------


def test_all_tasks_done_is_a_plain_predicate_with_no_llm_dependency():
    """`all_tasks_done` lives in `routing.py`, which never imports
    `get_fast_llm` or anything from `nodes/supervisor.py` at all -- monkey-
    patching a symbol this function can't reach would prove nothing, so the
    "no LLM call" guarantee is asserted structurally instead: its compiled
    bytecode resolves no name other than `state`/`pending_tasks`, so there
    is no code path inside it that could ever reach an LLM client."""
    import src.agents.graph.routing as routing_module

    assert "get_fast_llm" not in dir(routing_module)
    referenced_names = set(all_tasks_done.__code__.co_names)
    assert referenced_names == {"get"}  # only `state.get(...)` is called

    assert all_tasks_done(_state(pending_tasks=[])) is True
    assert all_tasks_done(_state(pending_tasks=["hotel_node"])) is False
