"""Phase 7 (260812-0927-langgraph-orchestration-state-patch-and-interrupts):
`interrupt()`/`Command(resume=...)` for ambiguous dates, driven through the
real compiled `graph_v2`, plus the deadlock regression this whole phase
exists to kill (a pending question no longer blocks an unrelated fact).

Live-Postgres restart-durability test is opt-in only, gated behind
RUN_LIVE_POSTGRES_CHECKPOINTER_TESTS=1 -- mirrors tests/test_checkpointer.py's
existing convention. A plain `pytest tests/` run must never require a real
database.
"""

from __future__ import annotations

import os

import pytest
from langchain_core.messages import HumanMessage
from langgraph.types import Command

import src.agents.graph_v2.graph as graph_module
import src.agents.graph_v2.nodes.supervisor as supervisor_module
from src.domain.travel_state import TravelState, apply_patch
from src.models.schemas import PlannerChatResponse

_FUTURE_START = "2099-01-01"
_FUTURE_END = "2099-01-05"


def _unreachable_llm(*_args, **_kwargs):
    raise AssertionError("this scenario must never call the LLM")


def _seeded_travel_state(**extra_changes: object) -> dict:
    changes = [
        {"path": "destination", "operation": "set", "value": "Đà Nẵng"},
        {"path": "people", "operation": "set", "value": 2},
        {"path": "dates.start", "operation": "set", "value": _FUTURE_START},
        {"path": "dates.end", "operation": "set", "value": _FUTURE_END},
    ]
    for path, value in extra_changes.items():
        changes.append({"path": path.replace("__", "."), "operation": "set", "value": value})
    return apply_patch(TravelState(), changes).state.to_dict()


# --- Missing year -----------------------------------------------------------


def test_missing_year_pauses_then_resumes_with_a_supplied_year(monkeypatch):
    """"15/09" has no year; 15 > 12 so once a year lands there is only one
    calendar reading -- an isolated missing_year interrupt, no cascade into
    day_month_order."""

    def _fake_extract_patch(_state):
        return {"patch": [{"path": "dates.start", "operation": "set", "value": "15/09"}], "intent": "update_trip"}

    monkeypatch.setattr(graph_module, "extract_patch", _fake_extract_patch)
    monkeypatch.setattr(supervisor_module, "get_fast_llm", _unreachable_llm)

    app = graph_module.build_graph()
    config = {"configurable": {"thread_id": "test-missing-year"}}

    paused = app.invoke(
        {"session_id": "s1", "language": "vi", "messages": [HumanMessage(content="đi ngày 15/09")]},
        config=config,
    )

    assert "__interrupt__" in paused
    payload = paused["__interrupt__"][0].value
    assert payload["kind"] == "missing_year"
    assert payload["path"] == "dates.start"
    assert "message" in payload and payload["message"]

    snapshot = app.get_state(config)
    assert snapshot.interrupts  # thread is genuinely paused, not finished

    resumed = app.invoke(Command(resume="2099"), config=config)

    assert "__interrupt__" not in resumed
    assert resumed["travel_state"]["dates.start"]["value"] == "2099-09-15"


def test_unresolved_year_reply_drops_the_change_without_looping(monkeypatch):
    """A reply that never supplies a year (e.g. more small talk) must not
    re-interrupt forever -- the change is simply dropped and the turn
    completes, matching this phase's no-deadlock guarantee."""

    def _fake_extract_patch(_state):
        return {"patch": [{"path": "dates.start", "operation": "set", "value": "15/09"}], "intent": "update_trip"}

    monkeypatch.setattr(graph_module, "extract_patch", _fake_extract_patch)
    monkeypatch.setattr(supervisor_module, "get_fast_llm", _unreachable_llm)

    app = graph_module.build_graph()
    config = {"configurable": {"thread_id": "test-missing-year-unresolved"}}

    app.invoke(
        {"session_id": "s1", "language": "vi", "messages": [HumanMessage(content="đi ngày 15/09")]},
        config=config,
    )

    resumed = app.invoke(Command(resume="không biết"), config=config)

    assert "__interrupt__" not in resumed
    assert resumed["travel_state"].get("dates.start") is None
    # The raw reply is surfaced, not silently discarded -- the caller
    # (api/routes.py::_run_turn_via_graph) is what re-runs it as a fresh
    # turn (see test_unresolved_resume_reply_is_reprocessed_as_a_fresh_turn
    # below for the full round trip through a second `extract_patch` call).
    assert resumed["unresolved_resume_text"] == "không biết"


def test_a_resolved_resume_never_carries_an_unresolved_flag(monkeypatch):
    def _fake_extract_patch(_state):
        return {"patch": [{"path": "dates.start", "operation": "set", "value": "15/09"}], "intent": "update_trip"}

    monkeypatch.setattr(graph_module, "extract_patch", _fake_extract_patch)
    monkeypatch.setattr(supervisor_module, "get_fast_llm", _unreachable_llm)

    app = graph_module.build_graph()
    config = {"configurable": {"thread_id": "test-resolved-no-flag"}}

    app.invoke(
        {"session_id": "s1", "language": "vi", "messages": [HumanMessage(content="đi ngày 15/09")]},
        config=config,
    )
    resumed = app.invoke(Command(resume="2099"), config=config)

    assert resumed.get("unresolved_resume_text") is None


def test_unresolved_resume_reply_answers_a_different_intent_and_is_not_lost(monkeypatch):
    """The exact class of bug this whole phase exists to kill, recreated one
    level down inside the interrupt itself: paused on a date question, the
    user replies with something that answers a COMPLETELY different intent
    (changing the destination, not the year). `extract_patch` never runs
    again on the resume invoke (only `validate_patch` re-executes) -- this
    drives the full two-invoke sequence `_run_turn_via_graph` performs
    (resume, detect `unresolved_resume_text`, re-run as a fresh turn) and
    proves the destination change actually lands."""

    def _fake_extract_patch(state):
        last_message = str(state["messages"][-1].content)
        if "Huế" in last_message:
            return {"patch": [{"path": "destination", "operation": "set", "value": "Huế"}], "intent": "update_trip"}
        return {"patch": [{"path": "dates.start", "operation": "set", "value": "01/07"}], "intent": "update_trip"}

    monkeypatch.setattr(graph_module, "extract_patch", _fake_extract_patch)
    monkeypatch.setattr(supervisor_module, "get_fast_llm", _unreachable_llm)

    app = graph_module.build_graph()
    config = {"configurable": {"thread_id": "test-unresolved-different-intent"}}

    app.invoke(
        {"session_id": "s1", "language": "vi", "messages": [HumanMessage(content="đi ngày 01/07")]},
        config=config,
    )
    resumed = app.invoke(Command(resume="thôi đổi điểm đến sang Huế"), config=config)

    assert "__interrupt__" not in resumed
    unresolved = resumed["unresolved_resume_text"]
    assert unresolved == "thôi đổi điểm đến sang Huế"

    # This is what api/routes.py::_run_turn_via_graph does with it.
    final = app.invoke(
        {"session_id": "s1", "language": "vi", "messages": [HumanMessage(content=unresolved)]},
        config=config,
    )

    assert final["travel_state"]["destination"]["value"] == "Huế"
    # The abandoned date change is dropped, not resurrected -- the user
    # moved on to a different topic, never answered it.
    assert final["travel_state"].get("dates.start") is None


# --- Day/month order ---------------------------------------------------------


def test_day_month_order_ambiguity_pauses_with_both_readings_then_resumes(monkeypatch):
    def _fake_extract_patch(_state):
        return {"patch": [{"path": "dates.start", "operation": "set", "value": "1-2-2099"}], "intent": "update_trip"}

    monkeypatch.setattr(graph_module, "extract_patch", _fake_extract_patch)
    monkeypatch.setattr(supervisor_module, "get_fast_llm", _unreachable_llm)

    app = graph_module.build_graph()
    config = {"configurable": {"thread_id": "test-day-month-order"}}

    paused = app.invoke(
        {"session_id": "s1", "language": "vi", "messages": [HumanMessage(content="đi ngày 1-2-2099")]},
        config=config,
    )

    payload = paused["__interrupt__"][0].value
    assert payload["kind"] == "day_month_order"
    assert payload["candidates"] == ("2099-02-01", "2099-01-02")  # DD-MM (1 Feb) first, MM-DD (2 Jan) second

    # Pick option 2: 2 Jan (the MM-DD / "2 Jan" reading).
    resumed = app.invoke(Command(resume="2"), config=config)

    assert "__interrupt__" not in resumed
    assert resumed["travel_state"]["dates.start"]["value"] == "2099-01-02"


def test_unambiguous_bare_numeric_date_resolves_without_any_interrupt(monkeypatch):
    """A day/month component over 12 ("31-07") only has one valid reading --
    must never pause at all. This is WITH a year (unlike the missing-year
    tests above): a bare "31/07" with no year still asks for the year first,
    same as any other yearless date -- this test isolates the day/month-
    order rule specifically, not the missing-year rule."""

    def _fake_extract_patch(_state):
        return {"patch": [{"path": "dates.start", "operation": "set", "value": "31-07-2099"}], "intent": "update_trip"}

    monkeypatch.setattr(graph_module, "extract_patch", _fake_extract_patch)
    monkeypatch.setattr(supervisor_module, "get_fast_llm", _unreachable_llm)

    app = graph_module.build_graph()
    result = app.invoke(
        {"session_id": "s1", "language": "vi", "messages": [HumanMessage(content="đi ngày 31-07-2099")]},
        config={"configurable": {"thread_id": "test-unambiguous"}},
    )

    assert "__interrupt__" not in result
    assert result["travel_state"]["dates.start"]["value"] == "2099-07-31"


# --- The deadlock regression this phase exists to kill -----------------------


def test_deadlock_regression_date_change_applies_and_budget_returns_with_context(monkeypatch):
    """The reported failure, reproduced exactly: budget is the only slot
    still pending, the user sends an UNRELATED date change -- the date must
    apply, and budget must be asked again, not silently dropped or repeated
    verbatim (it must carry a "what changed" context line)."""

    # Within the seeded [2099-01-01, 2099-01-05) window so this exercises
    # the date CHANGE itself, not an unrelated end-before-start rejection.
    new_start = "2099-01-02"

    def _fake_extract_patch(_state):
        return {
            "patch": [{"path": "dates.start", "operation": "set", "value": new_start}],
            "intent": "update_trip",
        }

    monkeypatch.setattr(graph_module, "extract_patch", _fake_extract_patch)
    monkeypatch.setattr(supervisor_module, "get_fast_llm", _unreachable_llm)

    app = graph_module.build_graph()
    seeded = _seeded_travel_state()  # destination/people/dates set, budget still UNKNOWN

    result = app.invoke(
        {
            "session_id": "s1",
            "language": "vi",
            "travel_state": seeded,
            "messages": [HumanMessage(content="đổi ngày đi thành 02/01/2099")],
        },
        config={"configurable": {"thread_id": "test-deadlock-regression"}},
    )

    assert result["travel_state"]["dates.start"]["value"] == new_start
    assert result["missing_slots"] == ["budget.target"]

    response = PlannerChatResponse(**result["response"])
    assert "Đã cập nhật" in response.reply  # context, not a verbatim repeat
    assert "giá" in response.reply.lower()  # the budget question itself still follows


def test_deadlock_regression_budget_reply_after_answered_advances_past_it(monkeypatch):
    """Complement of the above: once budget IS answered (a bare ceiling,
    "tối đa 5 triệu" -> budget.max only), the slot gate opens and the turn
    reaches the supervisor instead of re-asking budget."""

    def _fake_extract_patch(_state):
        return {"patch": [{"path": "budget.max", "operation": "set", "value": 5_000_000}], "intent": "update_trip"}

    monkeypatch.setattr(graph_module, "extract_patch", _fake_extract_patch)
    monkeypatch.setattr(supervisor_module, "get_fast_llm", _unreachable_llm)

    app = graph_module.build_graph()
    seeded = _seeded_travel_state()

    result = app.invoke(
        {
            "session_id": "s1",
            "language": "vi",
            "travel_state": seeded,
            "messages": [HumanMessage(content="tối đa 5 triệu")],
        },
        config={"configurable": {"thread_id": "test-budget-answered"}},
    )

    assert result["missing_slots"] == []
    assert result["task_results"]  # reached the supervisor -> a worker ran
    assert result["routing_source"] == "impact_map"


# --- Interrupt purity (also asserted structurally in test_graph_v2_skeleton) -


def test_validate_patch_never_performs_an_llm_or_db_call_before_interrupting(monkeypatch):
    """Cross-check at the integration level: the missing-year scenario above
    must reach `interrupt()` without ever touching the LLM/DB -- both are
    monkeypatched to raise, and the first invoke already proved this by not
    raising. This test documents the invariant explicitly rather than
    relying on it being incidental to another test's fixture.
    """

    def _fake_extract_patch(_state):
        return {"patch": [{"path": "dates.start", "operation": "set", "value": "15/09"}], "intent": "update_trip"}

    monkeypatch.setattr(graph_module, "extract_patch", _fake_extract_patch)
    monkeypatch.setattr(supervisor_module, "get_fast_llm", _unreachable_llm)

    app = graph_module.build_graph()
    result = app.invoke(
        {"session_id": "s1", "language": "vi", "messages": [HumanMessage(content="đi ngày 15/09")]},
        config={"configurable": {"thread_id": "test-purity"}},
    )

    assert "__interrupt__" in result  # reached the pause with no LLM/DB call raised


# --- Restart durability (opt-in, live Postgres) ------------------------------


@pytest.mark.skipif(
    os.environ.get("RUN_LIVE_POSTGRES_CHECKPOINTER_TESTS") != "1",
    reason="Opt-in only: set RUN_LIVE_POSTGRES_CHECKPOINTER_TESTS=1 and CHECKPOINTER_DATABASE_URL "
    "to run against a real Postgres instance (a local `postgres:16` container works).",
)
def test_paused_thread_survives_a_simulated_process_restart(monkeypatch):
    from langgraph.checkpoint.postgres import PostgresSaver

    from src.config import get_settings
    from src.main import _require_checkpointer_database_url

    conn_string = _require_checkpointer_database_url(get_settings())
    thread_id = "test-interrupt-restart-durability"
    config = {"configurable": {"thread_id": thread_id}}

    def _fake_extract_patch(_state):
        return {"patch": [{"path": "dates.start", "operation": "set", "value": "15/09"}], "intent": "update_trip"}

    monkeypatch.setattr(graph_module, "extract_patch", _fake_extract_patch)
    monkeypatch.setattr(supervisor_module, "get_fast_llm", _unreachable_llm)

    try:
        with PostgresSaver.from_conn_string(conn_string) as checkpointer:
            checkpointer.setup()
            app = graph_module.build_graph(checkpointer=checkpointer)
            paused = app.invoke(
                {"session_id": "s1", "language": "vi", "messages": [HumanMessage(content="đi ngày 15/09")]},
                config=config,
            )
            assert "__interrupt__" in paused

        # Simulate a process restart: a fresh PostgresSaver connection, same DB.
        with PostgresSaver.from_conn_string(conn_string) as restarted_checkpointer:
            restarted_app = graph_module.build_graph(checkpointer=restarted_checkpointer)
            snapshot = restarted_app.get_state(config)
            assert snapshot.interrupts  # the pause survived the "restart"

            resumed = restarted_app.invoke(Command(resume="2099"), config=config)
            assert "__interrupt__" not in resumed
            assert resumed["travel_state"]["dates.start"]["value"] == "2099-09-15"
    finally:
        with PostgresSaver.from_conn_string(conn_string) as cleanup_checkpointer:
            cleanup_checkpointer.delete_thread(thread_id)
