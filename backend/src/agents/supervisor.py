"""LLM router that picks one of six route labels for a chat turn.

`decide_route_by_llm` runs the supervisor and extracts the first tool call's
route label. It never raises: any exception, timeout, or turn that produces no
tool call returns None, so the caller (`process_chat_turn`, via
`validate_route`) falls back to the deterministic `decide_route_by_rules`.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import tool
from langchain_core.messages import SystemMessage, HumanMessage

from src.agents.prompts import SUPERVISOR_ROUTER_PROMPT
from src.agents.routing_decision import route_context_from_state
from src.services.llm import get_fast_llm as get_llm

logger = logging.getLogger(__name__)

@tool
def route_finalize() -> str:
    """The user is confirming/finalizing the current itinerary (e.g. "chốt lịch trình", "xác nhận")."""
    return "finalize"

@tool
def route_new_trip() -> str:
    """The user wants to start a new trip, different from any existing saved itinerary."""
    return "new_trip"

@tool
def route_edit_draft() -> str:
    """The user wants to modify a saved itinerary (change hotel, change an activity, change timing, etc.)."""
    return "edit_draft"

@tool
def route_intake() -> str:
    """The user is providing trip details (destination, duration, people count), or there is no saved itinerary yet."""
    return "intake"

@tool
def route_chat() -> str:
    """None of the above — a general question or small talk."""
    return "chat"


_ROUTE_TOOLS = [
    route_finalize,
    route_new_trip,
    route_edit_draft,
    route_intake,
    route_chat,
]

_TOOL_NAME_TO_ROUTE: dict[str, str] = {t.name: t.name.removeprefix("route_") for t in _ROUTE_TOOLS}


def _state_summary(session: Any) -> str:
    """State the supervisor may look at: booleans and counts only — never
    destination/duration/people values or venue/hotel records (D1, D2)."""
    context = route_context_from_state(session.state)
    pending_hotels = "không có"
    if context.has_pending_hotel_selection:
        options = (getattr(session, "pending_hotel_selection", None) or {}).get("options") or []
        names = ", ".join(str(option.get("name", "")) for option in options if isinstance(option, dict))
        pending_hotels = f"CÓ ({len(options)} khách sạn: {names})" if names else f"CÓ ({len(options)} khách sạn)"

    def _yn(value: bool) -> str:
        return "có" if value else "chưa"

    return (
        "[Trạng thái phiên hiện tại — chỉ để chọn tuyến, không phải sự thật chuyến đi]\n"
        f"- Danh sách khách sạn đang chờ người dùng chọn: {pending_hotels}\n"
        f"- Đã có lịch trình đã lưu: {_yn(context.has_trip_data)}\n"
        f"- Lịch trình đã được chốt (finalized): {_yn(context.is_trip_finalized)}\n"
        f"- Đang trong quá trình lên một chuyến đi mới: {_yn(context.planning_new_trip)}\n"
        f"- Đã hoàn tất thông tin điểm đến/thời gian/số người: {_yn(context.intake_complete)}\n"
        f"- Đã hoàn tất ngân sách khách sạn: {_yn(context.hotel_prefs_complete)}\n"
        f"- Đang chờ người dùng làm rõ một yêu cầu chỉnh sửa trước đó: "
        f"{_yn(context.has_pending_edit_clarification)}\n"
    )


def decide_route_by_llm(session: Any, user_input: str) -> str | None:
    """Run the supervisor and return the first route label it calls, or None
    on any failure (exception, no tool call, or an unrecognized tool name)."""
    try:
        llm = get_llm(temperature=0)
        llm_with_tools = llm.bind_tools(_ROUTE_TOOLS)
        
        message = f"{_state_summary(session)}\nTin nhắn người dùng: {user_input}"
        
        messages = [
            SystemMessage(content=SUPERVISOR_ROUTER_PROMPT),
            HumanMessage(content=message)
        ]
        
        response = llm_with_tools.invoke(messages)
        
        if response.tool_calls:
            # Take the first call only
            return _TOOL_NAME_TO_ROUTE.get(response.tool_calls[0]["name"])
        return None
    except Exception:
        logger.exception("Supervisor router failed; falling back to regex routing")
        return None
