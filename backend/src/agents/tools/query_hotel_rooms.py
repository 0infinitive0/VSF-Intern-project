import json
import logging
from datetime import date
from typing import Any, Optional

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from src.agents.graph.state import TravelGraphState
from src.agents.tools.shown_hotels import labelled_amenities, shown_hotel_options, without_unknowns
from src.i18n import t
from src.services.place_details import get_hotel_detail

logger = logging.getLogger(__name__)


def _stay_dates(state: Any) -> tuple[date | None, date | None]:
    """The check-in/check-out the current hotel list was searched for.

    `previous_hotel_search_context` (`hotel_node.py`) is written on every
    successful search and, like `previous_hotel_options`, survives
    `load_context`'s per-turn reset -- so it is still there on a question
    turn that runs no worker. `trip_data` is the fallback for a turn after
    the itinerary exists, where the search context is stale but the
    itinerary's own stay dates are current.
    """
    get = getattr(state, "get", None)
    if get is None:
        return None, None

    context = get("previous_hotel_search_context") or {}
    start = context.get("start_date")
    end = context.get("end_date")
    if not (start and end):
        trip_data = get("trip_data") or {}
        itineraries = trip_data.get("itineraries") or []
        itinerary = itineraries[0] if itineraries and isinstance(itineraries[0], dict) else {}
        start = start or itinerary.get("start_date")
        end = end or itinerary.get("end_date")

    try:
        return (date.fromisoformat(str(start)), date.fromisoformat(str(end))) if start and end else (None, None)
    except ValueError:
        return None, None


@tool
def query_hotel_rooms(
    hotel_identifier: str,
    room_name: Optional[str] = None,
    *,
    runtime: ToolRuntime[None, TravelGraphState],
) -> Command:
    """
    CRITICAL: Use this tool ONLY when the user asks a specific question about room types, beds, capacity,
    views, PRICE, or AVAILABILITY for a hotel in the generated hotel list (e.g., "Does hotel 2 have a king
    bed?", "What is the view for rooms in hotel X?", "How much is the suite?", "Is any room still available?").
    Pass the rank number (e.g. "2") or the hotel name/id as `hotel_identifier`.
    You can optionally provide a `room_name` to filter rooms containing a specific keyword.
    """
    language = str(runtime.state.get("language") or "vi")
    vi = not language.startswith("en")

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
        # `get_hotel_detail` is the SAME function `GET /hotels/{id}` calls to
        # build the room cards the user is looking at (`api/routes.py`) --
        # not a parallel query. Reusing it, rather than a second raw select
        # of the `rooms` table, is what makes it structurally impossible for
        # this tool's price/availability answer to disagree with the screen.
        #
        # Previously this ran `client.table("rooms").select(...)` with no
        # price or availability column at all, so the tool said "dữ liệu chi
        # tiết giá theo từng loại phòng không được trả về" while the UI
        # showed 2.097.309 ₫ for the same room, and it listed sold-out rooms
        # as options with no indication they couldn't be booked.
        check_in, check_out = _stay_dates(runtime.state)
        detail = get_hotel_detail(str(hotel_id), check_in, check_out)
    except Exception as e:
        logger.exception("Failed to fetch rooms from Supabase.")
        reply = f"SYSTEM ERROR: Lỗi khi lấy dữ liệu phòng ({str(e)})."
        return Command(update={"messages": [ToolMessage(reply, tool_call_id=runtime.tool_call_id)]})

    rooms = (detail or {}).get("rooms") or []
    if room_name:
        needle = room_name.strip().lower()
        rooms = [room for room in rooms if needle in str(room.get("name") or "").lower()]

    if not rooms:
        reply = t(
            "Không tìm thấy thông tin phòng cho khách sạn này hoặc với từ khóa này. Vui lòng nói với người dùng rằng không có thông tin.",
            language,
        ) if language == "vi" else "No room data found for this hotel or keyword. Please inform the user that the information is unavailable."
        return Command(update={"messages": [ToolMessage(reply, tool_call_id=runtime.tool_call_id)]})

    # Raw table rows went to the model verbatim, so it answered a parent
    # asking about a family room with "không có loại phòng nào có trường
    # max_guests = 4" and "nhiều phòng có max_guests = null" -- column
    # names and a JSON literal, to someone who just wants to know if the
    # four of them fit. Renamed to plain keys, canonical facility ids
    # resolved to labels, and unknown values dropped rather than sent as
    # null so there is no `null` in the prompt to read back out.
    # Keys are written in the session's own language. The model quotes the
    # key when a value surprises it -- it wrote `(mục này ghi "sleeps 2")`
    # mid-Vietnamese-sentence even after the column names were gone -- so
    # the only reliable way to keep developer vocabulary out of the reply
    # is for there to be none in the payload at all.
    key = {
        "room": "phòng" if vi else "room",
        "sleeps": "số khách" if vi else "sleeps",
        "size": "diện tích m2" if vi else "size sqm",
        "bed": "giường" if vi else "bed",
        "view": "hướng nhìn" if vi else "view",
        "facilities": "tiện nghi" if vi else "facilities",
        "price": "giá mỗi đêm" if vi else "price per night",
        "currency": "đơn vị tiền" if vi else "currency",
        "availability": "tình trạng phòng" if vi else "availability",
    }
    # Same wording the room cards themselves use (i18n/locales/*.json's
    # roomPriceOnRequest/roomSoldOut/roomAvailableCount) -- a customer
    # reading both should never see the assistant and the screen disagree
    # in how they SAY the same fact, only possibly in what fact is known.
    price_on_request = "Giá theo yêu cầu" if vi else "Price on request"
    sold_out_text = "Hết phòng" if vi else "Sold out"

    def _availability_text(count: Any) -> str | None:
        if not isinstance(count, int):
            return None
        if count <= 0:
            return sold_out_text
        return f"Còn {count} phòng" if vi else (f"{count} room available" if count == 1 else f"{count} rooms available")

    rooms_data = []
    for room in rooms:
        if not isinstance(room, dict):
            continue
        price = room.get("price") or {}
        amount = price.get("amount")
        rooms_data.append(
            without_unknowns(
                {
                    key["room"]: room.get("name"),
                    key["sleeps"]: room.get("max_guests"),
                    key["size"]: room.get("room_size_sqm"),
                    key["bed"]: room.get("bed_description"),
                    key["view"]: room.get("view"),
                    key["facilities"]: labelled_amenities(room.get("room_facilities"), language=language),
                    key["price"]: amount if amount else price_on_request,
                    key["currency"]: (price.get("currency") or "VND") if amount else None,
                    key["availability"]: _availability_text(room.get("available_room_count")),
                }
            )
        )

    rooms_json = json.dumps(rooms_data, ensure_ascii=False, indent=2)
    reply = (
        "Here are the room types for this hotel, with current price and "
        "availability for the dates already searched. A room with no capacity "
        "shown simply has none recorded — tell the user it isn't listed, in "
        "ordinary words, and never name a field. Never suggest a room whose "
        f"availability says {sold_out_text!r} without telling the user it is "
        "sold out:\n"
        f"{rooms_json}"
    )

    return Command(update={"messages": [ToolMessage(reply, tool_call_id=runtime.tool_call_id)]})
