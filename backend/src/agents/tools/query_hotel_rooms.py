import json
import logging
from typing import Optional

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from src.agents.graph.state import TravelGraphState
from src.agents.tools.shown_hotels import labelled_amenities, shown_hotel_options
from src.i18n import t
from src.services.supabase_search import get_supabase_client

logger = logging.getLogger(__name__)


@tool
def query_hotel_rooms(
    hotel_identifier: str,
    room_name: Optional[str] = None,
    *,
    runtime: ToolRuntime[None, TravelGraphState],
) -> Command:
    """
    CRITICAL: Use this tool ONLY when the user asks a specific question about room types, beds, capacity,
    or views for a hotel in the generated hotel list (e.g., "Does hotel 2 have a king bed?", "What is the view for rooms in hotel X?").
    Pass the rank number (e.g. "2") or the hotel name/id as `hotel_identifier`.
    You can optionally provide a `room_name` to filter rooms containing a specific keyword.
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
            if last_calls[0]["name"] == "query_hotel_rooms" and current_calls[0]["name"] == "query_hotel_rooms":
                if str(last_calls[0]["args"].get("hotel_identifier", "")) == str(hotel_identifier) and str(last_calls[0]["args"].get("room_name", "")) == str(room_name):
                    logger.warning("[query_hotel_rooms] ANTI-LOOP TRIGGERED!")
                    reply = t(
                        "Lỗi: Bạn đã gọi công cụ này với cùng tham số nhưng không tìm thấy thông tin. ĐỪNG gọi lại. Hãy nói với người dùng bạn không có thông tin này và xử lý phần còn lại của yêu cầu.",
                        language
                    ) if language == "vi" else "Error: You just called this tool with the same args but the info wasn't there. DO NOT CALL IT AGAIN. Tell the user you don't have the info."
                    return Command(update={"messages": [ToolMessage(reply, tool_call_id=runtime.tool_call_id)]})

    options = shown_hotel_options(runtime.state)

    if not options:
        # See query_hotel.py for why this is not a SYSTEM ERROR and no longer
        # points the model at the removed `recommend_hotels` tool.
        reply = t(
            "Chưa có danh sách khách sạn nào. Hãy nói với người dùng rằng bạn cần tìm khách sạn trước.",
            language,
        ) if language == "vi" else "No hotel list exists yet. Tell the user a hotel search is needed first."
        return Command(update={"messages": [ToolMessage(reply, tool_call_id=runtime.tool_call_id)]})
    matched_hotel = None
    
    hotel_identifier_str = str(hotel_identifier).strip().lower()
    
    # 1. Try to match by rank/index
    try:
        rank_idx = int(hotel_identifier_str)
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
            if hotel_identifier_str in name:
                matched_hotel = opt
                break
                
    if not matched_hotel:
        reply = t(
            f"Lỗi: Không tìm thấy khách sạn nào khớp với '{hotel_identifier}' trong danh sách hiện tại. Vui lòng kiểm tra lại.",
            language,
        ) if language == "vi" else f"Error: Could not find any hotel matching '{hotel_identifier}' in the current list."
        return Command(update={"messages": [ToolMessage(reply, tool_call_id=runtime.tool_call_id)]})
    
    hotel_id = matched_hotel.get("id")
    if not hotel_id:
        reply = "SYSTEM ERROR: No valid ID found for this hotel."
        return Command(update={"messages": [ToolMessage(reply, tool_call_id=runtime.tool_call_id)]})

    try:
        client = get_supabase_client()
        query = client.table("rooms").select("name, max_guests, room_size_sqm, bed_description, view, room_facilities").eq("hotel_id", hotel_id)
        
        if room_name:
            query = query.ilike("name", f"%{room_name}%")
            
        res = query.execute()
        rooms_data = res.data
        
        if not rooms_data:
            reply = t(
                "Không tìm thấy thông tin phòng cho khách sạn này hoặc với từ khóa này. Vui lòng nói với người dùng rằng không có thông tin.",
                language,
            ) if language == "vi" else "No room data found for this hotel or keyword. Please inform the user that the information is unavailable."
            return Command(update={"messages": [ToolMessage(reply, tool_call_id=runtime.tool_call_id)]})
            
        # `room_facilities` are canonical ids straight out of the table; the
        # model repeats whatever it is given, so resolve them to the same
        # labels the room cards show rather than letting "outdoor_bathtub"
        # reach the user.
        rooms_data = [
            {**room, "room_facilities": labelled_amenities(room.get("room_facilities"), language=language)}
            if isinstance(room, dict)
            else room
            for room in rooms_data
        ]

        rooms_json = json.dumps(rooms_data, ensure_ascii=False, indent=2)
        reply = f"Here is the detailed room information for the requested hotel:\n{rooms_json}"
        
        return Command(update={"messages": [ToolMessage(reply, tool_call_id=runtime.tool_call_id)]})
        
    except Exception as e:
        logger.exception("Failed to fetch rooms from Supabase.")
        reply = f"SYSTEM ERROR: Lỗi khi lấy dữ liệu phòng ({str(e)})."
        return Command(update={"messages": [ToolMessage(reply, tool_call_id=runtime.tool_call_id)]})
