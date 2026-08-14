from __future__ import annotations

import logging
from typing import Annotated

from langchain.tools import tool
from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from src.i18n import t
from src.services.hotel_selection import resolve_selection

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
def select_place(selection: str, state: Annotated[dict, InjectedState], tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """
    Use this tool whenever a numbered place/attraction list has just been shown and the user's reply is their
    choice (a number like "2" or a place name). Pass their reply text verbatim as `selection`.
    """
    language = str(state.get("language") or "vi")
    pending = state.get("pending_place_selection")

    if not pending:
        return _reply_error(
            t("SYSTEM ERROR: Chưa có danh sách địa điểm nào để chọn.", language),
            tool_call_id,
        )

    raw_options = pending.get("options") or []
    from src.services.trip_scheduler import PlaceCandidate
    options = [
        (data, PlaceCandidate.from_mapping({**data, "category": "Attraction"}))
        for data in raw_options
        if isinstance(data, dict)
    ]
    resolved = resolve_selection(selection, options)
    if not resolved:
        return _reply_error(t("Mình chưa rõ bạn muốn chọn địa điểm nào. Vui lòng thử lại.", language), tool_call_id)

    # In modern graph_v2, the interrupt flow handles place selection directly.
    # This tool is provided for compatibility with qa_node legacy paths.
    return _reply_success(
        t("Đã chọn địa điểm.", language),
        tool_call_id,
        pending_place_selection=None,
    )
