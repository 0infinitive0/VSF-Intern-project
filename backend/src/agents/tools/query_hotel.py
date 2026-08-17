import json
import logging
from typing import Any

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from src.agents.graph.state import TravelGraphState
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

    hotel_options = runtime.state.get("hotel_options")
    
    if not hotel_options or not hotel_options.get("options"):
        reply = t(
            "SYSTEM ERROR: Không có danh sách khách sạn nào hiện đang được chọn. Hãy dùng công cụ recommend_hotels trước.",
            language,
        ) if language == "vi" else "SYSTEM ERROR: No hotel list is currently active. Use recommend_hotels first."
        return Command(update={"messages": [ToolMessage(reply, tool_call_id=runtime.tool_call_id)]})

    options = hotel_options["options"]
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
    cleaned_details = {
        "id": matched_hotel.get("id"),
        "name": matched_hotel.get("name"),
        "rank": matched_hotel.get("rank"),
        "star_rating": matched_hotel.get("star_rating"),
        "description": str(matched_hotel.get("description", ""))[:500] + "...", # Truncate description
        "amenities": matched_hotel.get("amenities", []),
        "covered_meals": matched_hotel.get("covered_meals", []),
        "lowest_price": matched_hotel.get("lowest_price"),
        "currency": matched_hotel.get("currency", "VND"),
        "matched_room_names": matched_hotel.get("matched_room_names", []),
    }
    
    hotel_json = json.dumps(cleaned_details, ensure_ascii=False, indent=2)
    reply = f"Here is the detailed information for the requested hotel:\n{hotel_json}"
    
    return Command(update={"messages": [ToolMessage(reply, tool_call_id=runtime.tool_call_id)]})
