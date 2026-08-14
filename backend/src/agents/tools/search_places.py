import logging
from typing import Any

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from src.agents.graph.state import TravelGraphState
from src.domain.travel_state import TravelState
from src.services.place_search import search_attraction_candidates
from src.services.search_center import resolve_center

logger = logging.getLogger(__name__)


@tool
def search_places(
    query: str,
    near: str | None = None,
    category: str | None = None,
    limit: int = 10,
    *,
    runtime: ToolRuntime[None, TravelGraphState],
) -> Command:
    """
    Search for places (restaurants, attractions, cafes) matching a query.
    If 'near' is provided, it searches near that named place. If 'near' is omitted, it searches near the selected hotel.
    """
    state = runtime.state
    travel_state = TravelState.from_dict(state.get("travel_state") or {})
    destination_id = str(travel_state.get("destination.id").value or "")
    language = str(state.get("language") or "vi")
    
    if not destination_id:
        reply = "Lỗi: Không xác định được điểm đến." if language == "vi" else "Error: Destination not set."
        return Command(update={"messages": [ToolMessage(reply, tool_call_id=runtime.tool_call_id)]})
    
    # 1. Resolve Center
    resolution = resolve_center(
        destination_id=destination_id,
        named_place=near,
        selected_hotel_coordinates=None  # Not supported in graph state yet
    )
    
    if not resolution.resolved:
        reply = (
            f"Bạn muốn tìm '{query}' gần đâu? (Ví dụ: gần khách sạn, hoặc gần một địa danh cụ thể)"
            if language == "vi" else
            f"Where would you like to search for '{query}' near? (e.g. near the hotel or a specific landmark)"
        )
        return Command(update={"messages": [ToolMessage(reply, tool_call_id=runtime.tool_call_id)]})
    
    # 2. Search
    try:
        candidates = search_attraction_candidates(
            query=query,
            destination_id=destination_id,
            match_count=limit,
            root_latitude=resolution.latitude,
            root_longitude=resolution.longitude,
        )
    except Exception as exc:
        logger.error("Failed to search places: %s", exc)
        reply = "Lỗi: Tìm kiếm thất bại." if language == "vi" else "Error: Search failed."
        return Command(update={"messages": [ToolMessage(reply, tool_call_id=runtime.tool_call_id)]})
    
    if not candidates:
        reply = "Không tìm thấy địa điểm nào phù hợp." if language == "vi" else "No places found matching the criteria."
        return Command(update={"messages": [ToolMessage(reply, tool_call_id=runtime.tool_call_id)]})
    
    lines = []
    for idx, c in enumerate(candidates, 1):
        lines.append(f"{idx}. {c.name}")
        if c.description:
            lines.append(f"   {c.description}")
        if c.rating:
            lines.append(f"   Rating: {c.rating}")
        if c.category:
            lines.append(f"   Category: {c.category}")
    
    reply = "\n".join(lines)
    return Command(update={"messages": [ToolMessage(reply, tool_call_id=runtime.tool_call_id)]})
