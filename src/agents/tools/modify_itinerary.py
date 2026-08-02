"""Module-level `modify_trip_plan` tool: `ToolRuntime`/`Command` based, no
TripSession reference (Phase 4, 260802-1437-langgraph-full-orchestration-
and-durable-state).

Delegates to `resolve_trip_edit_request` in `src.services.trip_planner` — the
same pure function `process_chat_turn`'s deterministic `_run_edit_draft`
calls (via `src.agents.session.execute_trip_edit_request`, a thin
session-bound wrapper kept there for that caller and for the many existing
tests that monkeypatch it directly). One implementation, two callers,
neither of which can see the other: this tool cannot import from
`src.agents.session` at all — doing so would reintroduce exactly the
circular import this phase removes from the other three tools
(session.py -> graph.py -> this module -> session.py).

Modifying touches the itinerary, so it carries the explicit
`pending_hotel_selection` precondition described in select_hotel.py's module
docstring.
"""

from __future__ import annotations

import logging

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from src.agents.state import TripState
from src.services.trip_edit_planner import TripEditPlanError, plan_trip_edit
from src.services.trip_planner import resolve_trip_edit_request

logger = logging.getLogger(__name__)


@tool
def modify_trip_plan(modification_request: str, runtime: ToolRuntime[None, TripState]) -> Command:
    """Apply a constrained stateless LLM plan to an existing Draft itinerary."""
    trip_data = runtime.state["trip_data"]
    if trip_data is None:
        reply = "SYSTEM ERROR: Chưa có kế hoạch chuyến đi để chỉnh sửa."
        return Command(update={"messages": [ToolMessage(reply, tool_call_id=runtime.tool_call_id)]})

    if runtime.state["pending_hotel_selection"] is not None:
        reply = "Bạn cần chọn khách sạn trước khi chỉnh sửa lịch trình."
        return Command(update={"messages": [ToolMessage(reply, tool_call_id=runtime.tool_call_id)]})

    try:
        plan = plan_trip_edit(modification_request, trip_data)
    except TripEditPlanError as exc:
        logger.warning("Could not safely plan trip edit: %s", exc)
        reply = "SYSTEM ERROR: Không thể hiểu an toàn yêu cầu chỉnh sửa này. Vui lòng diễn đạt cụ thể hơn."
        return Command(update={"messages": [ToolMessage(reply, tool_call_id=runtime.tool_call_id)]})

    reply, updates = resolve_trip_edit_request(trip_data, modification_request, plan)
    reply = reply or "Yêu cầu này không thay đổi lịch trình hiện tại."
    return Command(update={**updates, "messages": [ToolMessage(str(reply), tool_call_id=runtime.tool_call_id)]})
