"""`CHECKPOINTER_BACKEND=postgres` — the branch that makes graph state outlive
the process.

This matters because of a deliberate trade-off (plan QĐ-2): with the default
memory checkpointer, a restart keeps the transcript (it is in Supabase) but
loses `travel_state`/`trip_data` (they are in the checkpointer). That degrade
was accepted on the condition that a real escape hatch exists — and until now
the Postgres branch (`main.py`'s lifespan) had never been executed by a test,
only read. An escape hatch nobody has walked through is a claim, not a hatch.

Skipped without `CHECKPOINTER_DATABASE_URL`, so CI on a machine with no
Postgres stays green rather than red-by-default.
"""

from __future__ import annotations

import os

import pytest
from langchain_core.messages import HumanMessage
from langgraph.types import Command

import src.agents.graph.graph as graph_module
import src.agents.graph.nodes.hotel_node as hotel_node_module
import src.agents.graph.nodes.supervisor as supervisor_module
import src.services.search_center as search_center_module
from src.domain.travel_state import TravelState, apply_patch

_DSN = os.environ.get("CHECKPOINTER_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not _DSN,
    reason="CHECKPOINTER_DATABASE_URL is not set — the Postgres checkpointer branch cannot run here",
)


class _FakeSupabaseClient:
    """Enough of the client for `search_center` to resolve (or fail to
    resolve) a named place, matching test_hotel_node.py's own stub."""

    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def rpc(self, *_args, **_kwargs):
        return self

    def table(self, *_args, **_kwargs):
        return self

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def ilike(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def execute(self):
        return type("Result", (), {"data": self._rows})()


def _seeded_travel_state() -> dict:
    return apply_patch(
        TravelState(),
        [
            {"path": "destination", "operation": "set", "value": "Đà Nẵng"},
            {"path": "people", "operation": "set", "value": 2},
            {"path": "dates.start", "operation": "set", "value": "2099-01-01"},
            {"path": "dates.end", "operation": "set", "value": "2099-01-05"},
            # budget.target is gated ahead of hotel_node (ask_slot -> supervisor);
            # without it the turn stops to ask for a budget and never reaches the
            # node that pauses. Same reason test_hotel_node.py seeds it.
            {"path": "budget.target", "operation": "set", "value": 1_000_000},
        ],
    ).state.to_dict()


@pytest.fixture
def postgres_checkpointer():
    """A real `PostgresSaver` over the configured DSN, set up like the app's
    own lifespan does."""
    from langgraph.checkpoint.postgres import PostgresSaver

    with PostgresSaver.from_conn_string(_DSN) as saver:
        saver.setup()
        yield saver


def _pause_the_graph(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drive `hotel_node` into its radius-without-a-center `interrupt()` —
    the one pause a real turn can reach today."""

    def _fake_extract_patch(_state):
        return {"patch": [{"path": "hotel_preferences.radius_km", "operation": "set", "value": 3}]}

    def _unreachable_llm(*_args, **_kwargs):
        raise AssertionError("this scenario must never call the LLM")

    monkeypatch.setattr(graph_module, "extract_patch", _fake_extract_patch)
    monkeypatch.setattr(supervisor_module, "get_fast_llm", _unreachable_llm)
    monkeypatch.setattr(hotel_node_module, "_get_destination_id", lambda _d: "dest-1")
    monkeypatch.setattr(search_center_module, "get_supabase_client", lambda: _FakeSupabaseClient([]))


def test_a_paused_thread_survives_a_process_restart(postgres_checkpointer, monkeypatch):
    """Pause on one compiled graph, resume on a completely different one built
    over the same DSN — which is what a redeploy looks like from the
    checkpointer's side. With the memory saver this is impossible by
    construction: the state died with the object.
    """
    _pause_the_graph(monkeypatch)
    thread_id = f"pg-restart-{os.getpid()}"
    config = {"configurable": {"thread_id": thread_id}}

    before_restart = graph_module.build_graph(checkpointer=postgres_checkpointer)
    paused = before_restart.invoke(
        {
            "session_id": thread_id,
            "language": "vi",
            "travel_state": _seeded_travel_state(),
            "messages": [HumanMessage(content="Tìm khách sạn trong bán kính 3km")],
        },
        config=config,
    )
    assert "__interrupt__" in paused

    # A different compiled graph object — same durable store behind it.
    after_restart = graph_module.build_graph(checkpointer=postgres_checkpointer)

    snapshot = after_restart.get_state(config)
    assert snapshot.interrupts, "the pause did not survive the restart"
    assert snapshot.values["travel_state"]["destination"]["value"] == "Đà Nẵng"

    monkeypatch.setattr(
        search_center_module,
        "get_supabase_client",
        lambda: _FakeSupabaseClient([{"name": "Cầu Rồng", "latitude": 16.06, "longitude": 108.22}]),
    )
    resumed = after_restart.invoke(Command(resume="Cầu Rồng"), config=config)

    assert "__interrupt__" not in resumed, "the resumed turn paused again instead of completing"


def test_graph_state_is_readable_from_a_fresh_graph_after_a_completed_turn(
    postgres_checkpointer, monkeypatch
):
    """The property `/restore` depends on: what a turn committed is still
    there for a graph built later in another process."""
    _pause_the_graph(monkeypatch)
    monkeypatch.setattr(
        search_center_module,
        "get_supabase_client",
        lambda: _FakeSupabaseClient([{"name": "Cầu Rồng", "latitude": 16.06, "longitude": 108.22}]),
    )
    thread_id = f"pg-committed-{os.getpid()}"
    config = {"configurable": {"thread_id": thread_id}}

    graph_module.build_graph(checkpointer=postgres_checkpointer).invoke(
        {
            "session_id": thread_id,
            "language": "vi",
            "travel_state": _seeded_travel_state(),
            "messages": [HumanMessage(content="Tìm khách sạn gần Cầu Rồng")],
        },
        config=config,
    )

    values = graph_module.build_graph(checkpointer=postgres_checkpointer).get_state(config).values

    assert values["travel_state"]["destination"]["value"] == "Đà Nẵng"
    assert values["travel_state"]["people"]["value"] == 2
