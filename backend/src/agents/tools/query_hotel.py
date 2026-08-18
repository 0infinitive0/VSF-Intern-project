import json
import logging
from typing import Any

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from src.agents.graph.state import TravelGraphState
from src.agents.tools.shown_hotels import labelled_amenities, shown_hotel_options, without_unknowns
from src.i18n import t

logger = logging.getLogger(__name__)


@tool
def query_hotel(
    hotel_identifier: str,
    *,
    runtime: ToolRuntime[None, TravelGraphState],
) -> Command:
    """
    CRITICAL: Use this tool ONLY when the user asks a specific question about a hotel in the generated
    hotel list (e.g., "Does hotel 2 have a pool?", "What is the cancellation policy for hotel X?").
    Pass the rank number (e.g. "2") or the hotel name/id as `hotel_identifier`.
    This tool will fetch the detailed information (amenities, description, price, policy) for that specific hotel.
    """
    language = str(runtime.state.get("language") or "vi")
    
    # Anti-loop mechanism
    messages = runtime.state.get("messages", [])
    
    # In LangGraph, when a tool is executing, the last message in state is the AIMessage containing the tool_calls.
    # If the AI is looping, the sequence is: AIMessage(tool_calls) -> ToolMessage -> AIMessage(tool_calls)[CURRENT]
    # So if messages[-2] is a ToolMessage and messages[-3] is an AIMessage, it's a consecutive tool call without user input.
    if len(messages) >= 3 and getattr(messages[-2], "type", "") == "tool" and getattr(messages[-3], "type", "") == "ai":
        last_ai_msg = messages[-3]
        curr_ai_msg = messages[-1]
        
        if hasattr(last_ai_msg, "tool_calls") and last_ai_msg.tool_calls and hasattr(curr_ai_msg, "tool_calls") and curr_ai_msg.tool_calls:
            last_calls = last_ai_msg.tool_calls
            current_calls = curr_ai_msg.tool_calls
            if last_calls[0]["name"] == "query_hotel" and current_calls[0]["name"] == "query_hotel":
                if str(last_calls[0]["args"].get("hotel_identifier", "")) == str(hotel_identifier):
                    logger.warning("[query_hotel] ANTI-LOOP TRIGGERED!")
                    reply = t(
                        "Lỗi: Bạn đã gọi công cụ này với cùng tham số nhưng không tìm thấy thông tin. ĐỪNG gọi lại. Hãy nói với người dùng bạn không có thông tin này và xử lý phần còn lại của yêu cầu.",
                        language
                    ) if language == "vi" else "Error: You just called this tool with the same args but the info wasn't there. DO NOT CALL IT AGAIN. Tell the user you don't have the info."
                    return Command(update={"messages": [ToolMessage(reply, tool_call_id=runtime.tool_call_id)]})

    options = shown_hotel_options(runtime.state)

    if not options:
        # Not a SYSTEM ERROR: `respond`'s derive_stage turns that prefix into
        # a failed turn (`stage == "error"`), and this is an ordinary "you
        # haven't searched yet" state. The old text also told the model to
        # call `recommend_hotels`, a tool this node stopped having when
        # recommending became a worker action -- so the one instruction it
        # gave was impossible to follow.
        reply = t(
            "Chưa có danh sách khách sạn nào. Hãy nói với người dùng rằng bạn cần tìm khách sạn trước.",
            language,
        ) if language == "vi" else "No hotel list exists yet. Tell the user a hotel search is needed first."
        return Command(update={"messages": [ToolMessage(reply, tool_call_id=runtime.tool_call_id)]})
    matched_hotel = None
    
    hotel_identifier = str(hotel_identifier).strip().lower()
    
    # 1. Try to match by rank/index
    try:
        rank_idx = int(hotel_identifier)
        for opt in options:
            if opt.get("rank") == rank_idx:
                matched_hotel = opt
                break
    except ValueError:
        pass
        
    # 2. Try to match by name
    if not matched_hotel:
        for opt in options:
            name = str(opt.get("name", "")).strip().lower()
            if hotel_identifier in name:
                matched_hotel = opt
                break
                
    if not matched_hotel:
        reply = t(
            f"Lỗi: Không tìm thấy khách sạn nào khớp với '{hotel_identifier}' trong danh sách hiện tại. Vui lòng kiểm tra lại.",
            language,
        ) if language == "vi" else f"Error: Could not find any hotel matching '{hotel_identifier}' in the current list."
        return Command(update={"messages": [ToolMessage(reply, tool_call_id=runtime.tool_call_id)]})
        
    # Format the hotel details cleanly to save tokens, discarding giant unused fields
    # Plain-language keys, and anything unknown is OMITTED rather than sent as
    # null. The model repeats the shape it is given: handed `lowest_price` and
    # `max_guests = null` it wrote "không có phòng nào có trường max_guests =
    # 4" and "lowest_price là 2.097.309 VND" straight to a customer, who has
    # no idea what either means. A key that isn't there can't be quoted, and a
    # value that isn't null can't be read out as "null".
    description = str(matched_hotel.get("description") or "").strip()
    # Keys in the session's own language — see query_hotel_rooms.py for why a
    # quoted key has to already read as ordinary prose.
    vi = not language.startswith("en")
    cleaned_details = without_unknowns(
        {
            ("khách sạn số" if vi else "hotel number"): matched_hotel.get("rank"),
            ("tên" if vi else "name"): matched_hotel.get("name"),
            ("hạng sao" if vi else "stars"): matched_hotel.get("star_rating"),
            ("mô tả" if vi else "description"): (
                (description[:500] + "…") if len(description) > 500 else description
            ),
            # Labels, not canonical ids: whatever this dict holds is what the
            # model repeats to the user, and it will happily read
            # "bể bơi (swimming_pool)" out loud if handed the id.
            ("tiện nghi" if vi else "amenities"): labelled_amenities(
                matched_hotel.get("amenities", []), language=language
            ),
            ("bữa ăn bao gồm" if vi else "meals included"): matched_hotel.get("covered_meals", []),
            ("giá mỗi đêm từ" if vi else "price per night from"): matched_hotel.get("lowest_price"),
            ("đơn vị tiền" if vi else "currency"): matched_hotel.get("currency") or "VND",
            ("phòng khớp tìm kiếm" if vi else "rooms matching the search"): matched_hotel.get(
                "matched_room_names", []
            ),
        }
    )

    hotel_json = json.dumps(cleaned_details, ensure_ascii=False, indent=2)
    reply = (
        "Here is the detailed information for the requested hotel. Anything not "
        "listed below is simply unknown — say so in plain words rather than "
        "naming a field:\n"
        f"{hotel_json}"
    )
    
    return Command(update={"messages": [ToolMessage(reply, tool_call_id=runtime.tool_call_id)]})
