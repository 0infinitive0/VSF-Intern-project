"""Phase 5 (260812-0927-langgraph-orchestration-state-patch-and-interrupts):
the supervisor's three delegation paths (fast path / LLM / IMPACT_MAP
fallback), the possibility guard, and the max-iteration bound. No test here
calls a real model — `get_fast_llm` is monkeypatched on the supervisor
module in every case that could reach it, and asserted un-called where the
fast path/edge predicate is supposed to skip the LLM entirely.
"""

from __future__ import annotations

import json

from langchain_core.messages import HumanMessage

import src.agents.graph.nodes.supervisor as supervisor_module
from src.agents.graph.nodes.supervisor import MAX_SUPERVISOR_ITERATIONS, SupervisorDecision, supervisor
from src.agents.graph.routing import all_tasks_done, route_after_itinerary_node
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


def test_first_intake_turn_with_no_trip_goes_to_hotel_node_not_a_coin_flip(monkeypatch):
    """Regression: a single message that sets destination/dates/people/
    preferences all at once impacts both `hotel` and `itinerary`
    workflows, seeding `pending_tasks=["hotel_node", "itinerary_node"]`
    (apply_patch.py). Before `itinerary_node` also required `trip_data` to
    be possible, this forced the LLM path, and a wrong LLM pick of
    `itinerary_node` bailed immediately ("chọn khách sạn trước") with
    nothing to show -- the user had to resend the identical message.
    `itinerary_node` being impossible with no `trip_data` restores the fast
    path here: exactly one real candidate, zero LLM calls, `hotel_node`
    every time."""
    monkeypatch.setattr(supervisor_module, "get_fast_llm", _unreachable_llm_factory)

    state = _state(
        pending_tasks=["hotel_node", "itinerary_node"],
        task_results=[],
        travel_state={"destination": {"presence": "set", "value": "Da Nang"}},
        trip_data={},
    )
    result = supervisor(state)

    assert result["next_worker"] == "hotel_node"
    assert result["routing_source"] == "impact_map"


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
        trip_data={"destination": "Da Nang"},  # itinerary_node needs trip_data to be possible
    )
    result = supervisor(state)

    assert result["next_worker"] == "itinerary_node"
    assert result["routing_source"] == "supervisor"


# --- LLM path: recovery only -------------------------------------------------


def test_multi_workflow_first_delegation_uses_the_table_not_the_llm(monkeypatch):
    """A multi-worker turn used to go through the LLM. It no longer does:
    `WORKER_ORDER` already fixes the order for a causal reason (the hotel
    anchors the itinerary), and the model is constrained to pick from that
    same ordered list, so the only answer that differs from `workers[0]` is
    the wrong order. Call budget is pinned in
    `test_supervisor_llm_budget.py`."""
    monkeypatch.setattr(supervisor_module, "get_fast_llm", _unreachable_llm_factory)

    state = _state(
        pending_tasks=["hotel_node", "itinerary_node"],
        task_results=[],
        travel_state={"destination": {"presence": "set", "value": "Da Nang"}},
        trip_data={"destination": "Da Nang"},  # itinerary_node needs trip_data to be possible
    )
    result = supervisor(state)

    assert result["next_worker"] == "hotel_node"
    assert result["routing_source"] == "impact_map"


def test_recovery_turn_uses_the_llm_and_honors_its_choice(monkeypatch):
    """Where reasoning still earns its call: a worker has already reported,
    so the static table no longer has enough information to pick the next
    step. The model's choice is honored as before."""
    decision = SupervisorDecision(next_worker="itinerary_node", task_description="rebuild", reasoning="x")
    monkeypatch.setattr(supervisor_module, "get_fast_llm", lambda **_kwargs: _FakeLLM(decision=decision))

    state = _state(
        pending_tasks=["hotel_node", "itinerary_node"],
        task_results=[{"worker": "hotel_node", "status": "error"}],
        travel_state={"destination": {"presence": "set", "value": "Da Nang"}},
        trip_data={"destination": "Da Nang"},  # itinerary_node needs trip_data to be possible
    )
    result = supervisor(state)

    assert result["next_worker"] == "itinerary_node"
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
        trip_data={"destination": "Da Nang"},  # itinerary_node needs trip_data to be possible
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


# --- itinerary_node's `action` -> `task_description` JSON contract -----------


def test_edit_item_action_is_encoded_as_json_task_description(monkeypatch):
    """`itinerary_node._parse_task` only recognizes `edit_item`/`lock_days`
    from a JSON `{"action": ..., "user_request": ...}` string -- a plain
    sentence silently falls back to `rebuild_days` every time. Regression
    for that: when the LLM sets `action="edit_item"`, `_delegate` must
    encode it into that exact JSON shape, not pass the sentence through."""
    decision = SupervisorDecision(
        next_worker="itinerary_node",
        task_description="Swap day 1's breakfast for Timeline Coffee & Restaurant.",
        reasoning="user asked to change one meal on one day",
        action="edit_item",
    )
    monkeypatch.setattr(supervisor_module, "get_fast_llm", lambda **_kwargs: _FakeLLM(decision=decision))

    state = _state(
        pending_tasks=[],
        task_results=[],
        trip_data={"itineraries": [{}]},
        travel_state={"destination": {"presence": "set", "value": "Da Nang"}},
    )
    result = supervisor(state)

    assert result["next_worker"] == "itinerary_node"
    assert json.loads(result["task_description"]) == {
        "action": "edit_item",
        "user_request": "Swap day 1's breakfast for Timeline Coffee & Restaurant.",
    }


def test_itinerary_action_is_ignored_for_a_non_itinerary_worker(monkeypatch):
    """`action` only means something for `itinerary_node` -- a value set on
    any other worker (a model slip, or just unset) must not leak into that
    worker's plain-text `task_description`."""
    decision = SupervisorDecision(
        next_worker="qa_node", task_description="answer a question", reasoning="x", action="edit_item"
    )
    monkeypatch.setattr(supervisor_module, "get_fast_llm", lambda **_kwargs: _FakeLLM(decision=decision))

    state = _state(pending_tasks=[], task_results=[])
    result = supervisor(state)

    assert result["next_worker"] == "qa_node"
    assert result["task_description"] == "answer a question"


def test_itinerary_node_without_an_action_keeps_the_plain_sentence(monkeypatch):
    """No `action` set (e.g. a whole-day rebuild) -- `task_description`
    stays the model's own sentence, matching `itinerary_node`'s documented
    plain-string fallback to `rebuild_days`."""
    decision = SupervisorDecision(
        next_worker="itinerary_node", task_description="Rebuild day 2 from scratch.", reasoning="x"
    )
    monkeypatch.setattr(supervisor_module, "get_fast_llm", lambda **_kwargs: _FakeLLM(decision=decision))

    state = _state(
        pending_tasks=[],
        task_results=[],
        trip_data={"itineraries": [{}]},
        travel_state={"destination": {"presence": "set", "value": "Da Nang"}},
    )
    result = supervisor(state)

    assert result["task_description"] == "Rebuild day 2 from scratch."


def test_booking_node_is_never_eligible_via_impact_map():
    """`_IMPOSSIBLE['booking_node']` is unconditionally True -- the
    IMPACT_MAP-derived eligible-worker list (what both the fast path and
    the LLM-failure fallback delegate from) never includes it, even when
    it is sitting right there in `pending_tasks`."""
    state = _state(pending_tasks=["booking_node", "hotel_node"])
    eligible = supervisor_module._eligible_workers(state)
    assert "booking_node" not in eligible
    assert "hotel_node" in eligible


# --- Read-only routing: nearby-places vs qa_node -----------------------------
#
# Regression coverage for the trace bug: "liệt kê các địa điểm nổi bật trong
# vòng bán kính 3km" auto-routed to `qa_node` via `read_only_intent`, whose
# tools cannot write `suggested_places` -- the map showed zero pins. This
# section locks the `asks_nearby_places` gate added to close that gap, in
# both directions, and proves neither direction spends an LLM call (the
# regression guard for the earlier "ngày 3 tôi làm gì?" incident: that bug
# came from the unconstrained LLM branch, which this gate never reaches).


def test_asks_nearby_places_true_routes_to_itinerary_node_list_nearby():
    # Original bug-report text, misspelling ("nối bật") kept verbatim so this
    # test stays anchored to the trace it regresses against.
    message = "liệt kê các địa điểm nối bật trong vòng bán kính 3km"
    state = _state(
        messages=[HumanMessage(content=message)],
        intent="general_question",
        asks_nearby_places=True,
        pending_tasks=[],
        task_results=[],
        trip_data={"itineraries": [{}]},
        travel_state={"destination": {"presence": "set", "value": "Da Nang"}},
    )
    result = supervisor(state)

    assert result["next_worker"] == "itinerary_node"
    assert result["routing_source"] == "read_only_intent_nearby"
    task = json.loads(result["task_description"])
    assert task == {"action": "list_nearby", "user_request": message}


def test_asks_nearby_places_true_with_nothing_to_measure_from_routes_to_qa_node():
    """No trip AND no hotel cards on screen: there is no location to center a
    radius on, so `itinerary_node.list_nearby` could only hard-stop ("chọn
    khách sạn trước..."), where `qa_node` can at least attempt an answer."""
    state = _state(
        messages=[HumanMessage(content="gợi ý vài chỗ tham quan gần đây")],
        intent="general_question",
        asks_nearby_places=True,
        pending_tasks=[],
        task_results=[],
        trip_data={},
    )
    result = supervisor(state)

    assert result["next_worker"] == "qa_node"
    assert result["routing_source"] == "read_only_intent"


def test_asks_nearby_places_with_hotel_shortlist_but_no_trip_routes_to_list_nearby():
    """The reported gap: "tìm quanh khách sạn số 1" while still choosing
    between the shortlist cards. No trip exists yet, so the old
    `is_impossible` gate sent this to `qa_node`, whose tools cannot write
    `suggested_places` -- the map stayed empty at the one stage where the
    question is most useful."""
    message = "tìm quanh khách sạn số 1 có gì"
    state = _state(
        messages=[HumanMessage(content=message)],
        intent="general_question",
        asks_nearby_places=True,
        pending_tasks=[],
        task_results=[],
        trip_data={},
        travel_state={"destination": {"presence": "set", "value": "Hà Nội"}},
        previous_hotel_options=[{"id": "h1", "name": "A", "coordinates": "21.0,105.8"}],
    )
    result = supervisor(state)

    assert result["next_worker"] == "itinerary_node"
    assert result["routing_source"] == "read_only_intent_nearby"
    assert json.loads(result["task_description"]) == {
        "action": "list_nearby",
        "user_request": message,
    }


def test_asks_nearby_places_false_routes_to_qa_node_unchanged():
    state = _state(
        messages=[HumanMessage(content="phòng nào rẻ hơn?")],
        intent="general_question",
        asks_nearby_places=False,
        pending_tasks=[],
        task_results=[],
    )
    result = supervisor(state)

    assert result["next_worker"] == "qa_node"
    assert result["routing_source"] == "read_only_intent"


def test_asks_nearby_places_absent_from_state_still_routes_to_qa_node():
    """A session started before this field existed has no
    `asks_nearby_places` key at all -- `state.get(...)` must fall open to
    `qa_node`, not raise `KeyError`."""
    state = _state(
        messages=[HumanMessage(content="ngày 3 tôi làm gì?")],
        intent="general_question",
        pending_tasks=[],
        task_results=[],
    )
    del state["asks_nearby_places"]

    result = supervisor(state)

    assert result["next_worker"] == "qa_node"
    assert result["routing_source"] == "read_only_intent"


def test_read_only_branch_never_calls_llm_when_nearby_true(monkeypatch):
    monkeypatch.setattr(supervisor_module, "get_fast_llm", _unreachable_llm_factory)
    state = _state(
        messages=[HumanMessage(content="gần khách sạn có gì hay ho")],
        intent="general_question",
        asks_nearby_places=True,
        pending_tasks=[],
        task_results=[],
        trip_data={"itineraries": [{}]},
        travel_state={"destination": {"presence": "set", "value": "Da Nang"}},
    )
    result = supervisor(state)
    assert result["next_worker"] == "itinerary_node"


def test_read_only_branch_never_calls_llm_when_nearby_false(monkeypatch):
    monkeypatch.setattr(supervisor_module, "get_fast_llm", _unreachable_llm_factory)
    state = _state(
        messages=[HumanMessage(content="ngày 3 tôi làm gì?")],
        intent="general_question",
        asks_nearby_places=False,
        pending_tasks=[],
        task_results=[],
    )
    result = supervisor(state)
    assert result["next_worker"] == "qa_node"


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


# --- route_after_itinerary_node: the nearby-places turn skips budget_check ---
#
# `budget_check` re-plans (live hotel search + unlocked-day rebuild)
# whenever `budget.trip_total` is set, regardless of whether the turn that
# reached it actually changed anything -- and `response_payload.py` reads
# `suggested_places` off `task_results[-1]`, which `budget_check` overwrites.
# For every OTHER itinerary_node arrival (a real edit) that is the existing,
# correct behavior; for the read-only `list_nearby` turn it would both erase
# the map pins this fix exists to produce and let a read-only question
# silently rebuild the plan -- reopening the exact incident class the
# hardcoded `action` constant in `supervisor.py` was meant to close.


def test_route_after_itinerary_node_sends_read_only_nearby_turn_to_respond():
    state = _state(pending_tasks=[], routing_source="read_only_intent_nearby")
    assert route_after_itinerary_node(state) == "respond"


def test_route_after_itinerary_node_sends_every_other_source_to_budget_check():
    for source in ("impact_map", "supervisor", "day_loop_continuation", ""):
        state = _state(pending_tasks=[], routing_source=source)
        assert route_after_itinerary_node(state) == "budget_check"


def test_route_after_itinerary_node_defers_to_supervisor_when_not_done():
    """A multi-day rebuild still mid-queue must return to `supervisor`
    regardless of `routing_source` -- `all_tasks_done` stays the first
    check, same order as every other worker's completion edge."""
    state = _state(pending_tasks=["itinerary_node"], routing_source="read_only_intent_nearby")
    assert route_after_itinerary_node(state) == "supervisor"


# --- needs_trip_first: an itinerary request before a trip exists -------------


class TestNeedsTripFirst:
    """`itinerary_node` cannot build a trip, only edit one — the trip is
    created when the user picks a hotel. Asking for an itinerary before that
    used to leave the supervisor with an empty eligible set, which fell
    through the LLM path to `respond` and answered a real request with
    nothing useful. The constraint is real; the turn should act on it by
    sending the user to the step they actually need.
    """

    def _no_trip_state(self, **overrides):
        base = dict(
            pending_tasks=["itinerary_node"],
            task_results=[],
            travel_state={"destination": {"presence": "set", "value": "Da Nang"}},
            trip_data={},
        )
        base.update(overrides)
        return _state(**base)

    def test_it_delegates_to_hotel_node_without_asking_the_llm(self, monkeypatch):
        monkeypatch.setattr(supervisor_module, "get_fast_llm", _unreachable_llm_factory)

        result = supervisor(self._no_trip_state())

        assert result["next_worker"] == "hotel_node"
        assert result["routing_source"] == "needs_trip_first"

    def test_the_redirect_cannot_loop(self, monkeypatch):
        """`all_tasks_done` is `not pending_tasks`, and `hotel_node` only ever
        removes *itself* from that list. Leaving `itinerary_node` pending
        would send the turn back to the supervisor with the trip still
        missing — hotel searched again, redirected again, until the iteration
        cap. The redirect has to hand off the pending slot, not add to it."""
        monkeypatch.setattr(supervisor_module, "get_fast_llm", _unreachable_llm_factory)

        result = supervisor(self._no_trip_state())
        pending_after_supervisor = result["pending_tasks"]

        assert "itinerary_node" not in pending_after_supervisor
        assert pending_after_supervisor == ["hotel_node"]

        # Now simulate hotel_node doing what it always does: pop itself.
        pending_after_hotel = [w for w in pending_after_supervisor if w != "hotel_node"]
        assert all_tasks_done(_state(pending_tasks=pending_after_hotel)) is True
        assert result["supervisor_iterations"] == 1

    def test_no_second_redirect_after_hotel_node_already_ran_this_turn(self, monkeypatch):
        """The common first-intake turn seeds `pending_tasks=["hotel_node",
        "itinerary_node"]`. `hotel_node` runs, pops itself, and — because it
        presented options rather than creating the trip — leaves `trip_data`
        empty with `itinerary_node` still pending. That is the exact shape
        this redirect fires on, so it sent the turn straight back into a
        second full hotel search (RPC + hydration + ranking) to ask the same
        question twice. The user is being waited on; the turn is over."""
        monkeypatch.setattr(supervisor_module, "get_fast_llm", _unreachable_llm_factory)

        state = self._no_trip_state(
            task_results=[{"worker": "hotel_node", "status": "ok", "reply": "Mình tìm được vài khách sạn..."}],
        )
        result = supervisor(state)

        assert result["next_worker"] == "respond"
        assert result["routing_source"] == "awaiting_hotel_choice"
        assert "itinerary_node" not in result["pending_tasks"]

    def test_first_redirect_still_happens_when_hotel_node_has_not_run(self, monkeypatch):
        """The guard above keys on *this turn's* `task_results`, so an
        unrelated earlier worker must not suppress the redirect."""
        monkeypatch.setattr(supervisor_module, "get_fast_llm", _unreachable_llm_factory)

        result = supervisor(self._no_trip_state(task_results=[{"worker": "booking_node", "status": "ok"}]))

        assert result["next_worker"] == "hotel_node"
        assert result["routing_source"] == "needs_trip_first"

    def test_no_redirect_once_a_trip_exists(self, monkeypatch):
        """The ordinary edit path — `itinerary_node` is eligible on its own."""
        monkeypatch.setattr(supervisor_module, "get_fast_llm", _unreachable_llm_factory)

        result = supervisor(self._no_trip_state(trip_data={"destination": "Da Nang"}))

        assert result["next_worker"] == "itinerary_node"
        assert result["routing_source"] == "impact_map"

    def test_no_redirect_when_the_destination_is_what_is_missing(self, monkeypatch):
        """A missing destination is `ask_slot`'s job. Sending that turn to
        `hotel_node` would only produce its "no destination" defensive
        message."""
        decision = SupervisorDecision(next_worker="qa_node", task_description="x", reasoning="x")
        monkeypatch.setattr(supervisor_module, "get_fast_llm", lambda **_kwargs: _FakeLLM(decision=decision))

        result = supervisor(self._no_trip_state(travel_state={}))

        assert result["routing_source"] != "needs_trip_first"

    def test_no_redirect_when_itinerary_was_not_what_was_asked_for(self, monkeypatch):
        """Nothing pending for `itinerary_node` — a pure question turn must
        stay reachable by `qa_node`."""
        decision = SupervisorDecision(next_worker="qa_node", task_description="x", reasoning="x")
        monkeypatch.setattr(supervisor_module, "get_fast_llm", lambda **_kwargs: _FakeLLM(decision=decision))

        result = supervisor(self._no_trip_state(pending_tasks=[]))

        assert result["next_worker"] == "qa_node"
        assert result["routing_source"] != "needs_trip_first"


# --- Empty-patch itinerary edit ----------------------------------------------
#
# Trace fdfad846-25d9-446b-8b88-ce4b7d015021: "ngày tôi không muốn đi vincom"
# extracted as `update_itinerary` with an empty changes list (no ALLOWED_PATHS
# entry fits "drop this place"), so `pending_tasks` was empty and the turn
# reached the unconstrained LLM branch, which answered it with `qa_node`.
# `qa_node` wrote a revised itinerary into the chat and saved nothing.


def _edit_turn_state(message: str = "ngày tôi không muốn đi vincom", **overrides):
    state = _state(
        messages=[HumanMessage(content=message)],
        intent="update_itinerary",
        pending_tasks=[],
        task_results=[],
        trip_data={"itineraries": [{}]},
        travel_state={"destination": {"presence": "set", "value": "Hà Nội"}},
    )
    state.update(overrides)
    return state


def test_edit_turn_rejects_qa_node_and_falls_back_to_edit_item(monkeypatch):
    decision = SupervisorDecision(next_worker="qa_node", task_description="answer", reasoning="x")
    monkeypatch.setattr(supervisor_module, "get_fast_llm", lambda **_kwargs: _FakeLLM(decision))

    message = "ngày tôi không muốn đi vincom"
    result = supervisor(_edit_turn_state(message))

    assert result["next_worker"] == "itinerary_node"
    assert result["routing_source"] == "itinerary_edit_intent"
    assert json.loads(result["task_description"]) == {"action": "edit_item", "user_request": message}


def test_edit_turn_keeps_the_llms_own_itinerary_action(monkeypatch):
    """The model still picks the action — only it can tell "lên lịch lại"
    (redo every day) from "bỏ Vincom" (touch one item)."""
    decision = SupervisorDecision(
        next_worker="itinerary_node", task_description="bỏ Vincom", reasoning="x", action="edit_item"
    )
    monkeypatch.setattr(supervisor_module, "get_fast_llm", lambda **_kwargs: _FakeLLM(decision))

    result = supervisor(_edit_turn_state())

    assert result["next_worker"] == "itinerary_node"
    assert result["routing_source"] == "supervisor"
    assert json.loads(result["task_description"]) == {"action": "edit_item", "user_request": "bỏ Vincom"}


def test_read_only_turn_still_reaches_qa_node(monkeypatch):
    """The guard is scoped to the edit intent: a question keeps its worker."""
    decision = SupervisorDecision(next_worker="qa_node", task_description="answer", reasoning="x")
    monkeypatch.setattr(supervisor_module, "get_fast_llm", lambda **_kwargs: _FakeLLM(decision))

    result = supervisor(_edit_turn_state(intent="hotel_search"))

    assert result["next_worker"] == "qa_node"


def test_edit_turn_without_trip_keeps_its_existing_paths(monkeypatch):
    """No trip yet: `itinerary_node` is impossible, so the guard must not
    fire and `qa_node` stays reachable."""
    decision = SupervisorDecision(next_worker="qa_node", task_description="answer", reasoning="x")
    monkeypatch.setattr(supervisor_module, "get_fast_llm", lambda **_kwargs: _FakeLLM(decision))

    result = supervisor(_edit_turn_state(trip_data={}))

    assert result["next_worker"] == "qa_node"


def test_edit_turn_does_not_reroute_after_itinerary_node_reported(monkeypatch):
    """`itinerary_node` already spoke this turn — re-delegating would replan
    the same request a second time."""
    decision = SupervisorDecision(next_worker="qa_node", task_description="answer", reasoning="x")
    monkeypatch.setattr(supervisor_module, "get_fast_llm", lambda **_kwargs: _FakeLLM(decision))

    result = supervisor(
        _edit_turn_state(task_results=[{"worker": "itinerary_node", "status": "ok", "reply": "Đã xoá."}])
    )

    assert result["next_worker"] == "qa_node"


# --- A hotel pick typed in chat ----------------------------------------------
#
# Same trace as `test_hotel_node.py`'s pick tests: `select_hotel` carries no
# ALLOWED_PATHS change, so `pending_tasks` is empty and the turn reaches the
# unconstrained LLM branch, where `qa_node` ("questions about the hotels
# already shown") is a plausible-looking answer that cannot select anything.


def test_select_hotel_intent_with_cards_on_screen_routes_to_hotel_node(monkeypatch):
    monkeypatch.setattr(supervisor_module, "get_fast_llm", _unreachable_llm_factory)

    state = _state(
        messages=[HumanMessage(content="chọn khách sạn số 1")],
        intent="select_hotel",
        pending_tasks=[],
        task_results=[],
        previous_hotel_options=[{"id": "h1", "name": "Horizon Hotel Apartment"}],
    )
    result = supervisor(state)

    assert result["next_worker"] == "hotel_node"
    assert result["routing_source"] == "select_hotel_intent"


def test_select_hotel_intent_without_cards_keeps_the_existing_paths(monkeypatch):
    """Nothing to pick FROM — the turn must not claim to be a pick."""
    decision = SupervisorDecision(next_worker="qa_node", task_description="answer", reasoning="x")
    monkeypatch.setattr(supervisor_module, "get_fast_llm", lambda **_kwargs: _FakeLLM(decision))

    state = _state(
        messages=[HumanMessage(content="chọn khách sạn số 1")],
        intent="select_hotel",
        pending_tasks=[],
        task_results=[],
        previous_hotel_options=[],
    )
    result = supervisor(state)

    assert result["routing_source"] != "select_hotel_intent"
