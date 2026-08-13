"""Orchestration-layer routing tables: worker names, delegation order, and
the possibility guard. `domain/travel_state.py` returns `Workflow` labels
(`detect_impact`) and must stay ignorant of graph node names (Phase 3
purity test) — that mapping lives here instead.
"""

from __future__ import annotations

from collections.abc import Callable

from src.agents.graph_v2.state import TravelGraphState
from src.domain.travel_state import Workflow

WORKFLOW_TO_WORKER: dict[Workflow, str] = {
    "hotel": "hotel_node",
    "itinerary": "itinerary_node",
    "itinerary_day": "itinerary_node",  # same worker, narrower scope in state
}

# Fixed order when several workflows are impacted: the hotel anchors the
# itinerary, so rebuilding the itinerary first would schedule around a hotel
# about to change.
WORKER_ORDER: tuple[str, ...] = ("hotel_node", "itinerary_node", "booking_node", "qa_node")


def _never(_state: TravelGraphState) -> bool:
    return False


# Structured output guarantees a valid *label*, not a *possible action* —
# ported forward from the legacy router's `_IMPOSSIBLE`
# (`routing_decision.py:174-177`).
_IMPOSSIBLE: dict[str, Callable[[TravelGraphState], bool]] = {
    "itinerary_node": lambda s: not bool((s.get("travel_state") or {}).get("destination")),
    "booking_node": lambda s: True,  # blocked until the booking plan lands
}


def is_impossible(worker: str, state: TravelGraphState) -> bool:
    return _IMPOSSIBLE.get(worker, _never)(state)


def all_tasks_done(state: TravelGraphState) -> bool:
    """Plain predicate on a conditional edge — no LLM. `True` once every
    worker the current turn's applied patch impacted has reported a
    result."""
    return not state.get("pending_tasks")


def route_scope_guard(state: TravelGraphState) -> str:
    """`scope_guard` blocked a jailbreak attempt (`detect_jailbreak`,
    `JAILBREAK_GUARD_MODE=block`) -> skip the whole patch pipeline and go
    straight to `respond`, mirroring the legacy plane's behavior of never
    reaching a tool/LLM call for a blocked input."""
    return "blocked" if state.get("jailbreak_blocked") else "proceed"


def route_ask_slot(state: TravelGraphState) -> str:
    """`ask_slot` is a Phase 7 stub (`missing_slots` is always empty until
    then), so this branch is unreachable today; `"ask"` routes through
    `respond` rather than straight to `END` so the frozen
    `PlannerChatResponse` shape is always built, including when Phase 7
    starts populating `missing_slots` for real."""
    return "ask" if state.get("missing_slots") else "supervisor"


def route_supervisor(state: TravelGraphState) -> str:
    """The supervisor node already decided; this edge only reads its
    decision back. `next_worker` is always one of the five conditional-edge
    keys the supervisor node itself is allowed to return."""
    return state.get("next_worker") or "respond"
