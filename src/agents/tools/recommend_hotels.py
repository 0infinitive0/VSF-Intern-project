"""Module-level `recommend_hotels` tool: `ToolRuntime`/`Command` based, no
TripSession reference (Phase 4, 260802-1437-langgraph-full-orchestration-
and-durable-state).

Previously imported `_save_pending_hotel_selection` from `src.agents.session`
*inside* the function body to dodge a circular import — direct evidence the
dependency ran the wrong way. Returning a `Command` instead removes the
cycle entirely: this module has no reason to import anything from
`src.agents.session` at all now.
"""

from __future__ import annotations

import logging
from datetime import datetime

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from src.agents.nodes.intake import validate_trip_basics
from src.agents.state import TripState
from src.services.hotel_selection import (
    lookup_sea_view_hotel_ids,
    rank_hotel_candidates,
    select_hotel_candidates,
)
from src.services.trip_formatter import format_hotel_options
from src.services.trip_planner import _get_destination_id

logger = logging.getLogger(__name__)


@tool
def recommend_hotels(
    destination: str = "",
    duration: str = "",
    people: str = "",
    preferences: str = "",
    hotel_preferences: str = "",
    target_price: str = "",
    min_price: str = "",
    max_price: str = "",
    hotel_amenity_prefs: str = "",
    *,
    runtime: ToolRuntime[None, TripState],
) -> Command:
    """
    CRITICAL: Use this tool ONCE destination, duration, and number of people are all known, to show
    a ranked list of real hotel options. This is the ONLY way to start planning a new trip — never
    call `generate_full_itinerary` yourself. If the user mentioned specific hotel wants (star rating,
    view, amenities...), pass them in `hotel_preferences`. `target_price`/`min_price`/`max_price`/
    `hotel_amenity_prefs` are usually pre-resolved by the guided budget/amenity intake in
    terminal_chat.py (a tier pick like "tầm trung" resolves to a real min/max range, e.g. 800000/
    2500000) — but if you are handling trip planning yourself (e.g. a second trip request later in
    the same conversation) and the user states a budget, convert it to a plain VND number yourself:
    a single number (e.g. "1 triệu" -> target_price="1000000") is used as a ceiling only; if the user
    gives an actual range (e.g. "1-2 triệu"), pass min_price/max_price instead. These matter more
    than the qualitative wants in `hotel_preferences` since they actually filter results by price.
    After this returns, the user's next reply must be handled by `select_hotel`, not by calling this
    tool or generate_full_itinerary again.
    """
    clean_destination, error = validate_trip_basics(destination, duration, people)
    if error:
        return Command(update={"messages": [ToolMessage(error, tool_call_id=runtime.tool_call_id)]})

    destination_id = _get_destination_id(clean_destination)
    if not destination_id:
        reply = f"SYSTEM ERROR: Không tìm thấy dữ liệu điểm đến cho {clean_destination}."
        return Command(update={"messages": [ToolMessage(reply, tool_call_id=runtime.tool_call_id)]})
    destination_id = str(destination_id)

    hotel_query = hotel_preferences.strip() or None
    parsed_target_price = float(target_price) if target_price.strip() else None
    parsed_min_price = float(min_price) if min_price.strip() else None
    parsed_max_price = float(max_price) if max_price.strip() else None
    if parsed_min_price is None and parsed_max_price is None and parsed_target_price is not None:
        # No explicit range given (e.g. a caller that only knows the older single-number
        # target_price) — fall back to treating it as a ceiling-only budget.
        parsed_max_price = parsed_target_price
    amenity_pref_set = frozenset(tag.strip() for tag in hotel_amenity_prefs.split(",") if tag.strip())

    try:
        options = select_hotel_candidates(
            clean_destination,
            destination_id,
            people,
            hotel_query=hotel_query,
            min_price=parsed_min_price,
            max_price=parsed_max_price,
        )
        sea_view_hotel_ids = (
            lookup_sea_view_hotel_ids([data["id"] for data, _candidate in options])
            if "sea_view" in amenity_pref_set
            else frozenset()
        )
        options = rank_hotel_candidates(
            options,
            target_price=parsed_target_price,
            amenity_prefs=amenity_pref_set,
            sea_view_hotel_ids=sea_view_hotel_ids,
        )
    except Exception as exc:
        logger.exception("Hotel recommendation failed")
        return Command(update={"messages": [ToolMessage(f"SYSTEM ERROR: {exc}", tool_call_id=runtime.tool_call_id)]})

    if not options:
        reply = (
            f"SYSTEM ERROR: Không tìm thấy khách sạn có tọa độ hợp lệ tại {clean_destination}; "
            "không thể gợi ý khách sạn."
        )
        return Command(update={"messages": [ToolMessage(reply, tool_call_id=runtime.tool_call_id)]})

    pending_payload = {
        "mode": "new_trip",
        "destination": clean_destination,
        "destination_id": destination_id,
        "duration": duration,
        "people": people,
        "preferences_text": preferences,
        "hotel_query": hotel_query,
        "created_at": datetime.now().isoformat(),
        "options": [data for data, _candidate in options],
    }
    reply = format_hotel_options(options)
    return Command(
        update={
            "pending_hotel_selection": pending_payload,
            "messages": [ToolMessage(reply, tool_call_id=runtime.tool_call_id)],
        }
    )
