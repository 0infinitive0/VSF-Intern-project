"""Phase 7 (260812-0927-langgraph-orchestration-state-patch-and-interrupts)
originally added `interrupt()`/`Command(resume=...)` here for a genuinely
ambiguous date (day/month order). `domain.travel_state._resolve_numeric_date`
no longer produces that ambiguity -- it always prefers the DD-MM
(Vietnamese) reading over MM-DD -- so a date-shaped patch value never pauses
the graph anymore. This file now proves that (silent resolution, no
interrupt, whatever the year/day-month shape), plus the deadlock regression
this whole phase exists to kill (a pending question no longer blocks an
unrelated fact) -- that regression no longer needs a date ambiguity to
reproduce, it's demonstrated directly with a plain date change.

`interrupt()`/`Command(resume=...)` itself is still real, live graph
infrastructure -- see `tests/test_hotel_node.py` for the hotel-center-ask
case that still uses it, including its own "different intent" regression
coverage and purity checks. This file no longer needs either, since nothing
here reaches `interrupt()` at all.
"""

from __future__ import annotations

from datetime import date

from langchain_core.messages import HumanMessage

import src.agents.graph.graph as graph_module
import src.agents.graph.nodes.supervisor as supervisor_module
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


# --- Date resolution never interrupts ----------------------------------------


def test_missing_year_resolves_without_pausing(monkeypatch):
    """"15/09" has no year; the missing year defaults to the current year
    and the turn completes without ever reaching `interrupt()`."""

    def _fake_extract_patch(_state):
        return {"patch": [{"path": "dates.start", "operation": "set", "value": "15/09"}], "intent": "update_trip"}

    monkeypatch.setattr(graph_module, "extract_patch", _fake_extract_patch)
    monkeypatch.setattr(supervisor_module, "get_fast_llm", _unreachable_llm)

    app = graph_module.build_graph()
    result = app.invoke(
        {"session_id": "s1", "language": "vi", "messages": [HumanMessage(content="đi ngày 15/09")]},
        config={"configurable": {"thread_id": "test-missing-year-defaults"}},
    )

    assert "__interrupt__" not in result
    assert result["travel_state"]["dates.start"]["value"] == f"{date.today().year}-09-15"


def test_ambiguous_day_month_order_resolves_to_dd_mm_without_any_interrupt(monkeypatch):
    """"1-2" has both components <= 12, so MM-DD (2 Jan) would also be a
    valid calendar date -- the DD-MM reading (1 Feb) wins outright, so this
    never reaches `interrupt()` either."""

    def _fake_extract_patch(_state):
        return {"patch": [{"path": "dates.start", "operation": "set", "value": "1-2-2099"}], "intent": "update_trip"}

    monkeypatch.setattr(graph_module, "extract_patch", _fake_extract_patch)
    monkeypatch.setattr(supervisor_module, "get_fast_llm", _unreachable_llm)

    app = graph_module.build_graph()
    result = app.invoke(
        {"session_id": "s1", "language": "vi", "messages": [HumanMessage(content="đi ngày 1-2-2099")]},
        config={"configurable": {"thread_id": "test-day-month-order"}},
    )

    assert "__interrupt__" not in result
    assert result["travel_state"]["dates.start"]["value"] == "2099-02-01"


def test_unambiguous_bare_numeric_date_resolves_without_any_interrupt(monkeypatch):
    """A day/month component over 12 ("31-07") only has one valid reading --
    must never pause, with or without a year, same as the always-DD-MM
    case above."""

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
    apply, and budget must be asked again, not silently dropped, and never
    mislabeled as a failed/misunderstood answer just because budget is still
    pending (the date change landed fine, only for a different slot)."""

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
    assert "giá" in response.reply.lower()  # the budget question itself still follows
    assert "chưa hiểu" not in response.reply.lower()  # never mislabeled -- the date change did land


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
