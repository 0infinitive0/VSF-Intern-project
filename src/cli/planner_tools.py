"""LangChain Agent tool definitions and Supervisor Agent factory for Terminal Chat."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime

from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent

from src.cli.trip_builder_svc import (
    CURRENT_TRIP_PLAN_FILE,
    _apply_local_trip_change,
    apply_trip_edit_plan,
    _build_trip_data,
    _clear_pending_hotel_selection,
    _current_trip_parameters,
    _get_destination_id,
    _load_pending_hotel_selection,
    _parse_trip_change,
    _reapply_planning_constraints,
    _save_pending_hotel_selection,
    _save_trip_data,
    format_hotel_options,
    format_trip_response_from_json,
    parse_duration_to_days,
)
from src.services.hotel_selection import (
    _parse_free_text_price,
    fetch_hotel_by_id,
    lookup_sea_view_hotel_ids,
    rank_hotel_candidates,
    resolve_hotel_selection,
    select_hotel_candidates,
)
from src.services.itinerary_reuse import ItineraryReuseQuery
from src.services.itinerary_store import ItineraryStore, ItineraryStoreError
from src.services.llm import get_llm
from src.services.supabase_search import validate_radius_filter
from src.services.trip_edit_planner import TripEditPlan, TripEditPlanError, plan_trip_edit
from src.services.trip_scheduler import PlaceCandidate

logger = logging.getLogger(__name__)

SUPERVISOR_PROMPT = """You are the Trip Planning Supervisor.
You are chatting with a user in Vietnamese. Your goal is to manage trip planning requests.

1. INITIAL TRIP PLANNING:
   Gather 3 pieces of info explicitly stated by the user: Destination, Duration, Number of People.
   - CRITICAL: DO NOT guess, fabricate, or supply default values for missing parameters! If the user has NOT explicitly provided duration or number of people, DO NOT call `recommend_hotels`.
   - Reply directly to the user in friendly, polite Vietnamese asking ONLY for the missing info.
   - Once all 3 are known, call `recommend_hotels` to show a ranked list of real hotels. NEVER call `generate_full_itinerary` yourself — the itinerary is only ever built after the user has picked a hotel from that list.
   - When calling `recommend_hotels`, pass the EXACT duration string provided by the user (e.g., duration="1 tuần" if the user said "1 tuần").
   - If the user mentions interests or preferred themes, pass them in the optional `preferences` argument. If they mention hotel-specific wants (star rating, view, amenities...), pass them in `hotel_preferences`. If they state a budget/price, convert it to plain VND numbers and pass it in `target_price`/`min_price`/`max_price` — do not just describe it in `hotel_preferences`, since these are what actually filter results by price. A single ceiling (e.g. "khoảng 1 triệu", "dưới 500k") goes in `target_price` (e.g. "1000000", "500000"); an actual range (e.g. "1-2 triệu", "từ 800k đến 2 triệu rưỡi") goes in `min_price`/`max_price` instead (e.g. "1000000"/"2000000"). Do not add another required question when these are absent.
   - CRITICAL: DO NOT start your responses with "Xin lỗi" or "Tôi xin lỗi". Be direct, polite, and welcoming (e.g., "Để lập kế hoạch cho chuyến đi Nha Trang, bạn cho mình biết...").

2. AFTER A HOTEL LIST HAS BEEN SHOWN:
   - The user's very next reply is their hotel choice (a number or a hotel name) — call `select_hotel(selection)` with that reply text verbatim. Do not try to interpret or validate the choice yourself, and do not call any other tool for that turn.

3. MODIFYING AN EXISTING TRIP:
   - If a trip plan has ALREADY been generated and saved, and the user asks to edit, change, swap, or update anything (e.g., change hotel, add an attraction, edit timing), call `modify_trip_plan(modification_request)`.
   - A hotel-change request also produces a numbered hotel list; the user's next reply after that must go through `select_hotel` too (see rule 2).

4. FINALIZING A TRIP:
   - Call `finalize_trip_plan` only after an explicit confirmation such as "finalize", "confirm trip", or "chốt lịch trình".

IMPORTANT RULES:
- NEVER guess missing duration or people values.
- Never output raw JSON in your text responses.
- DO NOT start any message with "Xin lỗi" or "Tôi xin lỗi".
- Return the EXACT text response from the tool to the user. Do not add conversational filler.
- All your responses to the user MUST be entirely in Vietnamese."""


def _validate_trip_basics(destination: str, duration: str, people: str) -> tuple[str | None, str | None]:
    """Validate the 3 required trip facts and clean the destination string.

    Returns (cleaned_destination, None) on success, or (None, error_message) on failure —
    error_message is a ready-to-return "SYSTEM ERROR: ..." string.
    """
    missing = []
    if not destination or destination.lower() in ["unknown", "chưa rõ", "none"]:
        missing.append("destination")
    if not duration or duration.lower() in ["unknown", "chưa rõ", "none"]:
        missing.append("duration")
    if not people or people.lower() in ["unknown", "chưa rõ", "none"]:
        missing.append("people")
    if missing:
        return None, (
            f"SYSTEM ERROR: You cannot plan the itinerary yet. You are missing: {', '.join(missing)}. "
            "DO NOT guess. Reply to the user in friendly Vietnamese asking for this specific information "
            "without saying 'Xin lỗi'."
        )

    dest_clean = destination.lower()
    for phrase in ["đi 1 mình", "một mình", "1 mình", "đi 1 nguoi", "1 người", "với vợ", "đi với vợ", "ễới màn", "ễới"]:
        dest_clean = dest_clean.replace(phrase, "")
    dest_clean = dest_clean.strip(" .-,_")

    if not dest_clean or len(dest_clean) < 2:
        return None, "SYSTEM ERROR: Điểm đến không hợp lệ. Hãy cung cấp tên thành phố hoặc tỉnh cụ thể."

    return dest_clean.title(), None


def _generate_and_save_itinerary(
    destination: str,
    duration: str,
    people: str,
    preferences: str = "",
    *,
    hotel_query: str | None = None,
    preselected_hotel: dict | None = None,
    planning_constraints: dict | None = None,
) -> str:
    """Shared build/save/format sequence used by generate_full_itinerary and select_hotel."""
    try:
        trip_data = _build_trip_data(
            destination,
            duration,
            people,
            preferences,
            hotel_query=hotel_query,
            preselected_hotel=preselected_hotel,
            planning_constraints=planning_constraints,
        )
        _save_trip_data(trip_data)
    except Exception as exc:
        logger.exception("Itinerary generation failed")
        return f"SYSTEM ERROR: {exc}"

    return format_trip_response_from_json(trip_data)


@tool
def generate_full_itinerary(
    destination: str = "",
    duration: str = "",
    people: str = "",
    preferences: str = "",
    hotel_id: str = "",
) -> str:
    """
    Do NOT call this tool directly during normal user interactions.
    `recommend_hotels` must be called first so the user can choose a hotel; `select_hotel`
    then handles calling this internal generation sequence automatically. Only use this
    tool if `hotel_id` is already specified and validated.
    """
    destination, error = _validate_trip_basics(destination, duration, people)
    if error:
        return error

    preselected_hotel = None
    if hotel_id:
        destination_id = _get_destination_id(destination)
        resolved = fetch_hotel_by_id(hotel_id, str(destination_id) if destination_id else None)
        if not resolved:
            return "SYSTEM ERROR: Không tìm thấy khách sạn với id đã cho tại điểm đến này."
        preselected_hotel, _candidate = resolved

    logger.info(
        "Executing balanced itinerary pipeline for destination=%r, duration=%r, people=%r, hotel_id=%r",
        destination,
        duration,
        people,
        hotel_id,
    )
    return _generate_and_save_itinerary(destination, duration, people, preferences, preselected_hotel=preselected_hotel)


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
    root_latitude: str | float | None = None,
    root_longitude: str | float | None = None,
    max_radius_km: str | float | None = None,
) -> str:
    """
    CRITICAL: Use this tool ONCE destination, duration, and number of people are all known, to show
    a ranked list of real hotel options. This is the ONLY way to start planning a new trip — never
    call `generate_full_itinerary` yourself. If the user mentioned specific hotel wants (star rating,
    view, amenities...), pass them in `hotel_preferences`. `target_price`/`min_price`/`max_price`/
    `hotel_amenity_prefs` are usually pre-resolved by the guided budget/amenity intake.

    OPTIONAL RADIUS FILTERING:
    - If caller specifies an anchor coordinate and maximum radius (in km), pass `root_latitude`, `root_longitude`,
      and `max_radius_km` together.
    - All three parameters MUST be passed together if radius filtering is used.
    - DO NOT invent coordinates or guess a location. Only pass coordinates if explicitly supplied by caller.
    - DO NOT widen or remove the radius if no hotel is returned; let the system report zero results.
    After this returns, the user's next reply must be handled by `select_hotel`, not by calling this
    tool or generate_full_itinerary again.
    """
    destination, error = _validate_trip_basics(destination, duration, people)
    if error:
        return error

    destination_id = _get_destination_id(destination)
    if not destination_id:
        return f"SYSTEM ERROR: Không tìm thấy dữ liệu điểm đến cho {destination}."
    destination_id = str(destination_id)

    parsed_root_lat = float(root_latitude) if root_latitude is not None and str(root_latitude).strip() != "" else None
    parsed_root_lon = float(root_longitude) if root_longitude is not None and str(root_longitude).strip() != "" else None
    parsed_max_radius = float(max_radius_km) if max_radius_km is not None and str(max_radius_km).strip() != "" else None

    try:
        radius_obj = validate_radius_filter(parsed_root_lat, parsed_root_lon, parsed_max_radius)
    except ValueError as val_err:
        return f"SYSTEM ERROR: {val_err}"

    hotel_query = hotel_preferences.strip() or None
    parsed_target_price = float(target_price) if target_price.strip() else None
    parsed_min_price = float(min_price) if min_price.strip() else None
    parsed_max_price = float(max_price) if max_price.strip() else None
    if parsed_min_price is None and parsed_max_price is None and parsed_target_price is not None:
        parsed_max_price = parsed_target_price
    amenity_pref_set = frozenset(
        tag.strip() for tag in hotel_amenity_prefs.split(",") if tag.strip()
    )

    try:
        options = select_hotel_candidates(
            destination,
            destination_id,
            people,
            hotel_query=hotel_query,
            min_price=parsed_min_price,
            max_price=parsed_max_price,
            root_latitude=radius_obj.root_latitude if radius_obj else None,
            root_longitude=radius_obj.root_longitude if radius_obj else None,
            max_radius_km=radius_obj.max_radius_km if radius_obj else None,
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
        return f"SYSTEM ERROR: {exc}"

    if not options:
        return (
            f"SYSTEM ERROR: Không tìm thấy khách sạn có tọa độ hợp lệ tại {destination}; "
            "không thể gợi ý khách sạn."
        )

    pending_payload: dict[str, Any] = {
        "mode": "new_trip",
        "destination": destination,
        "destination_id": destination_id,
        "duration": duration,
        "people": people,
        "preferences_text": preferences,
        "hotel_query": hotel_query,
        "created_at": datetime.now().isoformat(),
        "options": [data for data, _candidate in options],
    }
    planning_constraints = {}
    if radius_obj and radius_obj.max_radius_km is not None:
        planning_constraints["semantic_search_radius_km"] = radius_obj.max_radius_km
    if parsed_target_price is not None:
        planning_constraints["target_price"] = parsed_target_price
    if parsed_min_price is not None:
        planning_constraints["min_price"] = parsed_min_price
    if parsed_max_price is not None:
        planning_constraints["max_price"] = parsed_max_price
    if amenity_pref_set:
        planning_constraints["amenity_prefs"] = list(amenity_pref_set)
    if hotel_query:
        planning_constraints["hotel_query"] = hotel_query

    if radius_obj:
        pending_payload["radius_filter"] = {
            "root_latitude": radius_obj.root_latitude,
            "root_longitude": radius_obj.root_longitude,
            "max_radius_km": radius_obj.max_radius_km,
        }
    pending_payload["planning_constraints"] = planning_constraints

    _save_pending_hotel_selection(pending_payload)
    return format_hotel_options(options)


@tool
def select_hotel(selection: str) -> str:
    """
    Use this tool whenever a numbered hotel list has just been shown and the user's reply is their
    choice (a number like "2" or a hotel name). Pass their reply text verbatim as `selection`.
    """
    pending = _load_pending_hotel_selection()
    if not pending:
        return "SYSTEM ERROR: Chưa có danh sách khách sạn nào để chọn. Hãy tạo gợi ý khách sạn trước."

    raw_options = pending.get("options") or []
    options = [
        (data, PlaceCandidate.from_mapping({**data, "category": "Hotel"}))
        for data in raw_options
        if isinstance(data, dict)
    ]
    resolved = resolve_hotel_selection(selection, options)
    if not resolved:
        return (
            "Mình chưa xác định được đúng khách sạn bạn muốn chọn, bạn trả lời rõ hơn giúp mình nhé "
            "(số thứ tự hoặc tên khách sạn).\n------\n" + format_hotel_options(options)
        )

    hotel_data, _candidate = resolved
    mode = pending.get("mode", "new_trip")
    destination = pending.get("destination", "")
    duration = pending.get("duration", "")
    people = pending.get("people", "")
    preferences = pending.get("preferences_text", "")

    planning_constraints = dict(pending.get("planning_constraints") or {})
    if "radius_filter" in pending and "semantic_search_radius_km" not in planning_constraints:
        planning_constraints["semantic_search_radius_km"] = pending["radius_filter"]["max_radius_km"]

    if mode == "change_hotel":
        if not os.path.exists(CURRENT_TRIP_PLAN_FILE):
            _clear_pending_hotel_selection()
            return "SYSTEM ERROR: Không còn kế hoạch chuyến đi để đổi khách sạn."
        try:
            with open(CURRENT_TRIP_PLAN_FILE, "r", encoding="utf-8") as f:
                current_data = json.load(f)
        except Exception as e:
            return f"SYSTEM ERROR: Không thể đọc file kế hoạch hiện tại: {e}"

        saved_itinerary = (current_data.get("itineraries") or [{}])[0]
        if isinstance(saved_itinerary, dict) and str(saved_itinerary.get("status") or "").casefold() == "finalized":
            _clear_pending_hotel_selection()
            return "Kế hoạch đã xác nhận không thể chỉnh sửa. Hãy tạo một kế hoạch mới nếu cần thay đổi."

        try:
            updated_data = _build_trip_data(
                destination,
                duration,
                people,
                preferences,
                preselected_hotel=hotel_data,
                planning_constraints=planning_constraints,
            )
        except Exception as exc:
            logger.exception("Hotel change failed")
            return f"SYSTEM ERROR: {exc}"

        updated_data.setdefault("adjustments", []).append(
            "Đã đổi khách sạn và lập lại toàn bộ các cụm địa điểm theo vị trí mới."
        )
        updated_itinerary = (updated_data.get("itineraries") or [{}])[0]
        if isinstance(updated_itinerary, dict):
            updated_itinerary["status"] = "Draft"
            updated_itinerary.pop("summary", None)
            if planning_constraints:
                updated_itinerary["planning_constraints"] = planning_constraints
                updated_data.setdefault("adjustments", []).extend(
                    _reapply_planning_constraints(updated_data)
                )
        _save_trip_data(updated_data)
        _clear_pending_hotel_selection()
        return format_trip_response_from_json(updated_data)

    result = _generate_and_save_itinerary(
        destination,
        duration,
        people,
        preferences,
        preselected_hotel=hotel_data,
        planning_constraints=planning_constraints if planning_constraints else None,
    )
    if not str(result).startswith("SYSTEM ERROR:"):
        _clear_pending_hotel_selection()
    return result


@tool
def _legacy_modify_trip_plan(modification_request: str) -> str:
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
            destination_id = str(
                (current_data.get("itineraries") or [{}])[0].get("destination_id")
                or _get_destination_id(destination)
                or ""
            )
            if not destination_id:
                raise ValueError("Không xác định được điểm đến của kế hoạch hiện tại.")
            hotel_query = change.query or modification_request
            parsed_target_price = _parse_free_text_price(modification_request)
            planning_constraints = dict((current_data.get("itineraries") or [{}])[0].get("planning_constraints") or {})
            max_radius_km = planning_constraints.get("semantic_search_radius_km")
            root_lat, root_lon = (None, None)
            current_hotel_coords = (current_data.get("hotel") or {}).get("coordinates")
            if max_radius_km is not None and current_hotel_coords:
                parts = [p.strip() for p in current_hotel_coords.split(",") if p.strip()]
                if len(parts) == 2:
                    try:
                        root_lat, root_lon = float(parts[0]), float(parts[1])
                        max_radius_km = float(max_radius_km)
                    except ValueError:
                        root_lat, root_lon, max_radius_km = (None, None, None)

            options = rank_hotel_candidates(
                select_hotel_candidates(
                    destination,
                    destination_id,
                    people,
                    hotel_query=hotel_query,
                    max_price=parsed_target_price,
                    root_latitude=root_lat,
                    root_longitude=root_lon,
                    max_radius_km=max_radius_km,
                ),
                target_price=parsed_target_price,
            )
            if not options:
                raise ValueError(f"Không tìm thấy khách sạn phù hợp tại {destination}.")
            _save_pending_hotel_selection(
                {
                    "mode": "change_hotel",
                    "destination": destination,
                    "destination_id": destination_id,
                    "duration": duration,
                    "people": people,
                    "preferences_text": preferences,
                    "hotel_query": hotel_query,
                    "planning_constraints": planning_constraints,
                    "created_at": datetime.now().isoformat(),
                    "options": [data for data, _candidate in options],
                }
            )
            return format_hotel_options(options)

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


def execute_trip_edit_request(modification_request: str, plan: TripEditPlan) -> str | None:
    """Execute an already validated LLM edit plan against the saved Draft."""
    if not os.path.exists(CURRENT_TRIP_PLAN_FILE):
        return "SYSTEM ERROR: Chưa có kế hoạch chuyến đi để chỉnh sửa."
    try:
        with open(CURRENT_TRIP_PLAN_FILE, "r", encoding="utf-8") as file_handle:
            current_data = json.load(file_handle)
    except (OSError, json.JSONDecodeError) as exc:
        return f"SYSTEM ERROR: Không thể đọc kế hoạch hiện tại: {exc}"

    saved_itinerary = (current_data.get("itineraries") or [{}])[0]
    if isinstance(saved_itinerary, dict) and str(saved_itinerary.get("status") or "").casefold() == "finalized":
        return "Kế hoạch đã xác nhận không thể chỉnh sửa. Hãy tạo một kế hoạch mới nếu cần thay đổi."
    if plan.decision == "clarify":
        return plan.clarification_question or "Bạn muốn chỉnh sửa phần nào của lịch trình?"
    if plan.decision == "not_edit":
        return None

    hotel_change = next((operation for operation in plan.operations if operation.operation == "change_hotel"), None)
    if hotel_change:
        try:
            destination, duration, people, preferences = _current_trip_parameters(current_data)
            destination_id = str(saved_itinerary.get("destination_id") or _get_destination_id(destination) or "")
            if not destination or not destination_id:
                raise ValueError("Kế hoạch hiện tại thiếu điểm đến để đổi khách sạn.")
            planning_constraints = dict(saved_itinerary.get("planning_constraints") or {})
            
            old_min_price = planning_constraints.get("min_price")
            old_max_price = planning_constraints.get("max_price")
            old_target_price = planning_constraints.get("target_price")
            old_amenity_prefs = planning_constraints.get("amenity_prefs") or []
            old_hotel_query = planning_constraints.get("hotel_query")

            hotel_query = hotel_change.hotel_query or old_hotel_query or modification_request
            
            parsed_target_price = _parse_free_text_price(modification_request)
            if parsed_target_price is not None:
                new_target_price = parsed_target_price
                new_min_price = None
                new_max_price = parsed_target_price
            else:
                new_target_price = old_target_price
                new_min_price = old_min_price
                new_max_price = old_max_price
            
            max_radius_km = planning_constraints.get("semantic_search_radius_km")
            root_lat, root_lon = (None, None)
            current_hotel_coords = (current_data.get("hotel") or {}).get("coordinates")
            if max_radius_km is not None and current_hotel_coords:
                parts = [p.strip() for p in current_hotel_coords.split(",") if p.strip()]
                if len(parts) == 2:
                    try:
                        root_lat, root_lon = float(parts[0]), float(parts[1])
                        max_radius_km = float(max_radius_km)
                    except ValueError:
                        root_lat, root_lon, max_radius_km = (None, None, None)

            options = rank_hotel_candidates(
                select_hotel_candidates(
                    destination,
                    destination_id,
                    people,
                    hotel_query=hotel_query,
                    min_price=new_min_price,
                    max_price=new_max_price,
                    root_latitude=root_lat,
                    root_longitude=root_lon,
                    max_radius_km=max_radius_km,
                ),
                target_price=new_target_price,
                amenity_prefs=frozenset(old_amenity_prefs),
            )
            if not options:
                raise ValueError(f"Không tìm thấy khách sạn phù hợp tại {destination}.")
                
            if new_target_price is not None:
                planning_constraints["target_price"] = new_target_price
            if new_min_price is not None:
                planning_constraints["min_price"] = new_min_price
            if new_max_price is not None:
                planning_constraints["max_price"] = new_max_price
            if hotel_query:
                planning_constraints["hotel_query"] = hotel_query

            _save_pending_hotel_selection(
                {
                    "mode": "change_hotel",
                    "destination": destination,
                    "destination_id": destination_id,
                    "duration": duration,
                    "people": people,
                    "preferences_text": preferences,
                    "hotel_query": hotel_query,
                    "planning_constraints": planning_constraints,
                    "created_at": datetime.now().isoformat(),
                    "options": [data for data, _candidate in options],
                }
            )
            return format_hotel_options(options)
        except Exception as exc:
            logger.exception("Failed to prepare hotel change")
            return f"SYSTEM ERROR: {exc}"

    try:
        adjustments = apply_trip_edit_plan(current_data, plan)
        current_data.setdefault("adjustments", []).extend(adjustments)
        _save_trip_data(current_data)
        logger.info("Applied LLM edit plan: %s", [operation.operation for operation in plan.operations])
        return format_trip_response_from_json(current_data)
    except Exception as exc:
        logger.exception("Failed to apply LLM edit plan")
        return f"SYSTEM ERROR: {exc}"


@tool
def modify_trip_plan(modification_request: str) -> str:
    """Apply a constrained stateless LLM plan to an existing Draft itinerary."""
    if not os.path.exists(CURRENT_TRIP_PLAN_FILE):
        return "SYSTEM ERROR: Chưa có kế hoạch chuyến đi để chỉnh sửa."
    try:
        with open(CURRENT_TRIP_PLAN_FILE, "r", encoding="utf-8") as file_handle:
            current_data = json.load(file_handle)
        plan = plan_trip_edit(modification_request, current_data)
    except (OSError, json.JSONDecodeError, TripEditPlanError) as exc:
        logger.warning("Could not safely plan trip edit: %s", exc)
        return "SYSTEM ERROR: Không thể hiểu an toàn yêu cầu chỉnh sửa này. Vui lòng diễn đạt cụ thể hơn."
    result = execute_trip_edit_request(modification_request, plan)
    return result or "Yêu cầu này không thay đổi lịch trình hiện tại."


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
            hotel_id=str(itinerary.get("hotel_id") or (trip_data.get("hotel") or {}).get("id") or ""),
            planning_constraints=dict(itinerary.get("planning_constraints") or {}),
        )
        store = ItineraryStore.from_default()
        store.persist_itinerary_bundle(trip_data)
        result = store.finalize_trip_data(trip_data, reuse_query)
        itinerary["status"] = "Finalized"
        itinerary["summary"] = result.get("summary")
        # Already persisted + finalized above; re-persisting here would resend
        # the bundle to a now-finalized (immutable) row and fail.
        _save_trip_data(trip_data, persist=False)
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
        [recommend_hotels, select_hotel, modify_trip_plan, finalize_trip_plan],
        checkpointer=memory,
        prompt=SUPERVISOR_PROMPT,
    )
