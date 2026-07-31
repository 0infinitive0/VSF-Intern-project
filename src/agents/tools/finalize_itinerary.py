"""Session-bound `finalize_trip_plan` tool factory."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from langchain_core.tools import BaseTool, tool

from src.services.itinerary_reuse import ItineraryReuseQuery
from src.services.itinerary_store import ItineraryStore, ItineraryStoreError
from src.services.trip_formatter import parse_duration_to_days
from src.services.trip_planner import _current_trip_parameters, _get_destination_id

if TYPE_CHECKING:
    from src.agents.session import TripSession

logger = logging.getLogger(__name__)


def build_finalize_trip_plan_tool(session: TripSession) -> BaseTool:
    @tool
    def finalize_trip_plan() -> str:
        """Finalize the saved draft only after the user explicitly confirms it."""
        from src.agents.session import _save_trip_data

        if session.trip_data is None:
            return "SYSTEM ERROR: Chưa có kế hoạch để xác nhận. Hãy tạo kế hoạch trước."
        trip_data = session.trip_data
        try:
            itinerary = (trip_data.get("itineraries") or [{}])[0]
            destination, duration, people, preferences = _current_trip_parameters(trip_data)
            destination_id = str(itinerary.get("destination_id") or _get_destination_id(destination) or "")
            if not destination_id:
                raise ValueError("Không xác định được điểm đến của kế hoạch hiện tại.")
            number_of_people = int("".join(filter(str.isdigit, people)) or 1)
            child_context = f"{people} {preferences}".casefold()
            child_focused = any(
                keyword in child_context
                for keyword in ("trẻ em", "tre em", "children", "child", "kids", "gia đình", "gia dinh")
            )
            reuse_query = ItineraryReuseQuery(
                destination_id=destination_id,
                destination_name=destination,
                duration_days=parse_duration_to_days(duration),
                number_of_adults=number_of_people,
                preferences=tuple(part.strip() for part in preferences.split(",") if part.strip()),
                child_focused=child_focused,
                hotel_id=str(itinerary.get("hotel_id") or (trip_data.get("hotel") or {}).get("id") or ""),
                planning_constraints=dict(itinerary.get("planning_constraints") or {}),
            )
            store = ItineraryStore.from_default()
            store.persist_itinerary_bundle(trip_data)
            result = store.finalize_trip_data(trip_data, reuse_query)
            itinerary["status"] = "Finalized"
            itinerary["summary"] = result.get("summary")
            # Already persisted + finalized above; re-persisting here would resend
            # the bundle to a now-finalized (immutable) row and fail.
            _save_trip_data(session, trip_data, persist_to_supabase=False)
            if not result.get("embedding_saved", result.get("has_embedding", False)):
                return "Đã xác nhận lịch trình. Phần tìm kiếm tái sử dụng sẽ tự thử lại sau."
            return "Đã xác nhận lịch trình và lưu làm mẫu có thể tái sử dụng."
        except (ItineraryStoreError, ValueError) as exc:
            logger.exception("Trip finalization failed")
            return f"SYSTEM ERROR: {exc}"
        except Exception as exc:
            logger.exception("Unexpected trip finalization failure")
            return f"SYSTEM ERROR: {exc}"

    return finalize_trip_plan
