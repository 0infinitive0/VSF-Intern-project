"""Phase 4 measurement: regex vs. supervisor routing accuracy and latency.

This is a measurement tool, not a hard pass/fail gate — the plan's own Phase 4
doc states three legitimate outcomes (supervisor beats regex, matches it, or
is worse), and the honest result may be "keep the flag off". `decide_route_by_llm`
calls whatever `LLM_PROVIDER` resolves to in the environment — in this repo
that is real OpenAI, traced to real LangSmith, when `.env` is used as-is — so
this test is opt-in only: set `RUN_LIVE_ROUTING_EVAL=1` to run it. An Ollama
reachability check alone is NOT a safe gate here, since Ollama commonly runs
locally anyway (for embeddings, per ARCHITECTURE.md's Environment Matrix)
regardless of which provider `LLM_PROVIDER` actually points `get_llm()` at.

Run directly for a human-readable report:
    RUN_LIVE_ROUTING_EVAL=1 python tests/test_agents/test_supervisor_routing_accuracy.py
Or via pytest for CI-safe structural assertions only (no accuracy gate):
    RUN_LIVE_ROUTING_EVAL=1 pytest tests/test_agents/test_supervisor_routing_accuracy.py
"""

from __future__ import annotations

import os
import time
import urllib.request
from dataclasses import dataclass, field

import pytest

from src.agents.routing_decision import Route, decide_route_by_rules, route_context_from_state
from src.agents.supervisor import decide_route_by_llm

_LIVE_EVAL_OPT_IN = "RUN_LIVE_ROUTING_EVAL"


def _live_eval_enabled() -> bool:
    return os.environ.get(_LIVE_EVAL_OPT_IN) == "1"


def _ollama_reachable() -> bool:
    try:
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=1)
        return True
    except Exception:
        return False


class _FakeIntakeState:
    def __init__(self, is_complete: bool = False):
        self.is_complete = is_complete


class _FakeHotelPrefState:
    def __init__(self, is_complete: bool = False):
        self.is_complete = is_complete


@dataclass
class _FakeSession:
    """Since Phase 3, route_context_from_state reads a TripState dict, not a
    session object — `.state` translates this fake's legacy attributes into
    that shape. `decide_route_by_llm` also reads `.pending_hotel_selection`
    directly (a getattr on the session, unrelated to `.state`), so that
    attribute stays as-is."""

    trip_data: dict | None = None
    pending_hotel_selection: dict | None = None
    initial_plan_complete: bool = False
    planning_new_trip: bool = False
    pending_trip_edit_request: str | None = None
    intake_state: _FakeIntakeState = field(default_factory=_FakeIntakeState)
    hotel_pref_state: _FakeHotelPrefState = field(default_factory=_FakeHotelPrefState)

    @property
    def state(self) -> dict:
        return {
            "trip_data": self.trip_data,
            "pending_hotel_selection": self.pending_hotel_selection,
            "initial_plan_complete": self.initial_plan_complete,
            "planning_new_trip": self.planning_new_trip,
            "pending_trip_edit_request": self.pending_trip_edit_request,
            "intake": {
                "destination": "x" if self.intake_state.is_complete else None,
                "duration": "x" if self.intake_state.is_complete else None,
                "people": "x" if self.intake_state.is_complete else None,
                "preferences": [],
            },
            "hotel_prefs": {
                "stage": "done" if self.hotel_pref_state.is_complete else "pending_budget",
                "target_price": None,
                "min_price": None,
                "max_price": None,
            },
        }


_SAVED_DRAFT = {"itineraries": [{"duration_days": 3, "status": "Draft"}]}
_TWO_HOTEL_OPTIONS = {
    "mode": "new_trip",
    "options": [{"name": "Muong Thanh Grand"}, {"name": "Vinpearl Resort"}],
}


@dataclass
class Scenario:
    message: str
    expected: Route
    source: str
    session: _FakeSession
    note: str = ""


SCENARIOS: list[Scenario] = [
    Scenario(
        message="đi Đà Nẵng 3 ngày 2 người",
        expected="new_trip",
        source="session.py:303 — must not read as 'day 2' edit scope",
        session=_FakeSession(trip_data=_SAVED_DRAFT),
    ),
    Scenario(
        message="đổi khách sạn ngày 2",
        expected="edit_draft",
        source="session.py:303 day-scope guard",
        session=_FakeSession(trip_data=_SAVED_DRAFT),
    ),
    Scenario(
        message="3",
        expected="select_hotel",
        source="session.py:355 — bare number is always a pick",
        session=_FakeSession(pending_hotel_selection=_TWO_HOTEL_OPTIONS),
    ),
    Scenario(
        message="chốt lịch trình",
        expected="finalize",
        source="session.py:470-477 — escape from the trap",
        session=_FakeSession(pending_hotel_selection=_TWO_HOTEL_OPTIONS, trip_data=_SAVED_DRAFT),
        note=(
            "decide_route_by_rules ALWAYS answers select_hotel here — it checks "
            "has_pending_hotel_selection first, by design (D1's stated risk). The "
            "actual escape only happens one level down, inside process_chat_turn's "
            "select_hotel branch body, after select_hotel.invoke() fails to resolve "
            "a pick and the list is dropped. This scenario measures whether the "
            "supervisor can skip that extra hop; the regex label is expected to "
            "read select_hotel, not the table's 'expected' column."
        ),
    ),
    Scenario(
        message="thêm quán cà phê ngày 2",
        expected="edit_draft",
        source="session.py:470-477 — same trap",
        session=_FakeSession(pending_hotel_selection=_TWO_HOTEL_OPTIONS, trip_data=_SAVED_DRAFT),
        note="Same caveat as above: decide_route_by_rules's raw label is select_hotel.",
    ),
    Scenario(
        message="sau 20h tôi không muốn đi đâu nữa",
        expected="edit_draft",
        source="session.py:316-325 — names no place",
        session=_FakeSession(trip_data=_SAVED_DRAFT),
    ),
    Scenario(
        message="tôi muốn đi Hội An",
        expected="new_trip",
        source="_unsupported_destination_reply",
        session=_FakeSession(trip_data=_SAVED_DRAFT),
        note=(
            "decide_route_by_rules's raw label for an unsupported city on a weak "
            "signal is edit_draft (fresh_intake.destination is None because Hội An "
            "doesn't match the known list) — the 'expected' outcome (naming the "
            "supported destinations) is produced by _unsupported_destination_reply, "
            "which process_chat_turn runs for both new_trip and edit_draft labels "
            "alike, so the user-visible behavior is correct either way."
        ),
    ),
]


@pytest.mark.skipif(
    not _live_eval_enabled(),
    reason=f"Live LLM/LangSmith call — set {_LIVE_EVAL_OPT_IN}=1 to opt in",
)
@pytest.mark.skipif(not _ollama_reachable(), reason="Ollama not reachable — live measurement only")
def test_routing_accuracy_and_latency_report():
    """Prints the comparison table and per-call latency. No accuracy assertion
    — see module docstring. Only asserts the harness itself doesn't crash and
    every label produced is a real Route or None."""
    rows = []
    regex_latencies = []
    supervisor_latencies = []

    for scenario in SCENARIOS:
        t0 = time.perf_counter()
        context = route_context_from_state(scenario.session.state)
        regex_label = decide_route_by_rules(context, scenario.message)
        regex_latencies.append(time.perf_counter() - t0)

        t0 = time.perf_counter()
        supervisor_label = decide_route_by_llm(scenario.session, scenario.message)
        supervisor_latencies.append(time.perf_counter() - t0)

        rows.append((scenario.message, scenario.expected, regex_label, supervisor_label, scenario.note))
        assert regex_label in (
            "select_hotel", "finalize", "new_trip", "edit_draft", "intake", "chat",
        )
        assert supervisor_label in (
            "select_hotel", "finalize", "new_trip", "edit_draft", "intake", "chat", None,
        )

    print("\n\n=== Supervisor vs. regex routing — Phase 4 measurement ===")
    print(f"{'message':<38} {'expected':<13} {'regex':<13} {'supervisor':<13}")
    for message, expected, regex_label, supervisor_label, note in rows:
        print(f"{message:<38} {expected:<13} {regex_label:<13} {str(supervisor_label):<13}")
        if note:
            print(f"    note: {note}")

    print(
        f"\nLatency (n={len(SCENARIOS)}): "
        f"regex avg={sum(regex_latencies) / len(regex_latencies) * 1000:.1f}ms, "
        f"supervisor avg={sum(supervisor_latencies) / len(supervisor_latencies) * 1000:.1f}ms, "
        f"added avg={(sum(supervisor_latencies) - sum(regex_latencies)) / len(SCENARIOS) * 1000:.1f}ms"
    )


if __name__ == "__main__":
    if not _live_eval_enabled():
        raise SystemExit(
            f"Refusing to call the real LLM/LangSmith: set {_LIVE_EVAL_OPT_IN}=1 to run this report."
        )
    test_routing_accuracy_and_latency_report()
