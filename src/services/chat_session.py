"""Reusable, transport-agnostic chat-turn processing for the trip planner.

Extracted from the CLI's `while True` loop so both the terminal (`src/cli/
terminal_chat.py`, state kept in local variables across loop iterations) and
the web API (`src/api/routes.py`, state kept in a session dict across HTTP
requests) can share the exact same per-turn decision logic.
"""

from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from src.cli.planner_tools import (
    _is_finalization_request,
    create_planner_agent,
    execute_trip_edit_request,
    finalize_trip_plan,
    modify_trip_plan,
    recommend_hotels,
    select_hotel,
)
from src.cli.trip_builder_svc import (
    CURRENT_TRIP_PLAN_FILE,
    PENDING_HOTEL_SELECTION_FILE,
    _clear_pending_hotel_selection,
    _get_destination_names,
    _load_pending_hotel_selection,
)
from src.services.hotel_selection import HotelPreferenceState
from src.services.trip_edit_planner import TripEditPlanError, plan_trip_edit
from src.services.trip_intake import (
    TripIntakeState,
    _llm_extract_intake_facts,
    _match_known_destination,
)
from src.services.trip_scheduler import TripChange, parse_day_scope

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
    planning_new_trip: bool = False
    pending_trip_change: TripChange | None = None
    pending_trip_edit_request: str | None = None


def create_chat_session(thread_id: str) -> ChatSession:
    return ChatSession(
        agent=create_planner_agent(),
        config={"configurable": {"thread_id": thread_id}},
    )


def suggestions_for(session: ChatSession) -> list[dict[str, str]]:
    """Tappable quick-reply chips for the state the conversation is now in, as
    [{"label", "value"}] — `value` is what to send when tapped.

    Declared here rather than inferred by the UI. A UI that scans the reply for
    lines like "1. ..." cannot tell a real menu from the model's own prose, and
    the model writes numbered lists constantly ("1. **Điểm đến** ... 2. **Thời
    gian** ..."). Those became chips that sent a bare "1" into a turn expecting
    free text — the answer then had nothing to do with what was asked.

    Empty means the turn wants free text, which is the common case.
    """
    # A shown hotel list is awaiting a pick, and outranks everything else: the
    # very next turn is routed to select_hotel regardless of session state.
    if os.path.exists(PENDING_HOTEL_SELECTION_FILE):
        pending = _load_pending_hotel_selection() or {}
        chips: list[dict[str, str]] = []
        for index, option in enumerate(pending.get("options") or [], start=1):
            name = str(option.get("name") or "").strip()
            if not name:
                continue
            chips.append({"label": f"{index}. {name}", "value": str(index)})
        return chips

    if session.initial_plan_complete or not session.intake_state.is_complete:
        return []

    return [
        {"label": f"{index}. {label}", "value": str(index)}
        for index, label in enumerate(session.hotel_pref_state.suggestion_options(), start=1)
    ]


def _saved_duration_days() -> int:
    try:
        with open(CURRENT_TRIP_PLAN_FILE, encoding="utf-8") as file_handle:
            trip_data = json.load(file_handle)
        itineraries = trip_data.get("itineraries") or [{}]
        itinerary = itineraries[0] if isinstance(itineraries, list) else itineraries
        return max(1, int(itinerary.get("duration_days") or 1))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return 1


def _scope_question(cutoff: str | None) -> str:
    label = cutoff or "giờ này"
    return f"Bạn muốn áp dụng giới hạn {label} cho ngày nào, hay tất cả các ngày?"


def _looks_like_textual_tool_call(content: object) -> bool:
    text = str(content or "").strip()
    if not text:
        return False
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return text.startswith("{") and '"name"' in text and (
            '"parameters"' in text or '"arguments"' in text
        )
    return isinstance(payload, dict) and bool(payload.get("name")) and any(
        key in payload for key in ("parameters", "arguments")
    )


def _normalize_intent_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.replace("Đ", "D").replace("đ", "d"))
    return "".join(character for character in decomposed if not unicodedata.combining(character)).casefold()


def _new_trip_signal(message: str) -> str | None:
    """Return a conservative signal for starting a separate trip.

    A strong signal explicitly says the trip/plan is new. A destination
    signal still requires intake to ground a real destination before the
    saved Draft is bypassed.
    """
    normalized = _normalize_intent_text(message)
    if re.search(r"\b(?:chuyen di|lich trinh|ke hoach)(?: du lich)? moi\b", normalized):
        return "strong"
    # "ngày N" marks an edit scope ("đổi khách sạn ngày 2"), but the same letters
    # appear in every ordinary new-trip sentence: "3 ngày 2 người" normalizes to
    # "3 ngay 2 nguoi", where the N is the head count. Without these guards the
    # most common way to start a trip is read as editing day 2 of the saved plan.
    # A duration reads as "<digit> ngày"; a scope reads as "ngày <digit>" with no
    # digit before it and no unit word after it.
    day_scope = r"(?<!\d\s)\bngay\s+\d+\b(?!\s*(?:nguoi|dem|tuan|thang))"
    if re.search(r"\b(?:doi|sua|thay|them|bo|xoa)\b", normalized) or re.search(day_scope, normalized):
        return None
    # Any ordinary "let's go somewhere" phrasing counts. This stays safe because it
    # is only a *candidate*: _begin_new_trip_if_requested still refuses unless intake
    # grounds a real destination, and the edit verbs / day scopes above already
    # returned. Requiring the exact words "muốn đi du lịch" missed the most common
    # opener of all — "đi Đà Nẵng 3 ngày 2 người".
    if re.search(r"\b(?:di|du lich|len ke hoach|lap ke hoach|len lich trinh)\b", normalized):
        return "destination"
    return None


def _unsupported_destination_reply(user_input: str) -> str | None:
    """Reply to use when a message clearly asks for a new trip but names a place we
    have no data for. Without this the message falls through to the saved-plan edit
    planner, which answers "không thể hiểu yêu cầu chỉnh sửa" — the user asked to go
    to Hội An and is told their edit was unclear, with no hint of the real reason.

    Keys off the place the user actually NAMED, not merely off a failure to ground
    one. An edit like "sau 20h tôi không muốn đi đâu nữa" names no place at all and
    must stay on the edit path; only a named-but-unknown city belongs here.
    """
    if _new_trip_signal(user_input) is None:
        return None
    destination_names = _get_destination_names()
    named = str(
        (_llm_extract_intake_facts(user_input, {}, destination_names) or {}).get("destination") or ""
    ).strip()
    if not named or named.casefold() == "null":
        return None
    if _match_known_destination(named, destination_names):
        return None
    return TripIntakeState().next_question(destination_names)


_OTHER_INTENT_WORDS = re.compile(
    r"\b(?:doi|sua|thay|them|bo|xoa|chot|xac nhan|hoan tat|tai sao|vi sao|sao lai|the nao|gi vay)\b"
)


def _is_hotel_choice_attempt(user_input: str) -> bool:
    """Whether a reply that failed to resolve was still *trying* to name a hotel.

    True keeps the list up and re-asks (a typo'd name, an out-of-range number).
    False means the user has moved on, and holding the list would trap them.
    """
    stripped = user_input.strip()
    if not stripped:
        return True
    # A bare number is always an attempt, even out of range — never read "3" as a
    # topic change just because the list is shorter than that.
    if stripped.isdigit():
        return True
    if _is_finalization_request(user_input):
        return False
    normalized = _normalize_intent_text(user_input)
    if _OTHER_INTENT_WORDS.search(normalized):
        return False
    if _new_trip_signal(user_input) is not None:
        return False
    return True


def _begin_new_trip_if_requested(session: ChatSession, user_input: str) -> bool:
    signal = _new_trip_signal(user_input)
    if signal is None:
        return False
    fresh_intake = TripIntakeState().with_message(user_input, _get_destination_names())
    if signal != "strong" and not fresh_intake.destination:
        return False
    session.intake_state = fresh_intake
    session.hotel_pref_state = HotelPreferenceState()
    session.pending_trip_change = None
    session.pending_trip_edit_request = None
    session.initial_plan_complete = False
    session.planning_new_trip = True
    return True


def process_chat_turn(session: ChatSession, user_input: str) -> str:
    """Handle exactly one chat turn and return the reply text. Mutates `session`
    in place. Callers own their own input loop / HTTP request cycle — this
    function never blocks on input() and never prints."""
    logger.info("User Input: %s", user_input)

    if os.path.exists(PENDING_HOTEL_SELECTION_FILE):
        tool_response = select_hotel.invoke({"selection": user_input})
        logger.info("Hotel selection response: %s", tool_response)
        # select_hotel deletes the pending file once it resolves a hotel, so the
        # file's survival — not the wording of the reply — is what says it failed.
        picked = not os.path.exists(PENDING_HOTEL_SELECTION_FILE)
        if picked:
            session.initial_plan_complete = not str(tool_response).startswith("SYSTEM ERROR:")
            if session.initial_plan_complete:
                session.planning_new_trip = False
            return tool_response

        if _is_hotel_choice_attempt(user_input):
            return tool_response

        # Not a pick and not an attempt at one. Re-asking here is what trapped
        # people: with a list pending, every later message was read as a choice,
        # so "chốt lịch trình" and "thêm quán cà phê ngày 2" both came back as
        # "mình chưa xác định được khách sạn", forever. Drop the list and let the
        # message be handled for what it actually is.
        logger.info("Reply is not a hotel choice; dropping the pending list")
        _clear_pending_hotel_selection()

    if os.path.exists(CURRENT_TRIP_PLAN_FILE) and _is_finalization_request(user_input):
        tool_response = finalize_trip_plan.invoke({})
        logger.info("Finalization response: %s", tool_response)
        session.initial_plan_complete = not str(tool_response).startswith("SYSTEM ERROR:")
        return tool_response

    has_saved_plan = os.path.exists(CURRENT_TRIP_PLAN_FILE)
    if has_saved_plan and not session.planning_new_trip:
        if not _begin_new_trip_if_requested(session, user_input):
            unsupported_reply = _unsupported_destination_reply(user_input)
            if unsupported_reply:
                logger.info("New-trip request names an unsupported destination")
                return unsupported_reply

    is_saved_plan_edit = has_saved_plan and not session.planning_new_trip
    if is_saved_plan_edit:
        try:
            with open(CURRENT_TRIP_PLAN_FILE, encoding="utf-8") as file_handle:
                current_data = json.load(file_handle)
            planner_request = user_input
            if session.pending_trip_edit_request:
                planner_request = f"{session.pending_trip_edit_request}\nLàm rõ của người dùng: {user_input}"
            edit_plan = plan_trip_edit(planner_request, current_data)
        except (OSError, json.JSONDecodeError, TripEditPlanError) as exc:
            logger.warning("Saved-trip edit planner failed safely: %s", exc)
            return "SYSTEM ERROR: Không thể hiểu an toàn yêu cầu chỉnh sửa này. Vui lòng diễn đạt cụ thể hơn."

        if edit_plan.decision == "clarify":
            session.pending_trip_edit_request = planner_request
            return edit_plan.clarification_question or "Bạn muốn chỉnh sửa phần nào của lịch trình?"
        session.pending_trip_edit_request = None
        if edit_plan.decision == "apply":
            tool_response = execute_trip_edit_request(user_input, edit_plan)
            logger.info("LLM planned modification response: %s", tool_response)
            return tool_response or "SYSTEM ERROR: Không thể áp dụng yêu cầu chỉnh sửa này."

    if False and session.pending_trip_change is not None:
        pending_change = session.pending_trip_change
        day_numbers = parse_day_scope(user_input, _saved_duration_days())
        if not day_numbers:
            return _scope_question(pending_change.requested_time)
        session.pending_trip_change = None
        scoped_request = f"{pending_change.query or ''}; áp dụng cho " + ", ".join(
            f"ngày {day}" for day in day_numbers
        )
        tool_response = modify_trip_plan.invoke({"modification_request": scoped_request})
        logger.info("Deterministic clarified modification response: %s", tool_response)
        return tool_response

    change_intent = None

    if is_saved_plan_edit and change_intent is not None:
        if change_intent.action == "set_latest_outing_start" and not change_intent.day_numbers:
            session.pending_trip_change = change_intent
            return _scope_question(change_intent.requested_time)
        tool_response = modify_trip_plan.invoke({"modification_request": user_input})
        logger.info("Deterministic modification response: %s", tool_response)
        return tool_response

    if not session.initial_plan_complete and not is_saved_plan_edit:
        if not session.intake_state.is_complete:
            destination_names = _get_destination_names()
            session.intake_state = session.intake_state.with_message(user_input, destination_names)
            missing_question = session.intake_state.next_question(destination_names)
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

    for attempt in range(2):
        agent_input = user_input
        if attempt:
            agent_input = (
                f"{user_input}\n"
                "Trả lời người dùng bằng văn bản tiếng Việt. Không xuất JSON hoặc mô phỏng lời gọi công cụ."
            )
        try:
            events = session.agent.stream(
                {"messages": [("user", agent_input)]},
                config=session.config,
                stream_mode="values",
            )

            final_ai_response = None
            tool_output_response = None
            for event in events:
                if "messages" not in event:
                    continue
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
        except Exception:
            logger.exception("Agent provider request failed")
            return (
                "SYSTEM ERROR: Mô hình hội thoại không thể xử lý yêu cầu này. "
                "Vui lòng thử diễn đạt lại yêu cầu cụ thể hơn."
            )

        if tool_output_response:
            logger.info("Final Tool Response Output:\n%s", tool_output_response)
            return tool_output_response
        if final_ai_response and not _looks_like_textual_tool_call(final_ai_response):
            logger.info("Final AI Response: %s", final_ai_response)
            return final_ai_response
        if final_ai_response:
            logger.warning("Discarded textual tool-call JSON from agent (attempt %s)", attempt + 1)
    return "SYSTEM ERROR: Không nhận được phản hồi từ agent."
