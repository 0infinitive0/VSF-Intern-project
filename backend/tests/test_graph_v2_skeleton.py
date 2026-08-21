"""Phase 5 (260812-0927-langgraph-orchestration-state-patch-and-interrupts):
topology, contract enforcement, and end-to-end shape tests for the
graph skeleton. Supervisor routing behavior itself is
covered by `test_supervisor_routing.py`.
"""

from __future__ import annotations

import inspect
import json
from collections import deque
from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver

import src.agents.graph.nodes.extract_patch as extract_patch_module
import src.agents.graph.nodes.hotel_node as hotel_node_module
import src.agents.graph.nodes.intake_qa as intake_qa_module
import src.agents.graph.nodes.supervisor as supervisor_module
import src.agents.graph.nodes.validate_patch as validate_patch_module
from src.agents.graph.contracts import CONTRACTS, ContractViolation, enforce_contract
from src.agents.graph.graph import NODE_NAMES, build_graph
from src.agents.graph.nodes.booking_node import booking_node
from src.agents.graph.nodes.qa_node import QA_TOOLS, build_qa_subgraph
from src.agents.graph.prompts import INTAKE_QA_NO_ANSWER_SENTINEL
from src.agents.graph.state import initial_graph_state
from src.models.schemas import PlannerChatResponse

# --- Topology ---------------------------------------------------------------


def test_every_declared_node_is_registered_and_reachable_from_start():
    app = build_graph()
    graph_repr = app.get_graph()

    for name in NODE_NAMES:
        assert name in graph_repr.nodes, f"{name} is declared but not registered"

    adjacency: dict[str, set[str]] = {}
    for edge in graph_repr.edges:
        adjacency.setdefault(edge.source, set()).add(edge.target)

    visited: set[str] = set()
    queue = deque(["__start__"])
    while queue:
        current = queue.popleft()
        if current in visited:
            continue
        visited.add(current)
        for target in adjacency.get(current, ()):
            if target not in visited:
                queue.append(target)

    unreachable = set(NODE_NAMES) - visited
    assert not unreachable, f"orphan node(s), unreachable from START: {unreachable}"
    assert "__end__" in visited, "no path reaches END"

    extra = set(graph_repr.nodes) - set(NODE_NAMES) - {"__start__", "__end__"}
    assert not extra, f"node registered but not declared in NODE_NAMES: {extra}"


def test_qa_node_has_exactly_one_outgoing_edge():
    app = build_graph()
    outgoing = [edge for edge in app.get_graph().edges if edge.source == "qa_node"]
    assert len(outgoing) == 1
    assert outgoing[0].target == "respond"


def test_intake_qa_has_two_outgoing_edges():
    """Phase 16 replaced the plain `intake_qa -> respond` edge with a
    conditional one (`routing.route_intake_qa`) -- both legs must still be
    reachable and the graph must still compile."""
    app = build_graph()
    targets = {edge.target for edge in app.get_graph().edges if edge.source == "intake_qa"}
    assert targets == {"respond", "supervisor"}


def test_only_validate_patch_and_hotel_node_call_interrupt():
    """Phase 7's standing constraint: `interrupt()` re-runs its WHOLE node
    from the start on every resume, so a node calling it must be pure (or
    idempotent) up to that call. Two nodes are granted that today:
    `validate_patch` (Phase 7, zero I/O up to its interrupt) and
    `hotel_node` (Phase 8, one read-only `attractions` lookup before its
    interrupt -- idempotent, not pure, see its module docstring for why
    that's the constraint that actually matters).

    Node modules are derived from `NODE_NAMES` (not hand-listed) so a future
    node is automatically covered instead of silently exempt."""
    import importlib

    interrupting_node_names = {"validate_patch", "hotel_node"}
    other_node_names = [name for name in NODE_NAMES if name not in interrupting_node_names]
    other_node_modules = [
        importlib.import_module(f"src.agents.graph.nodes.{name}") for name in other_node_names
    ]

    for module in other_node_modules:
        assert "interrupt(" not in inspect.getsource(module), f"{module.__name__} must not call interrupt()"

    assert "interrupt(" in inspect.getsource(validate_patch_module)
    assert "interrupt(" in inspect.getsource(hotel_node_module)

    forbidden = ("get_reasoning_llm", "get_fast_llm", "supabase", "httpx", "requests")
    validate_patch_source = inspect.getsource(validate_patch_module)
    for name in forbidden:
        assert name not in validate_patch_source, (
            f"validate_patch must stay pure up to interrupt() (no LLM/DB/API call) -- found {name!r}"
        )

    # hotel_node's own, looser bar: no LLM call anywhere (center resolution
    # never lets a model compute coordinates, doc §20), but a read-only
    # Supabase lookup before interrupt() is allowed -- see the module
    # docstring's idempotency argument.
    hotel_node_source = inspect.getsource(hotel_node_module)
    for name in ("get_reasoning_llm", "get_fast_llm", "httpx", "requests"):
        assert name not in hotel_node_source, f"hotel_node must never call an LLM -- found {name!r}"


# --- qa_node: reduced tool list + explicit checkpointer subgraph -----------


def test_qa_node_exposes_exactly_the_read_only_tools():
    names = {tool.name for tool in QA_TOOLS}
    # Phase 13 (`phase-13-place-search.md`) adds `search_places` -- still
    # read-only, no `select_place` (that pick is resolved via rebuild_day's
    # pause/resume, not a qa_node tool call; see qa_node.py's docstring).
    #
    # `get_hotel_options`/`get_trip_plan` are the two context readers: the
    # node could fetch ONE named hotel and could not see the itinerary at
    # all, so "which of these is cheapest?" and "what's on day 2?" had no
    # source to answer from. Both only read state the user is already
    # looking at, which is why the set grew without the contract below
    # changing.
    assert names == {
        "get_hotel_options",
        "get_trip_plan",
        "query_hotel",
        "query_hotel_rooms",
        "search_places",
    }
    assert not names & {"recommend_hotels", "select_hotel", "select_place", "modify_trip_plan"}


def test_qa_node_is_a_compiled_subgraph_with_an_explicit_checkpointer():
    checkpointer = MemorySaver()
    subgraph = build_qa_subgraph(checkpointer)
    assert subgraph.checkpointer is checkpointer


# --- Contracts ---------------------------------------------------------------


def test_qa_node_contract_declares_no_writes():
    assert CONTRACTS["qa_node"].writes == frozenset()


def test_enforce_contract_raises_when_a_node_writes_outside_its_contract():
    def _rogue_qa_node(state):
        # qa_node's contract writes nothing -- this node misbehaves by
        # mutating a hotel_preferences path it was never granted.
        travel_state = dict(state.get("travel_state") or {})
        travel_state["hotel_preferences.amenities"] = {"presence": "set", "value": ["pool"]}
        return {"travel_state": travel_state}

    wrapped = enforce_contract("qa_node", _rogue_qa_node)
    state = initial_graph_state("t1")

    with pytest.raises(ContractViolation):
        wrapped(state)


def test_enforce_contract_allows_a_write_within_the_declared_contract():
    def _compliant_hotel_node(state):
        travel_state = dict(state.get("travel_state") or {})
        travel_state["hotel_preferences.radius_km"] = {"presence": "set", "value": 5.0}
        # hotel_node also declares `emits_reply`, so a stand-in for it has to
        # speak like it does — see test_reply_contract.py for that obligation
        # on its own.
        return {
            "travel_state": travel_state,
            "task_results": [
                *(state.get("task_results") or []),
                {"worker": "hotel_node", "status": "ok", "reply": "Mình đã mở rộng bán kính tìm kiếm."},
            ],
        }

    wrapped = enforce_contract("hotel_node", _compliant_hotel_node)
    state = initial_graph_state("t1")

    result = wrapped(state)
    assert result["travel_state"]["hotel_preferences.radius_km"]["value"] == 5.0


# --- booking_node: explicit decline, never a silent pass-through -----------


def test_booking_node_declines_explicitly():
    state = initial_graph_state("t1")
    result = booking_node(state)

    assert result["task_results"][-1]["worker"] == "booking_node"
    assert result["task_results"][-1]["status"] == "declined"
    assert result["task_results"][-1]["reply"]  # non-empty — never a silent pass-through


def test_booking_node_replies_in_english_when_requested():
    state = initial_graph_state("t1")
    state["language"] = "en"
    result = booking_node(state)
    assert "book" in result["task_results"][-1]["reply"].lower()


# --- End-to-end: the graph returns a valid PlannerChatResponse ------------


def test_graph_completes_a_turn_end_to_end_and_returns_a_planner_chat_response(monkeypatch):
    """`extract_patch` (Phase 6) now runs for real, so both its LLM call and
    the supervisor's are forced to fail here -- `extract_patch` falls back to
    an empty patch/`general_question` on its own (never raises out), which
    keeps `pending_tasks` empty at the supervisor exactly as the Phase 5
    stub did, exercising the same `workers == [] -> "respond"` fallback
    deterministically, with no real model or network call anywhere in the
    turn."""

    def _raise(*_args, **_kwargs):
        raise RuntimeError("no LLM in this test")

    monkeypatch.setattr(supervisor_module, "get_fast_llm", _raise)
    monkeypatch.setattr(extract_patch_module, "get_reasoning_llm", _raise)
    monkeypatch.setattr(extract_patch_module, "_get_destination_names", lambda: ())

    app = build_graph()
    result = app.invoke(
        {
            "session_id": "turn-1",
            "language": "vi",
            "messages": [HumanMessage(content="Chào bạn")],
        },
        config={"configurable": {"thread_id": "test-e2e-thread"}},
    )

    assert "response" in result
    response = PlannerChatResponse(**result["response"])
    assert response.session_id == "turn-1"
    assert response.reply
    assert response.stage == "intake"


def test_graph_routes_a_completed_worker_through_budget_check_to_respond(monkeypatch):
    """Drives `hotel_node -> all_tasks_done(True) -> budget_check ->
    respond` through the real compiled graph, not just at the node-function
    level -- proving `budget_check` actually executes and the frozen
    response still gets built afterward.

    This substitutes `extract_patch` for one call so the test controls
    exactly what patch reaches `ask_slot`'s Phase 7 slot gate. Every OTHER
    required slot (destination/people/dates/preferences) is pre-seeded
    directly in the invoke's starting `travel_state` (not via the patch),
    preferences as an explicit opt-out, so the gate lets
    the turn through to the supervisor instead of stopping to ask for one of
    them first, while the patch itself still only sets `budget.max` -- the
    ONE change that maps to a single workflow (`hotel`) in `IMPACT_MAP`, so
    this also exercises the supervisor's fast path (zero LLM calls) rather
    than the LLM path.

    `hotel_node` does real work since Phase 8, so its two Supabase-touching
    calls (`_get_destination_id`, `select_hotel_candidates`) are stubbed --
    this test is about the `budget_check`/`respond` wiring around it, not
    hotel search correctness (see `test_hotel_node.py` for that).
    """
    import src.agents.graph.graph as graph_module
    from src.domain.travel_state import TravelState, apply_patch

    def _fake_extract_patch(_state):
        return {"patch": [{"path": "budget.max", "operation": "set", "value": 5000000}]}

    def _unreachable(*_args, **_kwargs):
        raise AssertionError("fast path must not call the LLM")

    monkeypatch.setattr(graph_module, "extract_patch", _fake_extract_patch)
    monkeypatch.setattr(supervisor_module, "get_fast_llm", _unreachable)
    monkeypatch.setattr(hotel_node_module, "_get_destination_id", lambda _destination: "dest-1")
    monkeypatch.setattr(hotel_node_module, "select_hotel_candidates", lambda *_args, **_kwargs: [])

    seeded_state = apply_patch(
        TravelState(),
        [
            {"path": "destination", "operation": "set", "value": "Đà Nẵng"},
            {"path": "people", "operation": "set", "value": 2},
            {"path": "dates.start", "operation": "set", "value": "2099-01-01"},
            {"path": "dates.end", "operation": "set", "value": "2099-01-05"},
            {"path": "preferences.themes", "operation": "set", "value": None},
        ],
    ).state

    app = graph_module.build_graph()
    result = app.invoke(
        {
            "session_id": "turn-budget",
            "language": "vi",
            "travel_state": seeded_state.to_dict(),
            "messages": [HumanMessage(content="Ngân sách tối đa 5 triệu")],
        },
        config={"configurable": {"thread_id": "test-budget-check-thread"}},
    )

    assert result["pending_tasks"] == []
    assert result["task_results"][-1]["worker"] == "hotel_node"
    assert result["task_results"][-1]["status"] == "no_results"
    assert result["routing_source"] == "impact_map"  # fast path, not the LLM

    response = PlannerChatResponse(**result["response"])
    assert response.reply  # respond ran and built the frozen shape after budget_check


def test_read_only_nearby_turn_skips_budget_check_and_keeps_its_pins(monkeypatch):
    """Regression for the code-review finding on the nearby-places fix
    (`plans/260819-1627-route-nearby-places-questions-to-itinerary-node`):
    `itinerary_node -> all_tasks_done(True) -> budget_check` is the normal
    edge for a real edit, but `budget_check` re-plans (hotel search +
    unlocked-day rebuild) whenever `budget.trip_total` is set, and
    `response_payload.suggested_places_from_task_results` reads only
    `task_results[-1]` -- so routing a read-only `list_nearby` turn through
    that same edge would silently erase the very pins this fix exists to
    produce (and, on an over-budget session, rebuild the plan behind the
    user's back). This drives the real compiled graph end to end with
    `budget.trip_total` SET and asserts `itinerary_node`'s result is what
    `respond` actually sees.
    """
    import src.agents.graph.graph as graph_module
    import src.agents.graph.nodes.itinerary_node as itinerary_node_module
    from src.domain.travel_state import TravelState, apply_patch

    def _fake_extract_patch(_state):
        return {"intent": "general_question", "patch": [], "asks_nearby_places": True}

    def _unreachable(*_args, **_kwargs):
        raise AssertionError("read-only nearby branch must not call the LLM")

    fake_candidate = SimpleNamespace(
        id="place-1",
        name="Bãi biển Mỹ Khê",
        category="beach",
        coordinates="16.06,108.25",
        description="Bãi biển nổi tiếng",
        rating=4.5,
    )

    monkeypatch.setattr(graph_module, "extract_patch", _fake_extract_patch)
    monkeypatch.setattr(supervisor_module, "get_fast_llm", _unreachable)
    monkeypatch.setattr(
        itinerary_node_module, "search_attraction_candidates", lambda *_a, **_kw: [fake_candidate]
    )

    seeded_state = apply_patch(
        TravelState(),
        [
            {"path": "destination", "operation": "set", "value": "Đà Nẵng"},
            {"path": "people", "operation": "set", "value": 2},
            {"path": "dates.start", "operation": "set", "value": "2099-01-01"},
            {"path": "dates.end", "operation": "set", "value": "2099-01-05"},
            {"path": "budget.trip_total", "operation": "set", "value": 5000000},
            # Already-derived range, as a real session would have by the
            # time a later turn asks a nearby-places question -- otherwise
            # `validate_patch._derive_budget_range_from_trip_total` derives
            # a fresh budget.min/max THIS turn even with an empty `patch`,
            # which impacts the hotel workflow and defeats the "workers
            # empty" precondition this test means to exercise.
            {"path": "budget.min", "operation": "set", "value": 800000},
            {"path": "budget.max", "operation": "set", "value": 1200000},
            {"path": "preferences.themes", "operation": "set", "value": None},
        ],
    ).state

    app = graph_module.build_graph()
    result = app.invoke(
        {
            "session_id": "turn-nearby",
            "language": "vi",
            "travel_state": seeded_state.to_dict(),
            "trip_data": {"hotel": {"coordinates": "16.06,108.22", "destination_id": "dest-1"}},
            "messages": [HumanMessage(content="liệt kê các địa điểm nổi bật trong vòng bán kính 3km")],
        },
        config={"configurable": {"thread_id": "test-nearby-budget-thread"}},
    )

    assert result["routing_source"] == "read_only_intent_nearby"
    # budget_check never ran: the last (and only new) task_results entry is
    # itinerary_node's own, not a "budget_check" one appended after it.
    assert [entry["worker"] for entry in result["task_results"]] == ["itinerary_node"]
    assert result["task_results"][-1]["suggested_places"] == [
        {
            "id": "place-1",
            "name": "Bãi biển Mỹ Khê",
            "category": "beach",
            "coordinates": "16.06,108.25",
            "description": "Bãi biển nổi tiếng",
            "rating": 4.5,
        }
    ]
    # trip_data/hotel is untouched -- no re-plan happened.
    assert result["trip_data"]["hotel"]["coordinates"] == "16.06,108.22"

    response = PlannerChatResponse(**result["response"])
    assert response.reply


def test_nearby_before_the_pick_anchors_on_the_numbered_hotel_card(monkeypatch):
    """"tìm quanh khách sạn số 2" while the shortlist is still on screen.

    No `trip_data` exists at this stage, which used to route the turn to
    `qa_node` and leave the map empty. The search must now center on the
    SECOND card's coordinates -- not the first, and not the destination
    centroid -- and the stage must stay `hotel_options` so the cards the
    user is choosing between do not disappear underneath the answer.
    """
    import src.agents.graph.graph as graph_module
    import src.agents.graph.nodes.itinerary_node as itinerary_node_module
    from src.domain.travel_state import TravelState, apply_patch

    def _fake_extract_patch(_state):
        return {"intent": "general_question", "patch": [], "asks_nearby_places": True}

    def _unreachable(*_args, **_kwargs):
        raise AssertionError("read-only nearby branch must not call the LLM")

    fake_candidate = SimpleNamespace(
        id="place-9",
        name="Hidden Gem Coffee",
        category="Restaurants & cafes",
        coordinates="21.03,105.85",
        description=None,
        rating=4.6,
    )
    search_calls: list[dict] = []

    def _fake_search(query, destination_id, **kwargs):
        search_calls.append({"query": query, "destination_id": destination_id, **kwargs})
        return [fake_candidate]

    monkeypatch.setattr(graph_module, "extract_patch", _fake_extract_patch)
    monkeypatch.setattr(supervisor_module, "get_fast_llm", _unreachable)
    monkeypatch.setattr(itinerary_node_module, "search_attraction_candidates", _fake_search)
    monkeypatch.setattr(itinerary_node_module, "_get_destination_id", lambda _name: "dest-hn")

    seeded_state = apply_patch(
        TravelState(),
        [
            {"path": "destination", "operation": "set", "value": "Hà Nội"},
            {"path": "people", "operation": "set", "value": 2},
            {"path": "dates.start", "operation": "set", "value": "2099-03-01"},
            {"path": "dates.end", "operation": "set", "value": "2099-03-04"},
            # Budget seeded (and its range already derived) for the same
            # reason the budget test above does it: an unanswered budget slot
            # sends the turn to `ask_slot` instead of the supervisor, and a
            # fresh derivation would impact the hotel workflow this turn.
            {"path": "budget.trip_total", "operation": "set", "value": 5000000},
            {"path": "budget.min", "operation": "set", "value": 800000},
            {"path": "budget.max", "operation": "set", "value": 1200000},
            {"path": "preferences.themes", "operation": "set", "value": None},
        ],
    ).state

    app = graph_module.build_graph()
    result = app.invoke(
        {
            "session_id": "turn-nearby-shortlist",
            "language": "vi",
            "travel_state": seeded_state.to_dict(),
            "previous_hotel_options": [
                {"id": "h1", "name": "Khách sạn A", "coordinates": "21.00,105.80"},
                {"id": "h2", "name": "Khách sạn B", "coordinates": "21.02,105.84"},
            ],
            "messages": [HumanMessage(content="tìm quanh khách sạn số 2 trong bán kính 3km")],
        },
        config={"configurable": {"thread_id": "test-nearby-shortlist-thread"}},
    )

    assert result["routing_source"] == "read_only_intent_nearby"
    assert [entry["worker"] for entry in result["task_results"]] == ["itinerary_node"]
    assert search_calls == [
        {
            "query": "tìm quanh khách sạn số 2 trong bán kính 3km",
            "destination_id": "dest-hn",
            "match_count": 8,
            "root_latitude": 21.02,
            "root_longitude": 105.84,
            "max_radius_km": 3.0,
        }
    ]
    assert result["task_results"][-1]["suggested_places"][0]["id"] == "place-9"

    response = PlannerChatResponse(**result["response"])
    # The reply names which card was measured from: with several on screen,
    # "quanh khách sạn" alone would not say which one the list belongs to.
    assert "số 2" in response.reply and "Khách sạn B" in response.reply
    # The pins reach the payload, which is the whole point of routing here
    # instead of to `qa_node` (whose tools cannot write this field at all).
    assert [place.id for place in response.suggested_places] == ["place-9"]


def test_nearby_before_the_pick_asks_which_card_when_no_number_is_given(monkeypatch):
    """Several cards on screen and no number in the message: the graph has
    no way to know which hotel is meant (the card the user is looking at is
    frontend-local state), so it asks instead of answering about hotel 1.
    """
    import src.agents.graph.graph as graph_module
    import src.agents.graph.nodes.itinerary_node as itinerary_node_module
    from src.domain.travel_state import TravelState, apply_patch

    def _fake_extract_patch(_state):
        return {"intent": "general_question", "patch": [], "asks_nearby_places": True}

    def _unreachable(*_args, **_kwargs):
        raise AssertionError("an ambiguous anchor must never reach the place search")

    monkeypatch.setattr(graph_module, "extract_patch", _fake_extract_patch)
    monkeypatch.setattr(supervisor_module, "get_fast_llm", _unreachable)
    monkeypatch.setattr(itinerary_node_module, "search_attraction_candidates", _unreachable)

    seeded_state = apply_patch(
        TravelState(),
        [
            {"path": "destination", "operation": "set", "value": "Hà Nội"},
            {"path": "people", "operation": "set", "value": 2},
            {"path": "dates.start", "operation": "set", "value": "2099-03-01"},
            {"path": "dates.end", "operation": "set", "value": "2099-03-04"},
            # Budget seeded (and its range already derived) for the same
            # reason the budget test above does it: an unanswered budget slot
            # sends the turn to `ask_slot` instead of the supervisor, and a
            # fresh derivation would impact the hotel workflow this turn.
            {"path": "budget.trip_total", "operation": "set", "value": 5000000},
            {"path": "budget.min", "operation": "set", "value": 800000},
            {"path": "budget.max", "operation": "set", "value": 1200000},
            {"path": "preferences.themes", "operation": "set", "value": None},
        ],
    ).state

    app = graph_module.build_graph()
    result = app.invoke(
        {
            "session_id": "turn-nearby-ambiguous",
            "language": "vi",
            "travel_state": seeded_state.to_dict(),
            "previous_hotel_options": [
                {"id": "h1", "name": "Khách sạn A", "coordinates": "21.00,105.80"},
                {"id": "h2", "name": "Khách sạn B", "coordinates": "21.02,105.84"},
            ],
            "messages": [HumanMessage(content="quanh khách sạn có quán cà phê nào không")],
        },
        config={"configurable": {"thread_id": "test-nearby-ambiguous-thread"}},
    )

    assert result["task_results"][-1]["status"] == "error"
    assert "số mấy" in result["task_results"][-1]["reply"]
    assert not result["task_results"][-1].get("suggested_places")


# --- End-to-end: clarify branch for an incomplete edit (Phase 16) ----------
#
# The extractor is faked at the node level in every case below so
# `patch_reason` is a controlled state value -- guard 2 is exercised
# deterministically, not as an inference about real model behavior (see
# plan.md's "Decided while planning" table). `intake_qa` itself runs for
# real wherever it's reached (only its LLM call is stubbed), so its own
# sentinel/exception handling and `routing.route_intake_qa`'s two-callers
# logic both run for real too -- only the two model calls this phase's plan
# names are ever stubbed.


class _FakeQaResponse:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeQaLLM:
    """One canned response or exception per call -- every intake_qa/
    extract_patch call site in these tests invokes its model exactly once."""

    def __init__(self, content: str | Exception) -> None:
        self._content = content

    def invoke(self, _prompt: str) -> _FakeQaResponse:
        if isinstance(self._content, Exception):
            raise self._content
        return _FakeQaResponse(self._content)


class _FakeSupervisorStructuredLLM:
    def __init__(self, decision) -> None:
        self._decision = decision

    def invoke(self, _prompt):
        return self._decision


class _FakeSupervisorLLM:
    def __init__(self, decision) -> None:
        self._decision = decision

    def with_structured_output(self, _model):
        return _FakeSupervisorStructuredLLM(self._decision)


def _all_slots_set_travel_state() -> dict:
    """destination/people/dates/budget all answered -- `ask_slot` returns
    empty `missing_slots`, clearing the first guard `route_ask_slot`'s
    post-intake branch checks."""
    from src.domain.travel_state import TravelState, apply_patch

    changes = [
        {"path": "destination", "operation": "set", "value": "Đà Nẵng"},
        {"path": "people", "operation": "set", "value": 2},
        {"path": "dates.start", "operation": "set", "value": "2099-01-01"},
        {"path": "dates.end", "operation": "set", "value": "2099-01-05"},
        {"path": "budget.target", "operation": "set", "value": None},  # explicit "no preference"
        {"path": "preferences.themes", "operation": "set", "value": None},  # ditto, the other skippable slot
    ]
    return apply_patch(TravelState(), changes).state.to_dict()


def _fake_itinerary_node(state):
    pending = [worker for worker in (state.get("pending_tasks") or []) if worker != "itinerary_node"]
    return {
        "trip_data": {"destination": "Đà Nẵng"},
        "pending_tasks": pending,
        "task_results": [
            *(state.get("task_results") or []),
            {"worker": "itinerary_node", "status": "ok", "reply": "Đã cập nhật kế hoạch."},
        ],
    }


def test_incomplete_edit_asks_the_missing_value_instead_of_a_generic_ack(monkeypatch, caplog):
    """Case 1: `đổi theme ngày 1` on a built trip with every slot already
    answered. `patch_reason == "missing_value"` routes to `intake_qa`
    instead of falling through to the supervisor's free pick, and
    `intake_qa`'s question becomes the reply -- not the generic-ack ERROR
    branch, not a worker bailing out with nothing to show."""
    import src.agents.graph.graph as graph_module

    def _fake_extract_patch(_state):
        return {"patch": [], "intent": "update_itinerary", "patch_reason": "missing_value"}

    monkeypatch.setattr(graph_module, "extract_patch", _fake_extract_patch)
    monkeypatch.setattr(
        intake_qa_module,
        "get_fast_llm",
        lambda **_kwargs: _FakeQaLLM("Ngày 1 bạn muốn theo hướng biển, thiên nhiên hay văn hoá?"),
    )

    app = graph_module.build_graph()
    with caplog.at_level("ERROR"):
        result = app.invoke(
            {
                "session_id": "turn-clarify",
                "language": "vi",
                "travel_state": _all_slots_set_travel_state(),
                "trip_data": {"destination": "Đà Nẵng"},
                "messages": [HumanMessage(content="đổi theme ngày 1")],
            },
            config={"configurable": {"thread_id": "test-clarify-thread"}},
        )

    assert result["response"]["reply"] == "Ngày 1 bạn muốn theo hướng biển, thiên nhiên hay văn hoá?"
    assert result["response"]["stage"] == "planned"
    assert result["task_results"] == []
    assert "fell through to the generic ack" not in caplog.text


def test_the_followup_answer_to_a_clarify_question_lands_on_the_day_it_answers(monkeypatch):
    """Case 2, chained on the same thread as case 1's exact scenario. The
    reply is an ORDINARY turn -- real `extract_patch`, only its LLM
    stubbed -- proving the design's "no new interrupt state" claim rather
    than assuming it.

    A bare "biển" names no day itself; with no anchor at all, this would
    land as a trip-wide `preferences.themes` change instead of the day that
    was actually asked about -- Phase 2's own test plan anticipated exactly
    this possibility ("if the bare reply does not extract to the day path
    on its own, record it as a finding and raise it"), and it was real
    (verified in code review). `pending_clarify_day` (Phase 16, module
    docstring of `extract_patch.py`) closes it: turn 1 persists the day the
    clarify question was about, turn 2 falls back to it since "biển" itself
    names none.
    """
    import src.agents.graph.graph as graph_module

    saver = MemorySaver()
    thread = {"configurable": {"thread_id": "test-clarify-then-followup"}}
    seeded_travel_state = _all_slots_set_travel_state()

    def _fake_extract_patch_turn1(_state):
        return {
            "patch": [],
            "intent": "update_itinerary",
            "patch_reason": "missing_value",
            "pending_clarify_day": 1,
        }

    monkeypatch.setattr(graph_module, "extract_patch", _fake_extract_patch_turn1)
    monkeypatch.setattr(intake_qa_module, "get_fast_llm", lambda **_kwargs: _FakeQaLLM("Ngày 1 bạn muốn gì?"))

    app_turn1 = graph_module.build_graph(checkpointer=saver)
    turn1 = app_turn1.invoke(
        {
            "session_id": "turn-clarify",
            "language": "vi",
            "travel_state": seeded_travel_state,
            "trip_data": {"destination": "Đà Nẵng"},
            "messages": [HumanMessage(content="đổi theme ngày 1")],
        },
        config=thread,
    )
    assert turn1["pending_clarify_day"] == 1

    # Turn 2: restore the real extract_patch, stub only the LLM call under it
    # -- the day-scope rewrite and the pending_clarify_day read/clear both
    # run for real.
    monkeypatch.setattr(graph_module, "extract_patch", extract_patch_module.extract_patch)
    fake_response = json.dumps(
        {
            "intent": "update_itinerary",
            "changes": [{"path": "preferences.themes", "operation": "set", "value": ["biển"]}],
        }
    )
    monkeypatch.setattr(extract_patch_module, "get_reasoning_llm", lambda **_kwargs: _FakeQaLLM(fake_response))
    monkeypatch.setattr(extract_patch_module, "_get_destination_names", lambda: ())
    monkeypatch.setattr(graph_module, "itinerary_node", _fake_itinerary_node)
    decision = supervisor_module.SupervisorDecision(next_worker="itinerary_node", task_description="x", reasoning="x")
    monkeypatch.setattr(supervisor_module, "get_fast_llm", lambda **_kwargs: _FakeSupervisorLLM(decision))

    app_turn2 = graph_module.build_graph(checkpointer=saver)
    result = app_turn2.invoke({"messages": [HumanMessage(content="biển")]}, config=thread)

    # daily_preferences.<day>.theme is a free-text string, not a label list
    # -- the rewrite joins preferences.themes' list value so it survives
    # _validate_daily_theme instead of being silently rejected.
    assert result["travel_state"]["daily_preferences.1.theme"]["value"] == "biển"
    # Seeded as an explicit opt-out (NOT_APPLICABLE) by
    # `_all_slots_set_travel_state`; a trip-wide themes change would flip it
    # to SET, which is exactly the leak this asserts against.
    assert result["travel_state"]["preferences.themes"]["presence"] != "set"
    assert result["pending_clarify_day"] is None  # consumed, doesn't leak to a third turn
    assert result["task_results"][-1]["worker"] == "itinerary_node"


def test_reason_no_change_skips_intake_qa_entirely_and_reaches_a_worker(monkeypatch):
    """Case 3, guard 2's own regression pin: `lên lịch lại` clears guard 1
    (an included intent) but `reason: "no_change"` stops it before
    `intake_qa` is ever invoked -- the one call `reason` was built to save.
    `intake_qa` explodes if reached, so this is a hard assertion, not an
    inference from the final reply."""
    import src.agents.graph.graph as graph_module

    def _fake_extract_patch(_state):
        return {"patch": [], "intent": "update_itinerary", "patch_reason": "no_change"}

    def _unreachable_intake_qa(_state):
        raise AssertionError("guard 2 must stop this turn before intake_qa ever runs")

    decision = supervisor_module.SupervisorDecision(
        next_worker="itinerary_node", task_description="redo", reasoning="x"
    )

    monkeypatch.setattr(graph_module, "extract_patch", _fake_extract_patch)
    monkeypatch.setattr(graph_module, "intake_qa", _unreachable_intake_qa)
    monkeypatch.setattr(graph_module, "itinerary_node", _fake_itinerary_node)
    monkeypatch.setattr(supervisor_module, "get_fast_llm", lambda **_kwargs: _FakeSupervisorLLM(decision))

    app = graph_module.build_graph()
    result = app.invoke(
        {
            "session_id": "turn-no-change",
            "language": "vi",
            "travel_state": _all_slots_set_travel_state(),
            "trip_data": {"destination": "Đà Nẵng"},
            "messages": [HumanMessage(content="lên lịch lại")],
        },
        config={"configurable": {"thread_id": "test-no-change-thread"}},
    )

    assert result["routing_source"] == "supervisor"
    assert result["task_results"][-1]["worker"] == "itinerary_node"
    assert result["response"]["reply"] == result["task_results"][-1]["reply"]


def test_intake_qa_no_answer_post_intake_routes_to_supervisor_not_the_generic_ack(monkeypatch, caplog):
    """Case 4, guard 3: `is_incomplete_edit` correctly decided this turn was
    worth asking about, but `intake_qa` declined -- its own NO_ANSWER
    sentinel, exercised for real here (only its LLM is stubbed). There is
    no pending question to fall back on post-intake, so `route_intake_qa`
    must not let this land on `_compose(None, None) -> None` and the
    generic-ack ERROR branch; it goes to `supervisor` instead."""
    import src.agents.graph.graph as graph_module

    def _fake_extract_patch(_state):
        return {"patch": [], "intent": "update_itinerary", "patch_reason": "missing_value"}

    decision = supervisor_module.SupervisorDecision(next_worker="itinerary_node", task_description="x", reasoning="x")

    monkeypatch.setattr(graph_module, "extract_patch", _fake_extract_patch)
    monkeypatch.setattr(intake_qa_module, "get_fast_llm", lambda **_kwargs: _FakeQaLLM(INTAKE_QA_NO_ANSWER_SENTINEL))
    monkeypatch.setattr(graph_module, "itinerary_node", _fake_itinerary_node)
    monkeypatch.setattr(supervisor_module, "get_fast_llm", lambda **_kwargs: _FakeSupervisorLLM(decision))

    app = graph_module.build_graph()
    with caplog.at_level("ERROR"):
        result = app.invoke(
            {
                "session_id": "turn-no-answer",
                "language": "vi",
                "travel_state": _all_slots_set_travel_state(),
                "trip_data": {"destination": "Đà Nẵng"},
                "messages": [HumanMessage(content="đổi theme ngày 1")],
            },
            config={"configurable": {"thread_id": "test-guard3-no-answer-thread"}},
        )

    assert result["intake_answer"] is None
    assert result["routing_source"] == "supervisor"
    assert "fell through to the generic ack" not in caplog.text
    assert result["response"]["reply"]


def test_intake_qa_raising_post_intake_routes_to_supervisor_and_the_turn_completes(monkeypatch, caplog):
    """Case 5, guard 3's other trigger: intake_qa's LLM call fails outright.
    Its own `except Exception` (nodes/intake_qa.py) already returns
    `{"intake_answer": None}` rather than propagating -- exercised for real
    here, proving the graph-level consequence is identical to a decline,
    not a crashed turn."""
    import src.agents.graph.graph as graph_module

    def _fake_extract_patch(_state):
        return {"patch": [], "intent": "update_itinerary", "patch_reason": "missing_value"}

    decision = supervisor_module.SupervisorDecision(next_worker="itinerary_node", task_description="x", reasoning="x")

    monkeypatch.setattr(graph_module, "extract_patch", _fake_extract_patch)
    monkeypatch.setattr(intake_qa_module, "get_fast_llm", lambda **_kwargs: _FakeQaLLM(RuntimeError("provider down")))
    monkeypatch.setattr(graph_module, "itinerary_node", _fake_itinerary_node)
    monkeypatch.setattr(supervisor_module, "get_fast_llm", lambda **_kwargs: _FakeSupervisorLLM(decision))

    app = graph_module.build_graph()
    with caplog.at_level("ERROR"):
        result = app.invoke(
            {
                "session_id": "turn-raises",
                "language": "vi",
                "travel_state": _all_slots_set_travel_state(),
                "trip_data": {"destination": "Đà Nẵng"},
                "messages": [HumanMessage(content="đổi theme ngày 1")],
            },
            config={"configurable": {"thread_id": "test-guard3-raises-thread"}},
        )

    assert result["intake_answer"] is None
    assert result["routing_source"] == "supervisor"
    assert "fell through to the generic ack" not in caplog.text
    assert result["response"]["reply"]


def test_budget_check_goes_straight_to_respond():
    """Nothing sits between the worker completion check and the assembler:
    the text `budget_check` hands on carries real prices and counts, and
    every node that could rewrite it on the way is one that could rewrite a
    number."""
    graph_repr = build_graph().get_graph()

    budget_targets = {edge.target for edge in graph_repr.edges if edge.source == "budget_check"}
    assert budget_targets == {"respond"}
