"""`POST /hotels/change` entering the graph at `hotel_node`.

The endpoint used to run a full turn on the hardcoded Vietnamese string
`"đổi khách sạn"`. That string carries no information: `hotel_node` reads
every input it needs from the already-committed `travel_state`. Pushing it
through `extract_patch` therefore buys nothing and risks something — an
extractor handed a bare instruction can invent a patch — besides ignoring
`session.language` outright.

Entering at `hotel_node` with `Command(goto=...)` skips `load_context ->
scope_guard -> extract_patch -> validate_patch -> apply_patch` while keeping
the four things a direct `hotel_node(state)` call would lose: the checkpointer
write, `enforce_contract`, `respond`'s payload, and `interrupt()`.

`update=load_context(...)` is mandatory, not decoration: it resets the 17
turn-scoped fields, and without it `respond` re-serves the previous turn's
`task_results`/`next_question`. Reusing the node function itself, rather than
copying the reset list, keeps one definition of "what belongs to a turn".

These started as the plan's gating spike (QĐ-3): LangGraph's docs warn that a
`Command` used as graph input can leave a graph "appearing stuck" by resuming
from the latest checkpoint instead of restarting. That warning is about
`update` without `goto`; these tests are what establish the `goto` form
actually behaves here.
"""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.messages import HumanMessage
from langgraph.types import Command

import src.agents.graph.graph as graph_module
import src.agents.graph.nodes.hotel_node as hotel_node_module
import src.agents.graph.nodes.supervisor as supervisor_module
import src.services.search_center as search_center_module
from src.agents.graph.nodes.load_context import load_context
from src.domain.travel_state import TravelState, apply_patch
from src.services.trip_scheduler import PlaceCandidate


def _seeded_travel_state(**extra: object) -> dict:
    changes = [
        {"path": "destination", "operation": "set", "value": "Đà Nẵng"},
        {"path": "people", "operation": "set", "value": 2},
        {"path": "dates.start", "operation": "set", "value": "2099-01-01"},
        {"path": "dates.end", "operation": "set", "value": "2099-01-05"},
        {"path": "budget.target", "operation": "set", "value": 1_000_000},
        {"path": "preferences.themes", "operation": "set", "value": None},
    ]
    for path, value in extra.items():
        changes.append({"path": path.replace("__", "."), "operation": "set", "value": value})
    return apply_patch(TravelState(), changes).state.to_dict()


def _option(id_: str) -> tuple[dict, PlaceCandidate]:
    data = {
        "id": id_,
        "destination_id": "dest-1",
        "name": f"Hotel {id_}",
        "star_rating": 4,
        "coordinates": "16.05,108.2",
        "matched_rooms": [],
        "covered_meals": [],
        "review_score": 8.0,
        "amenities": [],
        "similarity": 0.7,
    }
    return data, PlaceCandidate.from_mapping({**data, "category": "Hotel"})


class _FakeSupabaseClient:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def table(self, *_a, **_k):
        return self

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def ilike(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def execute(self):
        return type("Result", (), {"data": self._rows})()


@pytest.fixture
def graph_env(monkeypatch: pytest.MonkeyPatch):
    """A compiled graph whose hotel search succeeds, with `extract_patch` under
    a spy so "did this turn go through the extractor?" is answerable."""
    extractor_calls: list[dict] = []

    def _spying_extract_patch(state):
        # A stub, not the real extractor: the point of this fixture is to make
        # "was the extractor reached?" observable, and the real one would need
        # an LLM to answer a question these tests never ask. The patch it
        # returns routes the setup turn to `hotel_node`, so the thread ends up
        # holding a worker result that a later turn could leak.
        extractor_calls.append(dict(state))
        return {
            "patch": [{"path": "hotel_preferences.min_star_rating", "operation": "set", "value": 4}],
            "intent": "hotel_search",
        }

    def _unreachable_llm(*_a, **_k):
        raise AssertionError("this scenario must never call an LLM")

    monkeypatch.setattr(graph_module, "extract_patch", _spying_extract_patch)
    monkeypatch.setattr(supervisor_module, "get_fast_llm", _unreachable_llm)
    monkeypatch.setattr(hotel_node_module, "_get_destination_id", lambda _d: "dest-1")
    monkeypatch.setattr(
        hotel_node_module, "select_hotel_candidates", lambda *_a, **_k: [_option("h1")]
    )

    return type(
        "GraphEnv",
        (),
        {
            "app": graph_module.build_graph(),
            "extractor_calls": extractor_calls,
            "monkeypatch": monkeypatch,
        },
    )()


def _enter_at_hotel_node(app, config: dict) -> dict[str, Any]:
    """Exactly what `routes.py::change_hotel` does."""
    snapshot = app.get_state(config)
    return app.invoke(Command(goto="hotel_node", update=load_context(snapshot.values)), config=config)


def _establish_a_thread(app, config: dict, travel_state: dict | None = None) -> dict[str, Any]:
    """One ordinary turn, so the thread has a checkpoint to re-enter."""
    return app.invoke(
        {
            "session_id": "s1",
            "language": "vi",
            "travel_state": travel_state or _seeded_travel_state(),
            "messages": [HumanMessage(content="tìm khách sạn")],
        },
        config=config,
    )


class TestEntryPoint:
    def test_the_graph_runs_hotel_node_instead_of_appearing_stuck(self, graph_env):
        """The specific failure LangGraph's docs warn about: a `Command` input
        that resumes from the checkpoint and produces nothing."""
        config = {"configurable": {"thread_id": "change-runs"}}
        _establish_a_thread(graph_env.app, config)

        result = _enter_at_hotel_node(graph_env.app, config)

        assert result.get("response"), "no payload — the graph never reached `respond`"
        workers = [entry.get("worker") for entry in result.get("task_results") or []]
        assert "hotel_node" in workers

    def test_the_extractor_never_sees_this_turn(self, graph_env):
        """Asserted with a spy, not a stopwatch: the point is that no LLM gets
        the chance to invent a patch, not that the turn is fast."""
        config = {"configurable": {"thread_id": "change-skips-extract"}}
        _establish_a_thread(graph_env.app, config)
        graph_env.extractor_calls.clear()

        _enter_at_hotel_node(graph_env.app, config)

        assert graph_env.extractor_calls == []

    def test_the_payload_is_a_complete_response_not_a_stub(self, graph_env):
        config = {"configurable": {"thread_id": "change-payload"}}
        _establish_a_thread(graph_env.app, config)

        response = _enter_at_hotel_node(graph_env.app, config)["response"]

        assert response["reply"]
        assert response["stage"] in {"intake", "hotel_options", "planned", "error"}
        assert response["intake"] is not None

    def test_committed_travel_state_survives_the_re_entry(self, graph_env):
        """`Command(goto=...)` skips the `apply_patch` node; the facts the user
        already gave must not be dropped along with it."""
        config = {"configurable": {"thread_id": "change-keeps-state"}}
        _establish_a_thread(graph_env.app, config)

        result = _enter_at_hotel_node(graph_env.app, config)

        assert result["travel_state"]["destination"]["value"] == "Đà Nẵng"
        assert result["travel_state"]["people"]["value"] == 2


class TestTurnScopedReset:
    def test_the_turn_does_not_inherit_the_previous_question(self, graph_env):
        """Without `update=load_context(...)` this is the silent bug: the turn
        still returns 200, it just re-asks something already answered."""
        config = {"configurable": {"thread_id": "change-resets"}}
        _establish_a_thread(graph_env.app, config)

        result = _enter_at_hotel_node(graph_env.app, config)

        assert result.get("next_question") is None

    def test_the_turn_reports_only_its_own_worker_results(self, graph_env):
        """A stale `task_results` would make `respond` serve the PREVIOUS
        turn's reply as this turn's answer."""
        config = {"configurable": {"thread_id": "change-fresh-results"}}
        first = _establish_a_thread(graph_env.app, config)
        assert first.get("task_results"), "the setup turn produced no worker result to leak"

        result = _enter_at_hotel_node(graph_env.app, config)

        assert len(result["task_results"]) == 1
        assert result["task_results"][0]["worker"] == "hotel_node"


class TestInterruptStillWorks:
    def test_a_pause_inside_hotel_node_survives_this_entry_point(self, graph_env):
        """The whole reason this goes through the graph instead of calling
        `hotel_node(state)` as a function: the node can `interrupt()` to ask
        which center a radius search should use."""
        config = {"configurable": {"thread_id": "change-interrupt"}}
        _establish_a_thread(
            graph_env.app, config, travel_state=_seeded_travel_state(hotel_preferences__radius_km=3)
        )
        graph_env.monkeypatch.setattr(
            search_center_module, "get_supabase_client", lambda: _FakeSupabaseClient([])
        )

        paused = _enter_at_hotel_node(graph_env.app, config)

        assert "__interrupt__" in paused
        assert paused["__interrupt__"][0].value["kind"] == "hotel_radius_center"

    def test_the_pause_resumes_normally(self, graph_env):
        config = {"configurable": {"thread_id": "change-interrupt-resume"}}
        _establish_a_thread(
            graph_env.app, config, travel_state=_seeded_travel_state(hotel_preferences__radius_km=3)
        )
        graph_env.monkeypatch.setattr(
            search_center_module, "get_supabase_client", lambda: _FakeSupabaseClient([])
        )
        assert "__interrupt__" in _enter_at_hotel_node(graph_env.app, config)

        graph_env.monkeypatch.setattr(
            search_center_module,
            "get_supabase_client",
            lambda: _FakeSupabaseClient(
                [{"name": "Cầu Rồng", "latitude": 16.06, "longitude": 108.22}]
            ),
        )
        resumed = graph_env.app.invoke(Command(resume="Cầu Rồng"), config=config)

        assert "__interrupt__" not in resumed
        assert resumed.get("response")
