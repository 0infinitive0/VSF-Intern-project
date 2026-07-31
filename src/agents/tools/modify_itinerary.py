"""Session-bound `modify_trip_plan` tool factory."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from langchain_core.tools import BaseTool, tool

from src.services.trip_edit_planner import TripEditPlanError, plan_trip_edit

if TYPE_CHECKING:
    from src.agents.session import TripSession

logger = logging.getLogger(__name__)


def build_modify_trip_plan_tool(session: TripSession) -> BaseTool:
    @tool
    def modify_trip_plan(modification_request: str) -> str:
        """Apply a constrained stateless LLM plan to an existing Draft itinerary."""
        from src.agents.session import execute_trip_edit_request

        if session.trip_data is None:
            return "SYSTEM ERROR: Chưa có kế hoạch chuyến đi để chỉnh sửa."
        try:
            plan = plan_trip_edit(modification_request, session.trip_data)
        except TripEditPlanError as exc:
            logger.warning("Could not safely plan trip edit: %s", exc)
            return "SYSTEM ERROR: Không thể hiểu an toàn yêu cầu chỉnh sửa này. Vui lòng diễn đạt cụ thể hơn."
        result = execute_trip_edit_request(session, modification_request, plan)
        return result or "Yêu cầu này không thay đổi lịch trình hiện tại."

    return modify_trip_plan
