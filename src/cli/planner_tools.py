"""LangChain Agent tool definitions and Supervisor Agent factory for Terminal Chat."""

from __future__ import annotations

import json
import logging
import os

from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent

from src.cli.trip_builder_svc import (
    CURRENT_TRIP_PLAN_FILE,
    _apply_local_trip_change,
    _build_trip_data,
    _current_trip_parameters,
    _get_destination_id,
    _parse_trip_change,
    _save_trip_data,
    format_trip_response_from_json,
    parse_duration_to_days,
)
from src.services.itinerary_reuse import ItineraryReuseQuery
from src.services.itinerary_store import ItineraryStore, ItineraryStoreError
from src.services.llm import get_llm

logger = logging.getLogger(__name__)

SUPERVISOR_PROMPT = """You are the Trip Planning Supervisor.
You are chatting with a user in Vietnamese. Your goal is to manage trip planning requests.

1. INITIAL TRIP PLANNING:
   Gather 3 pieces of info explicitly stated by the user: Destination, Duration, Number of People.
   - CRITICAL: DO NOT guess, fabricate, or supply default values for missing parameters! If the user has NOT explicitly provided duration or number of people, DO NOT call `generate_full_itinerary`.
   - Reply directly to the user in friendly, polite Vietnamese asking ONLY for the missing info.
   - When calling `generate_full_itinerary`, pass the EXACT duration string provided by the user (e.g., duration="1 tuần" if the user said "1 tuần").
   - If the user mentions interests or preferred themes, pass them in the optional `preferences` argument. Do not add another required question when preferences are absent.
   - CRITICAL: DO NOT start your responses with "Xin lỗi" or "Tôi xin lỗi". Be direct, polite, and welcoming (e.g., "Để lập kế hoạch cho chuyến đi Nha Trang, bạn cho mình biết...").

2. MODIFYING AN EXISTING TRIP:
   - If a trip plan has ALREADY been generated and saved, and the user asks to edit, change, swap, or update anything (e.g., change hotel, add an attraction, edit timing), call `modify_trip_plan(modification_request)`.

3. FINALIZING A TRIP:
   - Call `finalize_trip_plan` only after an explicit confirmation such as "finalize", "confirm trip", or "chốt lịch trình".

IMPORTANT RULES:
- NEVER guess missing duration or people values.
- Never output raw JSON in your text responses.
- DO NOT start any message with "Xin lỗi" or "Tôi xin lỗi".
- Return the EXACT text response from the tool to the user. Do not add conversational filler.
- All your responses to the user MUST be entirely in Vietnamese."""


@tool
def generate_full_itinerary(
    destination: str = "",
    duration: str = "",
    people: str = "",
    preferences: str = "",
) -> str:
    """
    CRITICAL: Use this tool to generate the initial trip plan ONLY once you have gathered destination, duration, and number of people.
    Pass extracted destination, duration, and people from chat history. Preserve duration units (e.g. pass "1 tuần" if user said "1 tuần").
    """
    missing = []
    if not destination or destination.lower() in ["unknown", "chưa rõ", "none"]: missing.append("destination")
    if not duration or duration.lower() in ["unknown", "chưa rõ", "none"]: missing.append("duration")
    if not people or people.lower() in ["unknown", "chưa rõ", "none"]: missing.append("people")
    
    if missing:
        return f"SYSTEM ERROR: You cannot plan the itinerary yet. You are missing: {', '.join(missing)}. DO NOT guess. Reply to the user in friendly Vietnamese asking for this specific information without saying 'Xin lỗi'."

    dest_clean = destination.lower()
    for phrase in ["đi 1 mình", "một mình", "1 mình", "đi 1 nguoi", "1 người", "với vợ", "đi với vợ", "ễới màn", "ễới"]:
        dest_clean = dest_clean.replace(phrase, "")
    dest_clean = dest_clean.strip(" .-,_")
    
    if not dest_clean or len(dest_clean) < 2:
        return "SYSTEM ERROR: Điểm đến không hợp lệ. Hãy cung cấp tên thành phố hoặc tỉnh cụ thể."
    destination = dest_clean.title()
    logger.info(
        "Executing balanced itinerary pipeline for destination=%r, duration=%r, people=%r",
        destination,
        duration,
        people,
    )
    try:
        trip_data = _build_trip_data(destination, duration, people, preferences)
        _save_trip_data(trip_data)
    except Exception as exc:
        logger.exception("Balanced itinerary generation failed")
        return f"SYSTEM ERROR: {exc}"

    return format_trip_response_from_json(trip_data)


@tool
def modify_trip_plan(modification_request: str) -> str:
    """
    Use this tool when the user wants to change, modify, or update an existing trip plan (e.g. change hotel, edit schedule, swap attractions).
    Pass the user's specific modification request string.
    """
    if not os.path.exists(CURRENT_TRIP_PLAN_FILE):
        return "SYSTEM ERROR: Chưa có kế hoạch chuyến đi nào được tạo. Vui lòng tạo chuyến đi mới trước khi chỉnh sửa."
        
    try:
        with open(CURRENT_TRIP_PLAN_FILE, "r", encoding="utf-8") as f:
            current_data = json.load(f)
    except Exception as e:
        return f"SYSTEM ERROR: Không thể đọc file kế hoạch hiện tại: {e}"

    saved_itinerary = (current_data.get("itineraries") or [{}])[0]
    if isinstance(saved_itinerary, dict) and str(saved_itinerary.get("status") or "").casefold() == "finalized":
        return "Kế hoạch đã xác nhận không thể chỉnh sửa. Hãy tạo một kế hoạch mới nếu cần thay đổi."

    logger.info(f"Modifying trip plan based on request: {modification_request}")
    try:
        change = _parse_trip_change(modification_request)
        if change.action == "change_hotel":
            destination, duration, people, preferences = _current_trip_parameters(current_data)
            if not destination:
                raise ValueError("Kế hoạch hiện tại không lưu điểm đến để đổi khách sạn.")
            updated_data = _build_trip_data(
                destination,
                duration,
                people,
                preferences,
                hotel_query=change.query or modification_request,
            )
            updated_data.setdefault("adjustments", []).append(
                "Đã đổi khách sạn và lập lại toàn bộ các cụm địa điểm theo vị trí mới."
            )
        else:
            updated_data = current_data
            adjustments = _apply_local_trip_change(updated_data, change, modification_request)
            updated_data.setdefault("adjustments", []).extend(adjustments)
        updated_itinerary = (updated_data.get("itineraries") or [{}])[0]
        if isinstance(updated_itinerary, dict):
            updated_itinerary["status"] = "Draft"
            updated_itinerary.pop("summary", None)
        _save_trip_data(updated_data)
        logger.info("Successfully applied structured trip change: %s", change.action)
    except Exception as exc:
        logger.exception("Failed to apply structured trip modification")
        return f"SYSTEM ERROR: {exc}"

    return format_trip_response_from_json(updated_data)


def _is_finalization_request(message: str) -> bool:
    normalized = message.casefold().strip()
    return any(
        phrase in normalized
        for phrase in ("finalize", "confirm trip", "chốt lịch trình", "chot lich trinh", "xác nhận lịch")
    )


@tool
def finalize_trip_plan() -> str:
    """Finalize the saved draft only after the user explicitly confirms it."""
    if not os.path.exists(CURRENT_TRIP_PLAN_FILE):
        return "SYSTEM ERROR: Chưa có kế hoạch để xác nhận. Hãy tạo kế hoạch trước."
    try:
        with open(CURRENT_TRIP_PLAN_FILE, "r", encoding="utf-8") as file_handle:
            trip_data = json.load(file_handle)
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
        )
        store = ItineraryStore.from_default()
        store.persist_itinerary_bundle(trip_data)
        result = store.finalize_trip_data(trip_data, reuse_query)
        itinerary["status"] = "Finalized"
        itinerary["summary"] = result.get("summary")
        _save_trip_data(trip_data)
        if not result.get("embedding_saved", result.get("has_embedding", False)):
            return "Đã xác nhận lịch trình. Phần tìm kiếm tái sử dụng sẽ tự thử lại sau."
        return "Đã xác nhận lịch trình và lưu làm mẫu có thể tái sử dụng."
    except (ItineraryStoreError, ValueError) as exc:
        logger.exception("Trip finalization failed")
        return f"SYSTEM ERROR: {exc}"
    except Exception as exc:
        logger.exception("Unexpected trip finalization failure")
        return f"SYSTEM ERROR: {exc}"


def create_planner_agent(temperature: float = 0.3):
    llm = get_llm(temperature=temperature)
    memory = MemorySaver()
    return create_react_agent(
        llm,
        [generate_full_itinerary, modify_trip_plan, finalize_trip_plan],
        checkpointer=memory,
        prompt=SUPERVISOR_PROMPT,
    )
