"""`search_places` — Phase 13 (`phase-13-place-search.md`): on-demand place
search ("tìm nhà hàng xung quanh") for `qa_node`'s ReAct tool list.

`destination` is an explicit tool argument, not read from graph state:
`qa_node`'s subgraph shares only the `messages` channel with the parent
graph (see `nodes/qa_node.py`'s docstring) — `travel_state` is structurally
unreachable from inside it. The model already has the destination from the
conversation history it does share, so it fills the argument itself rather
than this tool reaching for state that was never there.

Center resolution reuses Phase 8's `search_center.resolve_center` — no
second center implementation, per the plan's own requirement.
"""

from __future__ import annotations

import logging

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from src.i18n import t
from src.services.place_search import search_attraction_candidates
from src.services.search_center import resolve_center
from src.services.supabase_search import DEFAULT_NEARBY_SEARCH_RADIUS_KM
from src.services.trip_planner import _get_destination_id

logger = logging.getLogger(__name__)


@tool
def search_places(
    query: str,
    destination: str,
    near: str | None = None,
    category: str | None = None,
    limit: int = 10,
    *,
    runtime: ToolRuntime,
) -> Command:
    """Search for places (restaurants, attractions, cafes) matching a query.

    `destination` is the trip's destination -- infer it from the
    conversation (e.g. "Đà Nẵng"). If `near` is given, searches near that
    named landmark (an attraction or a hotel); otherwise this asks the user
    for a center rather than guessing one (Phase 8's rule: never let the
    model calculate geographic distance). `category` is currently unused --
    reserved for a future category filter, not yet supported by the
    underlying search.
    """
    language = "vi"
    tool_call_id = runtime.tool_call_id

    destination_id = _get_destination_id(destination)
    if not destination_id:
        reply = t("Không tìm thấy dữ liệu điểm đến cho {dest}.", language, dest=destination)
        return Command(update={"messages": [ToolMessage(reply, tool_call_id=tool_call_id)]})

    resolution = resolve_center(
        destination_id=destination_id,
        named_place=near,
        selected_hotel_coordinates=None,  # no hotel-selection concept reachable from qa_node yet
    )
    if not resolution.resolved:
        reply = t(
            "Bạn muốn tìm '{query}' gần đâu? (vd: gần một địa danh cụ thể)",
            language,
            query=query,
        )
        return Command(update={"messages": [ToolMessage(reply, tool_call_id=tool_call_id)]})

    try:
        candidates = search_attraction_candidates(
            query,
            destination_id,
            match_count=limit,
            root_latitude=resolution.latitude,
            root_longitude=resolution.longitude,
            max_radius_km=DEFAULT_NEARBY_SEARCH_RADIUS_KM,
        )
    except Exception as exc:
        logger.exception("search_places: search failed")
        reply = t("Tìm địa điểm thất bại: {error}", language, error=str(exc))
        return Command(update={"messages": [ToolMessage(reply, tool_call_id=tool_call_id)]})

    if not candidates:
        reply = t("Không tìm thấy địa điểm nào phù hợp.", language)
        return Command(update={"messages": [ToolMessage(reply, tool_call_id=tool_call_id)]})

    lines = [t("Mình tìm được {count} địa điểm phù hợp:", language, count=len(candidates))]
    for idx, candidate in enumerate(candidates, 1):
        line = f"{idx}. {candidate.name}"
        if candidate.description:
            line += f" — {candidate.description}"
        if candidate.rating:
            line += f" ({candidate.rating}★)"
        lines.append(line)

    reply = "\n".join(lines)
    return Command(update={"messages": [ToolMessage(reply, tool_call_id=tool_call_id)]})
