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
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from src.agents.nodes.intake import validate_trip_basics
from src.agents.state import TripState
from src.i18n import t
from src.services.hotel_selection import (
    lookup_sea_view_hotel_ids,
    rank_hotel_candidates,
    select_hotel_candidates,
)
from src.services.trip_formatter import format_hotel_options
from src.services.trip_planner import _get_destination_id

logger = logging.getLogger(__name__)


class PreferenceItem(BaseModel):
    id: str = Field(description="English identifier (e.g. 'swimming_pool', 'near_center')")
    label: str = Field(description="Vietnamese display name (e.g. 'Hồ bơi', 'Gần trung tâm')")


@tool
def recommend_hotels(
    destination: str = "",
    duration: str = "",
    start_date: str = "",
    end_date: str = "",
    people: str = "",
    preferences: str = "",
    hotel_preferences: str = "",
    target_price: str = "",
    min_price: str = "",
    max_price: str = "",
    hotel_amenity_prefs: str = "",
    intake_context: str = "",
    exclude_hotel_ids: Any = None,
    *,
    runtime: ToolRuntime[None, TripState],
) -> Command:
    """
    CRITICAL: Use this tool whenever you need to search for hotels, recommend hotels, or when the user updates their hotel preferences (e.g., "khách sạn có hồ bơi"). Destination, duration, and number of people must be known. This is the ONLY way to start planning a new trip — never
    call `generate_full_itinerary` yourself. If the user mentioned specific hotel wants (star rating,
    view, amenities...), pass them in `hotel_preferences` as a list of dicts with 'id' and 'label'.
    DO NOT include budget or price information (like '1-2 triệu') in `preferences` or `hotel_preferences`. Use `min_price` and `max_price` for budget.
    `target_price`/`min_price`/`max_price`/
    `hotel_amenity_prefs` are usually pre-resolved by the guided budget/amenity intake in
    terminal_chat.py (a tier pick like "tầm trung" resolves to a real min/max range, e.g. 800000/
    2500000) — but if you are handling trip planning yourself (e.g. a second trip request later in
    the same conversation) and the user states a budget, convert it to a plain VND number yourself:
    a single number (e.g. "1 triệu" -> target_price="1000000") is used as a ceiling only; if the user
    gives an actual range (e.g. "1-2 triệu"), pass min_price/max_price instead. These matter more
    than the qualitative wants in `hotel_preferences` since they actually filter results by price.
    `intake_context` is extra free-text travel-style context (pace, day rhythm, free-text notes) from
    the intake form, carried through to itinerary theme generation; leave it empty when unset.
    After this returns, the user's next reply must be handled by `select_hotel`, not by calling this
    tool or generate_full_itinerary again.
    
    Args:
        destination: The destination city.
        duration: The duration of the trip (e.g. '3 ngày').
        start_date: The start date (YYYY-MM-DD).
        end_date: The end date (YYYY-MM-DD).
        people: Number of people.
        preferences: General trip preferences. MUST be a JSON array of objects as a string, e.g. '[{"id": "...", "label": "..."}]'. Do NOT include budget or price info here.
        hotel_preferences: Specific hotel preferences. MUST be a JSON array of objects as a string, e.g. '[{"id": "swimming_pool", "label": "Hồ bơi"}]'. Do NOT include budget or price info here.
        target_price: Target budget per night.
        min_price: Minimum budget per night.
        max_price: Maximum budget per night.
        hotel_amenity_prefs: Pre-resolved amenity preferences.
        intake_context: Additional intake context.
        exclude_hotel_ids: List of hotel IDs to exclude.
    """
    clean_destination, error = validate_trip_basics(destination, duration, people)
    if error:
        return Command(update={"messages": [ToolMessage(error, tool_call_id=runtime.tool_call_id)]})
    language = str(runtime.state.get("language") or "vi")

    # Anti-loop mechanism: restrict tool to 1 call per user message if args are identical
    messages = runtime.state.get("messages", [])
    if len(messages) >= 3 and getattr(messages[-2], "type", "") == "tool" and getattr(messages[-3], "type", "") == "ai":
        last_ai_msg = messages[-3]
        curr_ai_msg = messages[-1]
        
        if hasattr(last_ai_msg, "tool_calls") and last_ai_msg.tool_calls and hasattr(curr_ai_msg, "tool_calls") and curr_ai_msg.tool_calls:
            last_calls = last_ai_msg.tool_calls
            current_calls = curr_ai_msg.tool_calls
            if last_calls[0]["name"] == "recommend_hotels" and current_calls[0]["name"] == "recommend_hotels":
                # Compare args (excluding id)
                if last_calls[0]["args"] == current_calls[0]["args"]:
                    logger.warning("[recommend_hotels] ANTI-LOOP TRIGGERED!")
                    reply = t(
                        "SYSTEM ERROR: Lỗi: Bạn đã gọi công cụ này với cùng tham số rồi. ĐỪNG gọi lại. Hãy trả lời người dùng bằng kết quả đã tìm được.",
                        language
                    ) if language == "vi" else "SYSTEM ERROR: Error: You already called this tool with the same args. DO NOT CALL IT AGAIN. Answer the user with the result."
                    return Command(update={"messages": [ToolMessage(reply, tool_call_id=runtime.tool_call_id)]})

    clean_destination = destination.strip()
    try:
        parsed_start_date = date.fromisoformat(start_date)
        parsed_end_date = date.fromisoformat(end_date)
    except ValueError:
        reply = t(
            "SYSTEM ERROR: Cần có ngày bắt đầu và ngày kết thúc hợp lệ (YYYY-MM-DD) để tìm khách sạn.",
            language,
        )
        return Command(update={"messages": [ToolMessage(reply, tool_call_id=runtime.tool_call_id)]})
    if parsed_end_date <= parsed_start_date:
        reply = t("SYSTEM ERROR: Ngày kết thúc phải sau ngày bắt đầu.", language)
        return Command(update={"messages": [ToolMessage(reply, tool_call_id=runtime.tool_call_id)]})

    trip_data = runtime.state.get("trip_data")
    if trip_data and trip_data.destination and trip_data.destination.id:
        destination_id = str(trip_data.destination.id)
    else:
        intake = runtime.state.get("intake") or {}
        intake_destination = intake.get("destination")
        target_destination = intake_destination if intake_destination else clean_destination
        destination_id = _get_destination_id(target_destination)
        if not destination_id:
            reply = t(
                "SYSTEM ERROR: Không tìm thấy dữ liệu điểm đến cho {dest}.",
                language,
                dest=target_destination,
            )
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

    # A follow-up search must start beyond the hotels already shown to the user.
    # Keep an explicit list too so callers that already know prior IDs can use the
    # same contract without depending on session state.
    existing_pending = runtime.state.get("pending_hotel_selection") or {}
    existing_options = existing_pending.get("options", [])
    
    # Check if core parameters changed. If so, we must discard the old list.
    if existing_pending:
        old_dest = existing_pending.get("destination", "")
        old_start = existing_pending.get("start_date", "")
        old_end = existing_pending.get("end_date", "")
        
        if (old_dest != target_destination or 
            old_start != start_date or 
            old_end != end_date):
            existing_options = []

    if isinstance(exclude_hotel_ids, str):
        if exclude_hotel_ids.lower() in ("null", "none", "[]", ""):
            exclude_hotel_ids = []
        else:
            try:
                import json
                exclude_hotel_ids = json.loads(exclude_hotel_ids)
            except Exception:
                exclude_hotel_ids = [exclude_hotel_ids]
    if not isinstance(exclude_hotel_ids, list):
        exclude_hotel_ids = []

    requested_ids = [str(hotel_id).strip() for hotel_id in exclude_hotel_ids if str(hotel_id).strip()]
    excluded_ids = list(dict.fromkeys(requested_ids))

    try:
        selection_kwargs = {
            "hotel_query": hotel_query,
            "min_price": parsed_min_price,
            "max_price": parsed_max_price,
            "start_date": start_date,
            "end_date": end_date,
        }
        if excluded_ids:
            selection_kwargs["exclude_hotel_ids"] = excluded_ids
        options = select_hotel_candidates(
            clean_destination,
            destination_id,
            people,
            **selection_kwargs,
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
        reply = t(
            "SYSTEM ERROR: Không tìm thấy khách sạn có tọa độ hợp lệ tại {dest}; không thể gợi ý khách sạn.",
            language,
            dest=clean_destination,
        )
        return Command(update={"messages": [ToolMessage(reply, tool_call_id=runtime.tool_call_id)]})

    import json

    # Fallback initialization
    if preferences is None:
        preferences = ""
    if hotel_preferences is None:
        hotel_preferences = ""

    def parse_prefs(pref_str: str) -> list[dict]:
        pref_str = pref_str.strip()
        if not pref_str:
            return []
        try:
            # If it's a JSON array string like '[{"id": "x", "label": "y"}]'
            parsed = json.loads(pref_str)
            if isinstance(parsed, list):
                return parsed
        except Exception:
            pass
        # Fallback for LLMs that just return a normal string instead of a JSON array
        # E.g., "khách sạn có hồ bơi"
        return [{"id": pref_str, "label": pref_str}]

    parsed_hotel_prefs = parse_prefs(hotel_preferences)
    parsed_general_prefs = parse_prefs(preferences)
    
    def is_valid_pref(p_dict: dict) -> bool:
        if not p_dict or not p_dict.get("id") or not p_dict.get("label"):
            return False
        # Filter out budget-related text that the LLM mistakenly includes
        text_to_check = str(p_dict["id"]).lower() + " " + str(p_dict["label"]).lower()
        invalid_keywords = ["ngân sách", "triệu", "vnd", "usd", "giá", "rẻ", "đắt", "budget", "price"]
        if any(kw in text_to_check for kw in invalid_keywords):
            return False
        return True

    # Determine current preference objects
    current_prefs_dict = {}
    for p in parsed_hotel_prefs:
        p_dict = p.model_dump() if hasattr(p, "model_dump") else p if isinstance(p, dict) else None
        if is_valid_pref(p_dict):
            current_prefs_dict[str(p_dict["id"])] = p_dict
    for p in parsed_general_prefs:
        p_dict = p.model_dump() if hasattr(p, "model_dump") else p if isinstance(p, dict) else None
        if is_valid_pref(p_dict):
            current_prefs_dict[str(p_dict["id"])] = p_dict
            
    # For hotel amenity string, we don't have a good label, so we use the id for both
    if hotel_amenity_prefs.strip():
        for tag in hotel_amenity_prefs.split(","):
            tag = tag.strip()
            if tag:
                current_prefs_dict[tag] = {"id": tag, "label": tag}
    
    current_pref_ids = list(current_prefs_dict.keys())
    
    # Compare and merge with existing options
    existing_by_id = {str(opt.get("id")): opt for opt in existing_options if opt.get("id")}
    
    for data, _candidate in options:
        hotel_id = str(data.get("id"))
        if not hotel_id:
            continue
        
        if hotel_id in existing_by_id:
            prefs = existing_by_id[hotel_id].get("preferences", [])
            for cp_id in current_pref_ids:
                if cp_id not in prefs:
                    prefs.append(cp_id)
            existing_by_id[hotel_id]["preferences"] = prefs
        else:
            data["preferences"] = list(current_pref_ids)
            existing_by_id[hotel_id] = data
            
    combined_options = list(existing_by_id.values())
    
    # Sort by number of matched preferences (DESC) and lowest_price (ASC)
    combined_options.sort(key=lambda x: (-len(x.get("preferences", [])), float(x.get("lowest_price", 0) or 0)))
    
    # We maintain all_preferences dict to ensure we have labels for all previously saved IDs
    # But wait, existing_pending only has active_preferences and all_preferences in the payload.
    # We should merge them.
    all_prefs_dict = {}
    for p in existing_pending.get("all_preferences", []):
        if isinstance(p, dict) and "id" in p:
            if is_valid_pref(p):
                all_prefs_dict[p["id"]] = p
            
    # Add new current prefs
    all_prefs_dict.update(current_prefs_dict)
    
    # Rebuild all_preferences by gathering every preference ID assigned to any hotel
    final_all_prefs = []
    seen_prefs = set()
    for idx, opt in enumerate(combined_options, start=1):
        opt["rank"] = idx
        for p_id in opt.get("preferences", []):
            if p_id not in seen_prefs:
                seen_prefs.add(p_id)
                # Fallback to id as label if we somehow lost the label
                final_all_prefs.append(all_prefs_dict.get(p_id, {"id": p_id, "label": p_id}))

    compound_min_price = existing_pending.get("compound_min_price")
    if parsed_min_price is not None:
        if compound_min_price is None:
            compound_min_price = parsed_min_price
        else:
            compound_min_price = min(compound_min_price, parsed_min_price)
            
    compound_max_price = existing_pending.get("compound_max_price")
    if parsed_max_price is not None:
        if compound_max_price is None:
            compound_max_price = parsed_max_price
        else:
            compound_max_price = max(compound_max_price, parsed_max_price)

    pending_payload = {
        "mode": "new_trip",
        "destination": target_destination,
        "destination_id": destination_id,
        "duration": duration,
        "start_date": start_date,
        "end_date": end_date,
        "people": people,
        "preferences_text": preferences,
        "hotel_query": hotel_query,
        "intake_context": intake_context,
        "created_at": datetime.now().isoformat(),
        "options": combined_options,
        "all_preferences": final_all_prefs,
        "active_preferences": list(current_prefs_dict.values()),
        "compound_min_price": compound_min_price,
        "compound_max_price": compound_max_price,
    }
    reply = t(
        "Mình đã tìm được danh sách khách sạn phù hợp. Bạn xem và chọn trực tiếp khách sạn mong muốn trong tab Khách sạn để tạo lịch trình nhé!",
        language,
    )
    return Command(
        update={
            "pending_hotel_selection": pending_payload,
            "messages": [ToolMessage(reply, tool_call_id=runtime.tool_call_id)],
        }
    )
