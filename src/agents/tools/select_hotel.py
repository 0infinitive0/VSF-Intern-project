"""Session-bound `select_hotel` tool factory."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from langchain_core.tools import BaseTool, tool

from src.services.hotel_selection import resolve_hotel_selection
from src.services.trip_formatter import format_hotel_options, format_trip_response_from_json
from src.services.trip_planner import _build_trip_data, _generate_and_save_itinerary, _reapply_planning_constraints
from src.services.trip_scheduler import PlaceCandidate

if TYPE_CHECKING:
    from src.agents.session import TripSession

logger = logging.getLogger(__name__)


def build_select_hotel_tool(session: TripSession) -> BaseTool:
    @tool
    def select_hotel(selection: str) -> str:
        """
        Use this tool whenever a numbered hotel list has just been shown and the user's reply is their
        choice (a number like "2" or a hotel name). Pass their reply text verbatim as `selection`.
        """
        from src.agents.session import _clear_pending_hotel_selection, _save_trip_data

        pending = session.pending_hotel_selection
        if not pending:
            return "SYSTEM ERROR: Chưa có danh sách khách sạn nào để chọn. Hãy tạo gợi ý khách sạn trước."

        raw_options = pending.get("options") or []
        options = [
            (data, PlaceCandidate.from_mapping({**data, "category": "Hotel"}))
            for data in raw_options
            if isinstance(data, dict)
        ]
        resolved = resolve_hotel_selection(selection, options)
        if not resolved:
            return (
                "Mình chưa xác định được đúng khách sạn bạn muốn chọn, bạn trả lời rõ hơn giúp mình nhé "
                "(số thứ tự hoặc tên khách sạn).\n------\n" + format_hotel_options(options)
            )

        hotel_data, _candidate = resolved
        mode = pending.get("mode", "new_trip")
        destination = pending.get("destination", "")
        duration = pending.get("duration", "")
        start_date = pending.get("start_date")
        end_date = pending.get("end_date")
        people = pending.get("people", "")
        preferences = pending.get("preferences_text", "")
        stay_kwargs = {}
        if start_date is not None or end_date is not None:
            stay_kwargs = {"start_date": start_date, "end_date": end_date}

        if mode in {"change_hotel", "replace_trip_preferences"}:
            if session.trip_data is None:
                _clear_pending_hotel_selection(session)
                return "SYSTEM ERROR: Không còn kế hoạch chuyến đi để đổi khách sạn."
            current_data = session.trip_data

            saved_itinerary = (current_data.get("itineraries") or [{}])[0]
            if isinstance(saved_itinerary, dict) and str(saved_itinerary.get("status") or "").casefold() == "finalized":
                _clear_pending_hotel_selection(session)
                return "Kế hoạch đã xác nhận không thể chỉnh sửa. Hãy tạo một kế hoạch mới nếu cần thay đổi."

            try:
                planning_constraints = (
                    pending.get("planning_constraints") or {} if mode == "change_hotel" else {}
                )
                updated_data = _build_trip_data(
                    destination,
                    duration,
                    people,
                    preferences,
                    preselected_hotel=hotel_data,
                    planning_constraints=planning_constraints,
                    session_id=session.session_id,
                    **stay_kwargs,
                )
            except Exception as exc:
                logger.exception("Hotel change failed")
                return f"SYSTEM ERROR: {exc}"

            adjustment = (
                "Đã đổi khách sạn và lập lại toàn bộ các cụm địa điểm theo vị trí mới."
                if mode == "change_hotel"
                else "Đã cập nhật thông tin chuyến đi, chọn lại khách sạn và lập một lịch trình mới."
            )
            updated_data.setdefault("adjustments", []).append(adjustment)
            updated_itinerary = (updated_data.get("itineraries") or [{}])[0]
            if isinstance(updated_itinerary, dict):
                updated_itinerary["status"] = "Draft"
                updated_itinerary.pop("summary", None)
                if mode == "change_hotel" and planning_constraints:
                    updated_itinerary["planning_constraints"] = planning_constraints
                    updated_data.setdefault("adjustments", []).extend(
                        _reapply_planning_constraints(updated_data)
                    )
            _save_trip_data(session, updated_data)
            _clear_pending_hotel_selection(session)
            return format_trip_response_from_json(updated_data)

        result = _generate_and_save_itinerary(
            destination,
            duration,
            people,
            preferences,
            preselected_hotel=hotel_data,
            session_id=session.session_id,
            save=lambda trip_data: _save_trip_data(session, trip_data),
            **stay_kwargs,
        )
        if not str(result).startswith("SYSTEM ERROR:"):
            _clear_pending_hotel_selection(session)
        return result

    return select_hotel
