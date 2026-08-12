from __future__ import annotations

import logging
from typing import Annotated, Any, NotRequired

from langgraph.graph.message import add_messages
from langgraph.managed.is_last_step import RemainingStepsManager
from typing_extensions import TypedDict

from src.domain.travel_state import TravelState
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

    `travel_state` is the canonical `TravelState` (`src/domain/travel_state.py`)
    via `to_dict()`, carried alongside `intake`/`hotel_prefs` rather than
    replacing them — Phase 3 adds the patch-validated layer without changing
    either state's behavior; only from Phase 6 does `apply_patch` become the
    sole writer, and Phase 11 retires `intake`/`hotel_prefs` as writers.

    `route`/`reroute_count` are written by the Phase 5 router node;
    `reply`/`tool_ran` replace `TurnResult`'s two fields there. None of the
    four are read or written by anything before Phase 5 — they exist now so
    the schema doesn't change shape out from under Phase 5's checkpointed
    threads.

    `remaining_steps` is `create_react_agent`'s own required key (Phase 4):
    passing a custom `state_schema` to `create_react_agent` without it raises
    `ValueError: Missing required key(s) {'remaining_steps'}` at compile time
    — verified empirically, not from docs alone, since the docs' own
    ToolRuntime/Command examples only ever show a plain `StateGraph`, never
    `create_react_agent`. LangGraph's own `RemainingStepsManager` injects the
    actual value at runtime; nothing in this codebase reads or writes it.
    """

    messages: Annotated[list, add_messages]
    intake: dict[str, Any]
    hotel_prefs: dict[str, Any]
    travel_state: dict[str, Any]
    trip_data: dict[str, Any] | None
    pending_hotel_selection: dict[str, Any] | None
    initial_plan_complete: bool
    planning_new_trip: bool
    pending_trip_edit_request: str | None
    pending_trip_preference_request: str | None
    preference_replacement_state: dict[str, Any] | None
    pending_parameter_confirmation: bool
    route: str | None
    reroute_count: int
    reply: str
    tool_ran: str | None
    language: str
    remaining_steps: NotRequired[Annotated[int, RemainingStepsManager]]


def initial_state(session_id: str, language: str = "vi") -> TripState:
    """Fresh TripState for a brand-new conversation.

    `language` is the reply-language for deterministic content
    ("vi" | "en"); it mirrors the frontend's manual EN/VI toggle and is
    threaded into every reply-producing helper via `t(..., language)`.
    """
    logger.debug("Initializing TripState for session %s", session_id)
    return TripState(
        messages=[],
        intake=TripIntakeState().to_dict(),
        hotel_prefs=HotelPreferenceState().to_dict(),
        travel_state=TravelState().to_dict(),
        trip_data=None,
        pending_hotel_selection=None,
        initial_plan_complete=False,
        planning_new_trip=False,
        pending_trip_edit_request=None,
        pending_trip_preference_request=None,
        preference_replacement_state=None,
        pending_parameter_confirmation=False,
        route=None,
        reroute_count=0,
        reply="",
        tool_ran=None,
        language=language,
    )
