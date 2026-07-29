"""Reusable, transport-agnostic chat-turn processing for the trip planner.

Extracted from the CLI's `while True` loop so both the terminal (`src/cli/
terminal_chat.py`, state kept in local variables across loop iterations) and
the web API (`src/api/routes.py`, state kept in a session dict across HTTP
requests) can share the exact same per-turn decision logic.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

from src.cli.planner_tools import (
    _is_finalization_request,
    create_planner_agent,
    finalize_trip_plan,
    recommend_hotels,
    select_hotel,
)
from src.cli.trip_builder_svc import CURRENT_TRIP_PLAN_FILE, PENDING_HOTEL_SELECTION_FILE, _get_destination_names
from src.services.hotel_selection import HotelPreferenceState
from src.services.trip_intake import TripIntakeState
from src.services.trip_scheduler import infer_trip_change

logger = logging.getLogger(__name__)


@dataclass
class ChatSession:
    """Per-conversation state — one instance per terminal run, or per web
    session_id. Mutated in place by process_chat_turn as the conversation
    progresses through intake -> hotel preferences -> recommend/select -> agent."""

    agent: Any
    config: dict
    intake_state: TripIntakeState = field(default_factory=TripIntakeState)
    hotel_pref_state: HotelPreferenceState = field(default_factory=HotelPreferenceState)
    initial_plan_complete: bool = False


def create_chat_session(thread_id: str) -> ChatSession:
    return ChatSession(
        agent=create_planner_agent(),
        config={"configurable": {"thread_id": thread_id}},
    )


def process_chat_turn(session: ChatSession, user_input: str) -> str:
    """Handle exactly one chat turn and return the reply text. Mutates `session`
    in place. Callers own their own input loop / HTTP request cycle — this
    function never blocks on input() and never prints."""
    logger.info("User Input: %s", user_input)

    if os.path.exists(PENDING_HOTEL_SELECTION_FILE):
        tool_response = select_hotel.invoke({"selection": user_input})
        logger.info("Hotel selection response: %s", tool_response)
        session.initial_plan_complete = not str(tool_response).startswith("SYSTEM ERROR:")
        return tool_response

    if os.path.exists(CURRENT_TRIP_PLAN_FILE) and _is_finalization_request(user_input):
        tool_response = finalize_trip_plan.invoke({})
        logger.info("Finalization response: %s", tool_response)
        session.initial_plan_complete = not str(tool_response).startswith("SYSTEM ERROR:")
        return tool_response

    change_intent = infer_trip_change(user_input)
    is_saved_plan_edit = bool(os.path.exists(CURRENT_TRIP_PLAN_FILE) and change_intent is not None)

    if not session.initial_plan_complete and not is_saved_plan_edit:
        if not session.intake_state.is_complete:
            session.intake_state = session.intake_state.with_message(user_input, _get_destination_names())
            missing_question = session.intake_state.next_question()
            if missing_question:
                logger.info("Deterministic intake response: %s", missing_question)
                return missing_question

            # Trip facts just became complete THIS turn (consumed by intake_state
            # above) — ask the first hotel-preference question next turn, rather
            # than also feeding this same input into hotel_pref_state right now.
            logger.info("Trip intake complete; asking hotel budget preference")
            return session.hotel_pref_state.next_question()

        if not session.hotel_pref_state.is_complete:
            session.hotel_pref_state = session.hotel_pref_state.with_message(user_input)
            missing_pref_question = session.hotel_pref_state.next_question()
            if missing_pref_question:
                logger.info("Guided hotel-preference response: %s", missing_pref_question)
                return missing_pref_question

        verified_arguments = {
            **session.intake_state.tool_arguments(),
            **session.hotel_pref_state.tool_arguments(),
        }
        logger.info("Deterministic intake complete: %s", verified_arguments)
        tool_response = recommend_hotels.invoke(verified_arguments)
        logger.info("Final Tool Response Output:\n%s", tool_response)
        return tool_response

    events = session.agent.stream(
        {"messages": [("user", user_input)]},
        config=session.config,
        stream_mode="values",
    )

    final_ai_response = None
    tool_output_response = None
    for event in events:
        if "messages" in event:
            latest_message = event["messages"][-1]

            if latest_message.type == "ai" and latest_message.tool_calls:
                tool_names = ", ".join(tc["name"] for tc in latest_message.tool_calls)
                logger.info("Delegating to tools: %s", tool_names)

            elif latest_message.type == "tool":
                if "SYSTEM ERROR:" not in str(latest_message.content):
                    tool_output_response = latest_message.content
                logger.info("Tool returned: %s", latest_message.name)

            if latest_message.type == "ai" and not latest_message.tool_calls:
                final_ai_response = latest_message.content

    if tool_output_response:
        logger.info("Final Tool Response Output:\n%s", tool_output_response)
        return tool_output_response
    if final_ai_response:
        logger.info("Final AI Response: %s", final_ai_response)
        return final_ai_response
    return "SYSTEM ERROR: Không nhận được phản hồi từ agent."
