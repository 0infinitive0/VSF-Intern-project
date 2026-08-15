"""Orchestration-layer routing tables: worker names, delegation order, and
the possibility guard. `domain/travel_state.py` returns `Workflow` labels
(`detect_impact`) and must stay ignorant of graph node names (Phase 3
purity test) — that mapping lives here instead.
"""

from __future__ import annotations

from collections.abc import Callable

from src.agents.graph.state import TravelGraphState
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
#
# `itinerary_node` additionally requires `trip_data` (not just `destination`):
# every one of its actions -- `lock_days`, `edit_item`, and the default
# `build_itinerary`/`rebuild_days` -- bails with "chọn khách sạn trước" when
# `trip_data` is empty (`itinerary_node.py`'s own `_err` calls). Only
# `hotel_node`'s `selected_hotel_id` branch ever creates `trip_data`
# (`_handle_hotel_selection` -> `build_selected_hotel_trip`); `itinerary_node`
# has no code path that builds one from scratch. Without this second check, a
# single message that sets destination/dates/people/preferences all at once
# (the common first-intake turn) impacts both `hotel` and `itinerary`
# workflows, so `itinerary_node` looked "possible" purely from `destination`
# and became a supervisor-LLM coin flip against `hotel_node` -- reported bug:
# the LLM sometimes picked `itinerary_node` first, which bailed immediately
# with nothing to show, forcing the user to resend the identical message.
_IMPOSSIBLE: dict[str, Callable[[TravelGraphState], bool]] = {
    "itinerary_node": lambda s: not bool((s.get("travel_state") or {}).get("destination"))
    or not bool(s.get("trip_data")),
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


def is_intake_question(state: TravelGraphState) -> bool:
    """True when the patch pipeline concluded — not merely guessed — that
    this turn's message is a genuine read-only question
    (`intent == "general_question"` with `extraction_failed` false). Shared
    by `route_ask_slot` (routes to `intake_qa`) and `ask_slot`
    (`nodes/ask_slot.py::_context_line`, which must not blame the user for
    "not answering" a slot when they asked a question instead — a question
    is not a failed answer attempt).
    """
    return state.get("intent") == "general_question" and not state.get("extraction_failed")


def route_ask_slot(state: TravelGraphState) -> str:
    """`"ask"` routes through `respond` rather than straight to `END` so the
    frozen `PlannerChatResponse` shape is always built.

    Phase 15's third branch: a required slot is still missing AND
    `is_intake_question` — `intake_qa` answers it and `ask_slot`'s question
    still follows in the same reply. A parse failure or an empty message
    falls through to `"ask"` instead, so a provider outage is never sent to
    an LLM to answer confidently.
    """
    if not state.get("missing_slots"):
        return "supervisor"
    if is_intake_question(state):
        return "intake_qa"
    return "ask"


def route_supervisor(state: TravelGraphState) -> str:
    """The supervisor node already decided; this edge only reads its
    decision back. `next_worker` is always one of the five conditional-edge
    keys the supervisor node itself is allowed to return."""
    return state.get("next_worker") or "respond"
