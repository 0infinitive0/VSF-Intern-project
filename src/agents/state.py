from __future__ import annotations

import logging
from typing import Annotated, Any, TypedDict

from langgraph.graph.message import add_messages

from src.services.hotel_selection import HotelPreferenceState
from src.services.trip_intake import TripIntakeState

logger = logging.getLogger(__name__)


class TripAgentState(TypedDict):
    """LangGraph message-passing state for the trip planner's supervisor agent.

    `create_react_agent` manages this state internally (tool calls, tool
    results, and the running message history); this schema documents its
    shape for anything that inspects agent state directly.
    """

    messages: Annotated[list, add_messages]


class TripState(TypedDict):
    """Every business fact a chat turn depends on, kept fully serializable so
    a checkpointer can own it (Phase 7). `intake`/`hotel_prefs` are
    `TripIntakeState`/`HotelPreferenceState` via `to_dict()` — reconstruct
    with `from_dict()` before reading `.is_complete` or other derived
    properties, never by reaching into the raw dict.

    `route`/`reroute_count` are written by the Phase 5 router node;
    `reply`/`tool_ran` replace `TurnResult`'s two fields there. None of the
    four are read or written by anything before Phase 5 — they exist now so
    the schema doesn't change shape out from under Phase 5's checkpointed
    threads.
    """

    messages: Annotated[list, add_messages]
    intake: dict[str, Any]
    hotel_prefs: dict[str, Any]
    trip_data: dict[str, Any] | None
    pending_hotel_selection: dict[str, Any] | None
    initial_plan_complete: bool
    planning_new_trip: bool
    pending_trip_edit_request: str | None
    route: str | None
    reroute_count: int
    reply: str
    tool_ran: str | None


def initial_state(session_id: str) -> TripState:
    """Fresh TripState for a brand-new conversation."""
    logger.debug("Initializing TripState for session %s", session_id)
    return TripState(
        messages=[],
        intake=TripIntakeState().to_dict(),
        hotel_prefs=HotelPreferenceState().to_dict(),
        trip_data=None,
        pending_hotel_selection=None,
        initial_plan_complete=False,
        planning_new_trip=False,
        pending_trip_edit_request=None,
        route=None,
        reroute_count=0,
        reply="",
        tool_ran=None,
    )
