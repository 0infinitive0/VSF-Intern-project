"""Module-level `select_hotel` tool: `ToolRuntime`/`Command` based, no
TripSession reference (Phase 4, 260802-1437-langgraph-full-orchestration-
and-durable-state).

`select_hotel` is the tool the hotel-pick gate hinges on: it is the only
tool that may turn a pending hotel selection into `trip_data`. Before this
phase, that guarantee was *structural* — `generate_full_itinerary` was
simply never registered with `create_react_agent`. Tools are no longer a
closed per-session set, so that guarantee is gone; this tool's own
`pending_hotel_selection` check (it refuses to act without one) is now the
*asserted* replacement. Phase 2's gate invariant test is what proves this
tool doesn't leak an itinerary through any other path.
"""

from __future__ import annotations

import logging

from langchain.tools import tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command
from typing import Annotated
from langchain_core.tools import InjectedToolCallId
from langgraph.prebuilt import InjectedState

from src.i18n import t
from src.services.hotel_selection import resolve_selection
from src.services.trip_formatter import format_hotel_options
from src.services.trip_planner import build_selected_hotel_trip
from src.services.trip_scheduler import PlaceCandidate

logger = logging.getLogger(__name__)


def _reply_success(text: str, tool_call_id: str | None, **extra_updates: object) -> Command:
    return Command(
        goto="__end__",
        update={**extra_updates, "messages": [ToolMessage(text, tool_call_id=tool_call_id)]}
    )

def _reply_error(text: str, tool_call_id: str | None, **extra_updates: object) -> Command:
    return Command(
        update={**extra_updates, "messages": [ToolMessage(text, tool_call_id=tool_call_id)]}
    )

@tool
def select_hotel(selection: str, state: Annotated[dict, InjectedState], tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """
    Use this tool whenever a numbered hotel list has just been shown and the user's reply is their
    choice (a number like "2" or a hotel name). Pass their reply text verbatim as `selection`.
    """
    logger.warning("Inside select_hotel! state keys: %s", state.keys())
    pending = state.get("pending_hotel_selection")
    logger.warning("Inside select_hotel! pending_hotel_selection is None: %s", pending is None)
    if pending:
        logger.warning("Inside select_hotel! pending keys: %s", pending.keys())
        logger.warning("Inside select_hotel! pending options count: %s", len(pending.get("options") or []))

    session_id = "poc_trip_planner_1"
    language = str(state.get("language") or "vi")

    if not pending:
        return _reply_error(
            t(
                "SYSTEM ERROR: Chưa có danh sách khách sạn nào để chọn. Hãy tạo gợi ý khách sạn trước.",
                language,
            ),
            tool_call_id,
        )

    raw_options = pending.get("options") or []
    options = [
        (data, PlaceCandidate.from_mapping({**data, "category": "Hotel"}))
        for data in raw_options
        if isinstance(data, dict)
    ]
    resolved = resolve_selection(selection, options)
    if not resolved:
        reply = t(
            "Mình chưa xác định được đúng khách sạn bạn muốn chọn, bạn trả lời rõ hơn giúp mình nhé "
            "(số thứ tự hoặc tên khách sạn).\n------\n{options}",
            language,
            options=format_hotel_options(options, language),
        )
        return _reply_error(reply, tool_call_id)

    hotel_data, _candidate = resolved
    mode = str(pending.get("mode") or "new_trip")
    intake_context = pending.get("intake_context", "") or ""
    current_trip_data = state.get("trip_data")
    if mode in {"change_hotel", "replace_trip_preferences"}:
        if current_trip_data is None:
            return _reply_error(
                t("SYSTEM ERROR: Không còn kế hoạch chuyến đi để đổi khách sạn.", language),
                tool_call_id,
                pending_hotel_selection=None,
                initial_plan_complete=True,
            )
        itinerary = (current_trip_data.get("itineraries") or [{}])[0]
        if isinstance(itinerary, dict) and str(itinerary.get("status") or "").casefold() == "finalized":
            return _reply_error(
                t("Kế hoạch đã xác nhận không thể chỉnh sửa. Hãy tạo một kế hoạch mới nếu cần thay đổi.", language),
                tool_call_id,
                pending_hotel_selection=None,
                initial_plan_complete=True,
            )

    try:
        generated = build_selected_hotel_trip(
            pending,
            hotel_data,
            current_trip_data=current_trip_data if mode in {"change_hotel", "replace_trip_preferences"} else None,
            session_id=session_id,
            intake_context=intake_context,
            language=language,
        )
    except Exception as exc:
        logger.exception("Hotel selection failed")
        error_text = str(exc)
        return _reply_error(
            error_text if error_text.startswith("SYSTEM ERROR:") else f"SYSTEM ERROR: {error_text}",
            tool_call_id,
        )

    return _reply_success(
        t("Đã chọn khách sạn. Lịch trình của bạn đã sẵn sàng trong tab Lịch trình.", language),
        tool_call_id,
        trip_data=generated.trip_data,
        pending_hotel_selection=None,
        initial_plan_complete=True,
    )
