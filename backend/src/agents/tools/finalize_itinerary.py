"""Module-level `finalize_trip_plan` tool: `ToolRuntime`/`Command` based, no
TripSession reference (Phase 4, 260802-1437-langgraph-full-orchestration-
and-durable-state).

Finalizing touches the itinerary, so it carries the explicit
`pending_hotel_selection` precondition the hotel-pick gate needs now that
tools are no longer a closed per-session set (see select_hotel.py's
module docstring for the full gate rationale).
"""

from __future__ import annotations

import logging

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from src.agents.state import TripState
from src.i18n import t
from src.services.itinerary_reuse import ItineraryReuseQuery
from src.services.itinerary_store import ItineraryStore, ItineraryStoreError
from src.services.trip_formatter import parse_duration_to_days
from src.services.trip_planner import _current_trip_parameters, _get_destination_id

logger = logging.getLogger(__name__)


@tool
def finalize_trip_plan(runtime: ToolRuntime[None, TripState]) -> Command:
    """Finalize the saved draft only after the user explicitly confirms it."""
    trip_data = runtime.state["trip_data"]
    language = str(runtime.state.get("language") or "vi")
    if trip_data is None:
        reply = t("SYSTEM ERROR: Chưa có kế hoạch để xác nhận. Hãy tạo kế hoạch trước.", language)
        return Command(update={"messages": [ToolMessage(reply, tool_call_id=runtime.tool_call_id)]})

    if runtime.state["pending_hotel_selection"] is not None:
        reply = t("Bạn cần chọn khách sạn trước khi xác nhận lịch trình.", language)
        return Command(update={"messages": [ToolMessage(reply, tool_call_id=runtime.tool_call_id)]})

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
        # Already persisted + finalized above via ItineraryStore — updating
        # trip_data in state is enough; no separate Supabase upsert here.
        if not result.get("embedding_saved", result.get("has_embedding", False)):
            reply = t("Đã xác nhận lịch trình. Phần tìm kiếm tái sử dụng sẽ tự thử lại sau.", language)
        else:
            reply = t("Đã xác nhận lịch trình và lưu làm mẫu có thể tái sử dụng.", language)
        return Command(
            update={"trip_data": trip_data, "messages": [ToolMessage(reply, tool_call_id=runtime.tool_call_id)]}
        )
    except (ItineraryStoreError, ValueError) as exc:
        logger.exception("Trip finalization failed")
        return Command(update={"messages": [ToolMessage(f"SYSTEM ERROR: {exc}", tool_call_id=runtime.tool_call_id)]})
    except Exception as exc:
        logger.exception("Unexpected trip finalization failure")
        return Command(update={"messages": [ToolMessage(f"SYSTEM ERROR: {exc}", tool_call_id=runtime.tool_call_id)]})
