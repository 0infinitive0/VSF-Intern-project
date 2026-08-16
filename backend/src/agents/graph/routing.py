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


def _no_destination(state: TravelGraphState) -> bool:
    """No worker can act on a trip with no destination. `ask_slot` normally
    gates this long before the supervisor sees the turn; this is the
    backstop for the paths that skip it."""
    return not bool((state.get("travel_state") or {}).get("destination"))


def requires_existing_trip(state: TravelGraphState) -> bool:
    """`itinerary_node` is an EDITOR, not a builder.

    Every action it has — `rebuild_days`, `edit_item`, `lock_days` — operates
    on a `trip_data` that already exists; none of them can create one. The
    trip is created by `hotel_node` when the user picks a hotel
    (`_handle_hotel_selection` -> `build_selected_hotel_trip`, which builds
    the hotel *and* the whole itinerary in one pass).

    That ordering is a causal constraint of the product, not a preference:
    the itinerary is scheduled around the hotel's location, so it cannot be
    built before we know where the user is staying. `WORKER_ORDER` encodes
    the same reason.

    Without this check, a single message setting destination/dates/people/
    preferences at once (the common first-intake turn) impacts both the
    `hotel` and `itinerary` workflows, so `itinerary_node` looked "possible"
    purely from `destination` and became a supervisor-LLM coin flip against
    `hotel_node` — reported bug: the LLM sometimes picked `itinerary_node`
    first, which bailed immediately with nothing to show, forcing the user
    to resend the identical message.
    """
    return not bool(state.get("trip_data"))


_IMPOSSIBLE: dict[str, Callable[[TravelGraphState], bool]] = {
    "itinerary_node": lambda s: _no_destination(s) or requires_existing_trip(s),
    "booking_node": lambda s: True,  # blocked until the booking plan lands
}


def is_impossible(worker: str, state: TravelGraphState) -> bool:
    return _IMPOSSIBLE.get(worker, _never)(state)


def needs_trip_first(state: TravelGraphState) -> bool:
    """The turn asked for itinerary work before a trip exists.

    This is the one reason `itinerary_node` is impossible that has an
    obvious next step rather than being a dead end: the trip is created by
    picking a hotel, so the turn should go do that (see
    `requires_existing_trip`). The supervisor acts on this instead of
    delegating to nobody and answering with nothing.

    Narrow on purpose: a missing *destination* is `ask_slot`'s job, and
    redirecting that turn would only produce `hotel_node`'s own "no
    destination" defensive reply.
    """
    if "itinerary_node" not in (state.get("pending_tasks") or []):
        return False
    if _no_destination(state) or not requires_existing_trip(state):
        return False
    return not is_impossible("hotel_node", state)


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
