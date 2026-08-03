"""Service module for data hydration, candidate retrieval, theme generation, and trip plan mutations."""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from copy import deepcopy
from dataclasses import replace
from datetime import datetime
from functools import lru_cache
from typing import Any, Dict, List

from supabase import Client, create_client

from src.config import get_settings
from src.services.hotel_selection import select_hotel_candidates
from src.services.itinerary_reuse import (
    ItineraryReuseQuery,
    ItineraryTemplate,
    classify_reuse_candidate,
    validate_template_bundle,
)
from src.services.itinerary_store import ItineraryStore, ItineraryStoreError
from src.services.llm import get_llm
from src.services.supabase_search import (
    search_attractions as rpc_search_attractions,
    search_hotels_with_rooms,
)
from src.services.trip_intake import (
    DestinationOption,
    destination_options_from_rows,
)
from src.services.trip_edit_planner import EditOperation, NewItemRequirements, TripEditPlan
from src.services.trip_scheduler import (
    DayTheme,
    PlaceCandidate,
    ScheduledItem,
    TripChange,
    apply_latest_outing_start,
    build_itinerary_with_hotel_reselection,
    default_duration_minutes,
    detect_covered_hotel_meals,
    fits_opening_hours,
    haversine_distance_km,
    normalize_day_themes,
    serialize_day_themes,
    validate_or_repair_day,
)

logger = logging.getLogger(__name__)

SESSION_DATA_DIR = "data"
CURRENT_TRIP_PLAN_FILE = os.path.join(SESSION_DATA_DIR, "current_trip_plan.json")
PENDING_HOTEL_SELECTION_FILE = os.path.join(SESSION_DATA_DIR, "pending_hotel_selection.json")
ENABLE_ITINERARY_REUSE = os.getenv("ENABLE_ITINERARY_REUSE", "false").casefold() in {"1", "true", "yes"}
ITINERARY_REUSE_TIER1_THRESHOLD = float(os.getenv("ITINERARY_REUSE_TIER1_THRESHOLD", "0.88"))


def clear_session_history() -> None:
    """Clear transient current trip plan, pending hotel selections, and working session files."""
    for filename in (
        CURRENT_TRIP_PLAN_FILE,
        PENDING_HOTEL_SELECTION_FILE,
        # Legacy bare-root paths from before these files moved under data/.
        os.path.basename(CURRENT_TRIP_PLAN_FILE),
        os.path.basename(PENDING_HOTEL_SELECTION_FILE),
    ):
        if os.path.exists(filename):
            try:
                os.remove(filename)
                logger.info("Removed session file: %s", filename)
            except Exception as exc:
                logger.warning("Could not remove %s: %s", filename, exc)


def _save_pending_hotel_selection(payload: Dict[str, Any]) -> None:
    """Persist the hotel options just shown to the user, so the next chat turn can
    resolve their reply (a rank number or a name) back to one of them."""
    os.makedirs(SESSION_DATA_DIR, exist_ok=True)
    with open(PENDING_HOTEL_SELECTION_FILE, "w", encoding="utf-8") as file_handle:
        json.dump(payload, file_handle, ensure_ascii=False, indent=2)


def _load_pending_hotel_selection() -> Dict[str, Any] | None:
    if not os.path.exists(PENDING_HOTEL_SELECTION_FILE):
        return None
    try:
        with open(PENDING_HOTEL_SELECTION_FILE, "r", encoding="utf-8") as file_handle:
            return json.load(file_handle)
    except Exception as exc:
        logger.error("Failed to read pending hotel selection: %s", exc)
        return None


def _clear_pending_hotel_selection() -> None:
    if os.path.exists(PENDING_HOTEL_SELECTION_FILE):
        os.remove(PENDING_HOTEL_SELECTION_FILE)


@lru_cache
def get_supabase_client() -> Client:
    settings = get_settings()
    url = getattr(settings, "supabase_url", None) or os.environ.get("SUPABASE_URL")
    key = getattr(settings, "supabase_service_key", None) or os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise ValueError("Missing SUPABASE_URL or SUPABASE_SERVICE_KEY in environment or settings.")
    return create_client(url, key)


def _get_destination_id(destination_name: str) -> str | None:
    try:
        supabase = get_supabase_client()
        clean_name = destination_name.lower().replace("đi ", "").replace("du lịch ", "").strip()
        response = supabase.table("destinations").select("id").ilike("name", f"%{clean_name}%").limit(1).execute()
        data = response.data
        if data:
            return data[0]["id"]
    except Exception as e:
        logger.error(f"Error fetching destination ID for {destination_name}: {e}")
    return None


@lru_cache
def _get_destination_names() -> tuple[DestinationOption, ...]:
    """Load canonical destinations and aliases once for deterministic intake."""
    try:
        supabase = get_supabase_client()
        try:
            response = (
                supabase.table("destinations")
                .select("name, aliases")
                .limit(1000)
                .execute()
            )
        except Exception as exc:
            logger.warning(
                "Destination aliases are unavailable; falling back to canonical names: %s",
                exc,
            )
            response = supabase.table("destinations").select("name").limit(1000).execute()
        return destination_options_from_rows(response.data or [])
    except Exception as exc:
        logger.error("Failed to load destination names for trip intake: %s", exc)
        return ()


def _strip_json_fence(content: str) -> str:
    content = content.strip()
    if content.startswith("```json"):
        content = content[7:]
    elif content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]
    return content.strip()


def _hydrate_records(table_name: str, search_results: List[Dict[str, Any]], fields: str) -> List[Dict[str, Any]]:
    """Merge compact RPC results with canonical Supabase rows without changing RPC contracts."""
    result_ids = [str(result.get("id")) for result in search_results if result.get("id")]
    if not result_ids:
        return []
    try:
        supabase = get_supabase_client()
        response = supabase.table(table_name).select(fields).in_("id", result_ids).execute()
        canonical_by_id = {str(row["id"]): row for row in response.data or [] if row.get("id")}
    except Exception as exc:
        logger.error("Failed to hydrate %s search results: %s", table_name, exc)
        return []
    hydrated = []
    for result in search_results:
        canonical = canonical_by_id.get(str(result.get("id")))
        if canonical:
            hydrated.append({**result, **canonical})
    return hydrated


def _to_place_candidates(rows: List[Dict[str, Any]]) -> List[PlaceCandidate]:
    candidates = []
    for row in rows:
        candidate = PlaceCandidate.from_mapping(row)
        if candidate.id and candidate.name and candidate.coordinate_pair:
            candidates.append(candidate)
    return candidates


def _generate_day_themes(
    destination: str,
    number_of_days: int,
    available_categories: List[str],
    preferences: List[str],
) -> List[DayTheme]:
    prompt = f"""Create {number_of_days} distinct daily travel themes for {destination}.
Use only these available database categories: {json.dumps(available_categories, ensure_ascii=False)}.
Honor these user preferences when possible: {json.dumps(preferences, ensure_ascii=False)}.
Do not select or invent venue names. Return raw JSON only:
{{"themes":[{{"day_number":1,"title":"Vietnamese title","query":"semantic search query"}}]}}
Every day_number from 1 through {number_of_days} must appear exactly once and titles must be distinct."""
    raw_themes = []
    try:
        llm = get_llm(temperature=0.3)
        from langchain_core.messages import HumanMessage, SystemMessage

        response = llm.invoke(
            [
                SystemMessage(content="You generate constrained JSON only."),
                HumanMessage(content=prompt),
            ]
        )
        parsed = json.loads(_strip_json_fence(response.content))
        if isinstance(parsed, dict) and isinstance(parsed.get("themes"), list):
            raw_themes = parsed["themes"]
    except Exception as exc:
        logger.warning("Theme generation failed; using deterministic themes: %s", exc)
    return normalize_day_themes(raw_themes, number_of_days, preferences)


def _search_attraction_candidates(
    query: str,
    destination_id: str,
    match_count: int = 20,
    root_latitude: float | None = None,
    root_longitude: float | None = None,
    max_radius_km: float | None = None,
) -> List[PlaceCandidate]:
    kwargs: Dict[str, Any] = {
        "query": query,
        "match_count": match_count,
        "filter_destination_id": destination_id,
        "use_llm_filter": False,
    }
    if root_latitude is not None or root_longitude is not None or max_radius_km is not None:
        kwargs["root_latitude"] = root_latitude
        kwargs["root_longitude"] = root_longitude
        kwargs["max_radius_km"] = max_radius_km

    compact_results = rpc_search_attractions(**kwargs) or []
    hydrated = _hydrate_records(
        "attractions",
        compact_results,
        (
            "id,destination_id,name,description,category,is_tour,estimated_duration_minutes,"
            "opening_time,closing_time,rating,coordinates"
        ),
    )
    return _to_place_candidates(hydrated)


def _select_real_hotel(
    destination: str,
    destination_id: str,
    people: str,
    hotel_query: str | None = None,
) -> List[tuple[Dict[str, Any], PlaceCandidate]]:
    """Delegate hotel selection to the dedicated hotel_selection service module."""
    return select_hotel_candidates(destination, destination_id, people, hotel_query)


def _find_reusable_template(query: ItineraryReuseQuery) -> ItineraryTemplate | None:
    """Return a hydrated Tier 1 candidate or safely fall through to normal planning."""
    if not ENABLE_ITINERARY_REUSE:
        return None
    try:
        store = ItineraryStore.from_default()
        candidates = store.search_reusable_itineraries(
            query,
            threshold=ITINERARY_REUSE_TIER1_THRESHOLD,
        )
        for candidate in candidates:
            decision = classify_reuse_candidate(
                candidate,
                query,
                threshold=ITINERARY_REUSE_TIER1_THRESHOLD,
            )
            if decision.action != "reuse":
                logger.info("reuse_rejected template=%s reason=%s", candidate.id, decision.reason)
                continue
            bundle = store.load_itinerary_bundle(candidate.id)
            if not bundle:
                logger.info("reuse_rejected template=%s reason=missing_bundle", candidate.id)
                continue
            valid, reasons = validate_template_bundle(bundle.template)
            hotel_destination = str(bundle.hotel.get("destination_id") or "")
            if not valid or hotel_destination != query.destination_id or not bundle.hotel.get("coordinates"):
                reason = reasons[0] if reasons else "invalid_hotel"
                logger.info("reuse_rejected template=%s reason=%s", candidate.id, reason)
                continue
            logger.info("reuse_hit template=%s similarity=%.3f", candidate.id, candidate.similarity)
            return bundle.template
        logger.info("reuse_miss reason=no_qualified_candidate")
    except ItineraryStoreError as exc:
        logger.warning("reuse_miss reason=store_error detail=%s", exc)
    except Exception as exc:
        logger.warning("reuse_miss reason=unexpected_error detail=%s", exc)
    return None


def _serialize_schedule_item(
    item: ScheduledItem,
    itinerary_id: str,
    timestamp: str,
) -> Dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "itinerary_id": itinerary_id,
        "day_number": item.day_number,
        "order_index": item.order_index,
        "start_time": item.start_time,
        "end_time": item.end_time,
        "reference_type": item.reference_type,
        "reference_id": item.reference_id,
        "estimated_cost": None,
        "created_at": timestamp,
        "updated_at": timestamp,
        "activity": item.activity,
        "kind": item.kind,
        "item_kind": item.kind,
        "coordinates": item.coordinates,
    }


def _persist_itinerary_metadata(trip_data: Dict[str, Any]) -> None:
    """Persist a complete bundle, falling back only for an unapplied migration."""
    itineraries = trip_data.get("itineraries") or []
    itinerary = itineraries[0] if isinstance(itineraries, list) else itineraries
    if not isinstance(itinerary, dict) or not itinerary.get("id"):
        return
    session_id = itinerary.get("session_id")
    if session_id:
        try:
            supabase = get_supabase_client()
            supabase.table("sessions").upsert({"session_id": session_id}).execute()
        except Exception as exc:
            logger.debug("Could not pre-insert session %s: %s", session_id, exc)
    try:
        ItineraryStore.from_default().persist_itinerary_bundle(trip_data)
        return
    except ItineraryStoreError as exc:
        logger.warning("Complete itinerary persistence unavailable; retaining local JSON: %s", exc)
    row = {
        key: itinerary.get(key)
        for key in (
            "id",
            "session_id",
            "destination_id",
            "hotel_id",
            "duration_days",
            "number_of_adults",
            "number_of_children",
            "budget",
            "preferences",
            "day_themes",
            "status",
            "created_at",
            "updated_at",
        )
    }
    row["day_themes"] = itinerary.get("day_themes") or []
    try:
        supabase = get_supabase_client()
        supabase.table("itineraries").upsert(row).execute()
    except Exception as exc:
        logger.warning(
            "Could not persist itinerary metadata to Supabase; apply "
            "scripts/migrations/20260727_add_itinerary_day_themes.sql first: %s",
            exc,
        )


def _build_trip_data(
    destination: str,
    duration: str,
    people: str,
    preferences_text: str = "",
    hotel_query: str | None = None,
    themes_override: List[Dict[str, Any]] | None = None,
    preselected_hotel: Dict[str, Any] | None = None,
    planning_constraints: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    destination_id = _get_destination_id(destination)
    if not destination_id:
        raise ValueError(f"Không tìm thấy dữ liệu điểm đến cho {destination}.")
    destination_id = str(destination_id)
    number_of_days = parse_duration_to_days(duration)
    try:
        number_of_people = int("".join(filter(str.isdigit, people))) if any(char.isdigit() for char in people) else 1
    except (TypeError, ValueError):
        number_of_people = 1

    preferences = [part.strip() for part in preferences_text.replace(";", ",").split(",") if part.strip()]
    child_focused_text = f"{people} {preferences_text}".casefold()
    child_focused = any(
        keyword in child_focused_text
        for keyword in ("trẻ em", "tre em", "children", "child", "kids", "gia đình", "gia dinh")
    )
    if preselected_hotel is not None:
        preselected_candidate = PlaceCandidate.from_mapping({**preselected_hotel, "category": "Hotel"})
        if not preselected_candidate.id or not preselected_candidate.coordinate_pair:
            raise ValueError("Khách sạn đã chọn thiếu tọa độ hợp lệ; không thể lập lịch trình.")
        hotel_options = [(preselected_hotel, preselected_candidate)]
    else:
        hotel_options = _select_real_hotel(destination, destination_id, people, hotel_query)
        if not hotel_options:
            raise ValueError(
                f"Không tìm thấy khách sạn có tọa độ hợp lệ tại {destination}; không thể lập lịch trình theo vị trí khách sạn."
            )
    hotel_candidates = [candidate for _, candidate in hotel_options]
    reuse_query = ItineraryReuseQuery(
        destination_id=destination_id,
        destination_name=destination,
        duration_days=number_of_days,
        number_of_adults=number_of_people,
        preferences=tuple(preferences),
        child_focused=child_focused,
        hotel_id=hotel_candidates[0].id,
        planning_constraints=dict(planning_constraints or {}),
    )
    reusable_template = _find_reusable_template(reuse_query) if themes_override is None else None

    raw_themes = themes_override or (list(reusable_template.day_themes) if reusable_template else None)
    if raw_themes is not None:
        themes = normalize_day_themes(raw_themes, number_of_days, preferences)
    else:
        supabase = get_supabase_client()
        category_rows = (
            supabase.table("attractions")
            .select("category")
            .eq("destination_id", destination_id)
            .limit(1000)
            .execute()
            .data
            or []
        )
        categories = sorted({str(row.get("category")) for row in category_rows if row.get("category")})
        themes = _generate_day_themes(destination, number_of_days, categories, preferences)

    active_radius_km = (dict(planning_constraints or {})).get("semantic_search_radius_km")
    if active_radius_km is None:
        active_radius_km = 15.0
    active_radius_km = float(active_radius_km)

    active_lat, active_lon = (None, None)
    if hotel_candidates and hotel_candidates[0].coordinate_pair:
        active_lat, active_lon = hotel_candidates[0].coordinate_pair

    themed_candidates: Dict[int, List[PlaceCandidate]] = {}
    for theme in themes:
        themed_candidates[theme.day_number] = _search_attraction_candidates(
            f"{theme.query}. Destination: {destination}",
            destination_id,
            match_count=20,
            root_latitude=active_lat,
            root_longitude=active_lon,
            max_radius_km=active_radius_km,
        )
    pool_size = min(max(number_of_days * 3, 15), 50)
    restaurants = []
    if any("lunch" not in hotel.covered_meals for hotel in hotel_candidates):
        restaurants = _search_attraction_candidates(
            f"local restaurant lunch Vietnamese food in {destination}",
            destination_id,
            match_count=pool_size,
            root_latitude=active_lat,
            root_longitude=active_lon,
            max_radius_km=active_radius_km,
        )
    cafes = _search_attraction_candidates(
        f"coffee shop cafe relaxation in {destination}",
        destination_id,
        match_count=pool_size,
        root_latitude=active_lat,
        root_longitude=active_lon,
        max_radius_km=active_radius_km,
    )
    breakfasts = []
    if any("breakfast" not in hotel.covered_meals for hotel in hotel_candidates):
        breakfasts = _search_attraction_candidates(
            f"breakfast restaurant cafe morning food in {destination}",
            destination_id,
            match_count=pool_size,
            root_latitude=active_lat,
            root_longitude=active_lon,
            max_radius_km=active_radius_km,
        )
    dinners = []
    if any("dinner" not in hotel.covered_meals for hotel in hotel_candidates):
        dinners = _search_attraction_candidates(
            f"dinner restaurant evening dining in {destination}",
            destination_id,
            match_count=pool_size,
            root_latitude=active_lat,
            root_longitude=active_lon,
            max_radius_km=active_radius_km,
        )
    hotel_candidate, schedule = build_itinerary_with_hotel_reselection(
        hotel_candidates,
        themes,
        themed_candidates,
        restaurants,
        cafes,
        breakfasts=breakfasts,
        dinners=dinners,
        child_focused=child_focused,
    )
    hotel_data = next(
        data for data, candidate in hotel_options if candidate.id == hotel_candidate.id
    )
    if hotel_candidate.id != hotel_candidates[0].id:
        # The initial reuse lookup was hard-filtered to the primary hotel. Do
        # not attach that template's lineage when scheduling selected another
        # hotel for geographic viability.
        reusable_template = None
        logger.info(
            "hotel_reselected primary=%s selected=%s reason=insufficient_core_attractions",
            hotel_candidates[0].id,
            hotel_candidate.id,
        )

    now_iso = datetime.now().isoformat()
    itinerary_id = str(uuid.uuid4())
    day_themes = serialize_day_themes(themes)
    itinerary_record = {
        "id": itinerary_id,
        "session_id": "poc_trip_planner_1",
        "duration_days": number_of_days,
        "number_of_adults": number_of_people,
        "number_of_children": 0,
        "budget": None,
        "preferences": [destination, *preferences],
        "day_themes": day_themes,
        "planning_constraints": dict(planning_constraints or {}),
        "destination_id": destination_id,
        "hotel_id": hotel_data["id"],
        "parent_itinerary_id": reusable_template.id if reusable_template else None,
        "status": "Draft",
        "created_at": now_iso,
        "updated_at": now_iso,
    }
    return {
        "hotel": hotel_data,
        "itineraries": [itinerary_record],
        "itinerary_items": [
            _serialize_schedule_item(item, itinerary_id, now_iso) for item in schedule.items
        ],
        "adjustments": [
            *schedule.adjustments,
            *(["Đã dùng chủ đề từ lịch trình tương tự và lập lại lịch mới theo dữ liệu hiện tại."] if reusable_template else []),
        ],
    }


def _save_trip_data(trip_data: Dict[str, Any], *, persist: bool = True) -> None:
    os.makedirs(SESSION_DATA_DIR, exist_ok=True)
    with open(CURRENT_TRIP_PLAN_FILE, "w", encoding="utf-8") as file_handle:
        json.dump(trip_data, file_handle, ensure_ascii=False, indent=2)
    if persist:
        _persist_itinerary_metadata(trip_data)


def _parse_trip_change(modification_request: str) -> TripChange:
    prompt = f"""Classify this Vietnamese trip-plan edit request into exactly one action.

Actions:
- change_hotel: user wants a different hotel/accommodation for the whole trip (mentions "khách sạn", "resort", "chỗ ở", "đổi phòng"). Applies to the whole trip, not one day.
- replace_place: user wants to swap one specific attraction/restaurant/venue for another, keeping the same hotel.
- reschedule: user wants to move an existing activity to a different time, without changing which venue it is.
- add_place: user wants to add a new activity/venue that is not currently in the plan.
- remove_place: user wants to delete an existing activity/venue from the plan.

Request: {modification_request}
Return raw JSON only with this schema:
{{
  "action": "change_hotel|replace_place|reschedule|add_place|remove_place|set_latest_outing_start|set_meal_self_selected",
  "day_number": 1,
  "day_numbers": [1, 2],
  "order_index": 1,
  "query": "venue or hotel requirements",
  "requested_time": "HH:MM",
  "meal_kind": "breakfast|lunch|dinner"
}}
day_number/order_index apply only to replace_place, reschedule, add_place, remove_place — use null for both when action is change_hotel.
Use null for fields that do not apply. Never return itinerary JSON."""
    try:
        llm = get_llm(temperature=0.0)
        from langchain_core.messages import HumanMessage, SystemMessage

        response = llm.invoke(
            [
                SystemMessage(content="You classify edit intent and output constrained JSON only."),
                HumanMessage(content=prompt),
            ]
        )
        raw = json.loads(_strip_json_fence(response.content))
        action = raw.get("action")
        if action in {
            "change_hotel",
            "replace_place",
            "reschedule",
            "add_place",
            "remove_place",
            "set_latest_outing_start",
            "set_meal_self_selected",
        }:
            day_numbers = tuple(
                int(value) for value in raw.get("day_numbers") or [] if str(value).isdigit()
            )
            return TripChange(
                action=action,
                day_number=int(raw["day_number"]) if raw.get("day_number") else None,
                day_numbers=day_numbers,
                order_index=int(raw["order_index"]) if raw.get("order_index") else None,
                query=str(raw.get("query") or modification_request),
                requested_time=str(raw["requested_time"]) if raw.get("requested_time") else None,
                meal_kind=(
                    str(raw["meal_kind"])
                    if raw.get("meal_kind") in {"breakfast", "lunch", "dinner"}
                    else None
                ),
            )
    except Exception as exc:
        logger.warning("Structured edit classification failed: %s", exc)

    return TripChange(
        action="replace_place",
        day_number=None,
        order_index=None,
        query=modification_request,
        requested_time=None,
    )


def _current_trip_parameters(current_data: Dict[str, Any]) -> tuple[str, str, str, str]:
    itineraries = current_data.get("itineraries") or [{}]
    itinerary = itineraries[0] if isinstance(itineraries, list) else itineraries
    preferences = list(itinerary.get("preferences") or [])
    destination = str(preferences[0]) if preferences else ""
    duration = f"{int(itinerary.get('duration_days') or 1)} ngày"
    people = f"{int(itinerary.get('number_of_adults') or 1)} người"
    preference_text = ", ".join(str(value) for value in preferences[1:])
    return destination, duration, people, preference_text


def _apply_latest_outing_constraint(
    current_data: Dict[str, Any],
    day_numbers: tuple[int, ...],
    cutoff: str,
) -> List[str]:
    itinerary_rows = current_data.get("itineraries") or [{}]
    itinerary = itinerary_rows[0] if isinstance(itinerary_rows, list) else itinerary_rows
    if not isinstance(itinerary, dict):
        raise ValueError("Kế hoạch hiện tại không có bản ghi lịch trình hợp lệ.")

    repaired, removed_ids = apply_latest_outing_start(
        current_data.get("itinerary_items") or [], day_numbers, cutoff
    )
    current_data["itinerary_items"] = repaired
    constraints = dict(itinerary.get("planning_constraints") or {})
    cutoff_by_day = dict(constraints.get("latest_outing_start_by_day") or {})
    normalized_cutoff = cutoff[:5]
    for day_number in day_numbers:
        cutoff_by_day[str(day_number)] = normalized_cutoff
    constraints["latest_outing_start_by_day"] = cutoff_by_day
    itinerary["planning_constraints"] = constraints

    day_label = ", ".join(str(day) for day in day_numbers)
    adjustments = [
        f"Đã lưu giới hạn: không bắt đầu điểm đi chơi mới từ {normalized_cutoff} ở ngày {day_label}."
    ]
    if removed_ids:
        adjustments.append(
            f"Đã bỏ {len(removed_ids)} điểm bắt đầu từ {normalized_cutoff} trở đi; hoạt động bắt đầu sớm hơn vẫn được giữ."
        )
    return adjustments


def _reapply_planning_constraints(
    current_data: Dict[str, Any],
    *,
    only_days: tuple[int, ...] | None = None,
) -> List[str]:
    itinerary_rows = current_data.get("itineraries") or [{}]
    itinerary = itinerary_rows[0] if isinstance(itinerary_rows, list) else itinerary_rows
    if not isinstance(itinerary, dict):
        return []
    planning_constraints = itinerary.get("planning_constraints") or {}
    cutoff_by_day = planning_constraints.get(
        "latest_outing_start_by_day"
    ) or {}
    selected_days = set(only_days or ())
    grouped: Dict[str, List[int]] = {}
    for day_text, cutoff in cutoff_by_day.items():
        try:
            day_number = int(day_text)
        except (TypeError, ValueError):
            continue
        if selected_days and day_number not in selected_days:
            continue
        grouped.setdefault(str(cutoff), []).append(day_number)

    adjustments: List[str] = []
    for cutoff, days in grouped.items():
        adjustments.extend(
            _apply_latest_outing_constraint(current_data, tuple(sorted(days)), cutoff)
        )
    end_cutoff_by_day = planning_constraints.get("latest_outing_end_by_day") or {}
    end_grouped: Dict[str, List[int]] = {}
    for day_text, cutoff in end_cutoff_by_day.items():
        try:
            day_number = int(day_text)
        except (TypeError, ValueError):
            continue
        if selected_days and day_number not in selected_days:
            continue
        end_grouped.setdefault(str(cutoff), []).append(day_number)
    for cutoff, days in end_grouped.items():
        adjustments.extend(
            _apply_latest_outing_end_constraint(current_data, tuple(sorted(days)), cutoff)
        )
    meal_preferences = planning_constraints.get("meal_preferences") or {}
    for meal_kind, preference in meal_preferences.items():
        if preference == "self_selected" and meal_kind in {"breakfast", "lunch", "dinner"}:
            adjustments.extend(
                _apply_self_selected_meal_constraint(
                    current_data,
                    meal_kind,
                    only_days=only_days,
                )
            )
    day_meal_preferences = planning_constraints.get("meal_preferences_by_day") or {}
    for day_text, preferences in day_meal_preferences.items():
        try:
            day_number = int(day_text)
        except (TypeError, ValueError):
            continue
        if selected_days and day_number not in selected_days:
            continue
        if not isinstance(preferences, dict):
            continue
        for meal_kind, preference in preferences.items():
            if preference == "self_selected" and meal_kind in {"breakfast", "lunch", "dinner"}:
                adjustments.extend(
                    _apply_self_selected_meal_constraint(
                        current_data,
                        meal_kind,
                        only_days=(day_number,),
                    )
                )
    return adjustments


def _itinerary_record(current_data: Dict[str, Any]) -> Dict[str, Any]:
    rows = current_data.get("itineraries") or [{}]
    itinerary = rows[0] if isinstance(rows, list) else rows
    if not isinstance(itinerary, dict):
        raise ValueError("Kế hoạch hiện tại không có bản ghi lịch trình hợp lệ.")
    return itinerary


def _clock_minutes(value: str) -> int:
    hour_text, minute_text, *_ = value.split(":")
    return int(hour_text) * 60 + int(minute_text)


def _renumber_items(current_data: Dict[str, Any], day_numbers: tuple[int, ...] | None = None) -> None:
    selected_days = set(day_numbers or ())
    items = sorted(
        current_data.get("itinerary_items") or [],
        key=lambda item: (int(item.get("day_number") or 0), str(item.get("start_time") or ""), int(item.get("order_index") or 0)),
    )
    counts: Dict[int, int] = {}
    for item in items:
        day = int(item.get("day_number") or 0)
        if not selected_days or day in selected_days:
            counts[day] = counts.get(day, 0) + 1
            item["order_index"] = counts[day]
    current_data["itinerary_items"] = items


def _remove_item_by_id(current_data: Dict[str, Any], item_id: str) -> Dict[str, Any]:
    items = current_data.get("itinerary_items") or []
    removed = next((item for item in items if str(item.get("id")) == item_id), None)
    if removed is None:
        raise ValueError("Không tìm thấy hoạt động cần chỉnh sửa trong lịch trình hiện tại.")
    current_data["itinerary_items"] = [item for item in items if str(item.get("id")) != item_id]
    _renumber_items(current_data, (int(removed.get("day_number") or 0),))
    return removed


def _clock_text(minutes: int) -> str:
    minutes = max(0, min(minutes, 23 * 60 + 59))
    hour, minute = divmod(minutes, 60)
    return f"{hour:02d}:{minute:02d}:00"


def _close_gap_after_removal(current_data: Dict[str, Any], removed: Dict[str, Any]) -> None:
    """Move following saved slots earlier, leaving final conflict repair to the scheduler."""
    day_number = int(removed.get("day_number") or 0)
    start_time = str(removed.get("start_time") or "")
    end_time = str(removed.get("end_time") or "")
    if not start_time or not end_time:
        return
    duration = _clock_minutes(end_time) - _clock_minutes(start_time)
    if duration <= 0:
        return
    for item in current_data.get("itinerary_items") or []:
        if int(item.get("day_number") or 0) != day_number:
            continue
        item_start = str(item.get("start_time") or "")
        item_end = str(item.get("end_time") or "")
        if item_start and item_end and _clock_minutes(item_start) >= _clock_minutes(end_time):
            item["start_time"] = _clock_text(_clock_minutes(item_start) - duration)
            item["end_time"] = _clock_text(_clock_minutes(item_end) - duration)


def _set_meal_preference(
    current_data: Dict[str, Any],
    operation: EditOperation,
) -> List[str]:
    meal_kind = operation.meal_kind
    preference = operation.meal_preference
    if meal_kind not in {"breakfast", "lunch", "dinner"} or preference not in {"self_selected", "automatic"}:
        raise ValueError("Thiếu thông tin bữa ăn cần cập nhật.")
    itinerary = _itinerary_record(current_data)
    selected_days = operation.day_numbers or ((operation.day_number,) if operation.day_number else ())
    if preference == "self_selected":
        kept = []
        removed_count = 0
        for item in current_data.get("itinerary_items") or []:
            in_scope = not selected_days or int(item.get("day_number") or 0) in selected_days
            if in_scope and _item_kind(item) == meal_kind:
                removed_count += 1
                continue
            kept.append(item)
        current_data["itinerary_items"] = kept
        _renumber_items(current_data, selected_days or None)

        constraints = dict(itinerary.get("planning_constraints") or {})
        if selected_days:
            by_day = dict(constraints.get("meal_preferences_by_day") or {})
            for day in selected_days:
                values = dict(by_day.get(str(day)) or {})
                values[meal_kind] = "self_selected"
                by_day[str(day)] = values
            constraints["meal_preferences_by_day"] = by_day
        else:
            preferences = dict(constraints.get("meal_preferences") or {})
            preferences[meal_kind] = "self_selected"
            constraints["meal_preferences"] = preferences
        itinerary["planning_constraints"] = constraints
        labels = {"breakfast": "bữa sáng", "lunch": "bữa trưa", "dinner": "bữa tối"}
        return [f"Đã để bạn tự chọn {labels[meal_kind]} và bỏ {removed_count} gợi ý tự động."]

    constraints = dict(itinerary.get("planning_constraints") or {})
    preferences = dict(constraints.get("meal_preferences") or {})
    preferences.pop(meal_kind, None)
    constraints["meal_preferences"] = preferences
    itinerary["planning_constraints"] = constraints
    return ["Đã bật lại gợi ý bữa ăn tự động cho các lần lập lịch sau."]


def _apply_latest_outing_end_constraint(
    current_data: Dict[str, Any],
    day_numbers: tuple[int, ...],
    cutoff: str,
) -> List[str]:
    cutoff_minutes = _clock_minutes(cutoff)
    selected = set(day_numbers)
    kept = []
    removed = []
    for item in current_data.get("itinerary_items") or []:
        day = int(item.get("day_number") or 0)
        is_hotel = str(item.get("reference_type") or "").casefold() == "hotel"
        end_time = str(item.get("end_time") or "")
        if day in selected and not is_hotel and end_time and _clock_minutes(end_time) > cutoff_minutes:
            removed.append(item)
        else:
            kept.append(item)
    current_data["itinerary_items"] = kept
    _renumber_items(current_data, day_numbers)
    if removed:
        return [f"Đã bỏ {len(removed)} hoạt động kết thúc sau {cutoff}."]
    return [f"Đã áp dụng giới hạn kết thúc hoạt động trước {cutoff}."]


def _apply_schedule_policy(current_data: Dict[str, Any], operation: EditOperation) -> List[str]:
    itinerary = _itinerary_record(current_data)
    duration_days = int(itinerary.get("duration_days") or 1)
    days = operation.day_numbers or ((operation.day_number,) if operation.day_number else tuple(range(1, duration_days + 1)))
    constraints = dict(itinerary.get("planning_constraints") or {})
    adjustments: List[str] = []
    if operation.latest_start_time:
        by_day = dict(constraints.get("latest_outing_start_by_day") or {})
        for day in days:
            by_day[str(day)] = operation.latest_start_time
        constraints["latest_outing_start_by_day"] = by_day
        for day in days:
            adjustments.extend(_apply_latest_outing_constraint(current_data, (day,), operation.latest_start_time))
    if operation.latest_end_time:
        by_day = dict(constraints.get("latest_outing_end_by_day") or {})
        for day in days:
            by_day[str(day)] = operation.latest_end_time
        constraints["latest_outing_end_by_day"] = by_day
        adjustments.extend(_apply_latest_outing_end_constraint(current_data, tuple(days), operation.latest_end_time))
    if not adjustments:
        raise ValueError("Cần cung cấp giờ bắt đầu hoặc kết thúc hoạt động mới.")
    itinerary["planning_constraints"] = constraints
    return adjustments


def _child_focused_trip(current_data: Dict[str, Any]) -> bool:
    _, _, people, preferences = _current_trip_parameters(current_data)
    text = f"{people} {preferences}".casefold()
    return any(keyword in text for keyword in ("trẻ em", "tre em", "children", "child", "kids", "gia đình", "gia dinh"))


def _replace_scheduled_day(current_data: Dict[str, Any], day_number: int, scheduled: List[ScheduledItem]) -> List[str]:
    """Run the existing deterministic day repair and preserve matching item IDs."""
    _existing, hotel = _scheduled_day_from_json(current_data, day_number)
    child_focused = _child_focused_trip(current_data)
    outside_playgrounds = sum(
        1
        for item in current_data.get("itinerary_items", [])
        if int(item.get("day_number") or 0) != day_number
        and any(keyword in str(item.get("activity") or "").casefold() for keyword in ("playground", "trẻ em", "khu vui chơi trẻ em"))
    )
    repaired, adjustments = validate_or_repair_day(
        scheduled,
        hotel,
        child_focused=child_focused,
        playground_allowance=1 if child_focused else max(0, 1 - outside_playgrounds),
    )
    repaired = [replace(item, order_index=index) for index, item in enumerate(repaired, start=1)]
    _replace_day_in_json(current_data, day_number, repaired)
    return adjustments


def _candidate_text(candidate: PlaceCandidate) -> str:
    return f"{candidate.name} {candidate.category} {candidate.description or ''}".casefold()


def _candidate_matches_requirements(candidate: PlaceCandidate, requirements: NewItemRequirements) -> bool:
    text = _candidate_text(candidate)
    if requirements.included_categories and not any(value.casefold() in text for value in requirements.included_categories):
        return False
    if any(value.casefold() in text for value in requirements.excluded_categories):
        return False
    if requirements.item_kind in {"breakfast", "lunch", "dinner"}:
        return any(term in text for term in ("restaurant", "cafe", "coffee", "food", "bakery", "quán", "nhà hàng"))
    if requirements.item_kind == "coffee":
        return any(term in text for term in ("cafe", "coffee", "quán cà phê"))
    if requirements.item_kind in {"attraction", "evening"}:
        return not any(term in text for term in ("restaurant", "cafe", "coffee", "food", "bakery"))
    return True


def _candidate_anchor(
    scheduled: List[ScheduledItem],
    hotel: PlaceCandidate,
    target: ScheduledItem | None,
    requirements: NewItemRequirements,
) -> tuple[float, float] | None:
    if requirements.near == "hotel":
        return hotel.coordinate_pair
    if requirements.near == "target" and target:
        return target.coordinates or hotel.coordinate_pair
    if requirements.near == "previous_item" and target:
        index = scheduled.index(target)
        return scheduled[index - 1].coordinates if index else hotel.coordinate_pair
    if requirements.near == "next_item" and target:
        index = scheduled.index(target)
        return scheduled[index + 1].coordinates if index + 1 < len(scheduled) else hotel.coordinate_pair
    attraction = next((item for item in scheduled if item.kind == "attraction" and item.coordinates), None)
    return attraction.coordinates if attraction else hotel.coordinate_pair


def _select_edit_candidate(
    current_data: Dict[str, Any],
    scheduled: List[ScheduledItem],
    hotel: PlaceCandidate,
    requirements: NewItemRequirements,
    *,
    target: ScheduledItem | None,
    start_time: str,
) -> PlaceCandidate:
    destination_id = str((current_data.get("hotel") or {}).get("destination_id") or "")
    if not destination_id:
        destination_id = str(_itinerary_record(current_data).get("destination_id") or "")
    if not destination_id:
        raise ValueError("Thiếu mã điểm đến để tìm địa điểm mới.")
    constraints = dict(_itinerary_record(current_data).get("planning_constraints") or current_data.get("planning_constraints") or {})
    active_radius_km = constraints.get("semantic_search_radius_km")
    active_lat, active_lon = (None, None)
    if active_radius_km is not None and hotel and hotel.coordinate_pair:
        active_lat, active_lon = hotel.coordinate_pair
        active_radius_km = float(active_radius_km)

    candidates = _search_attraction_candidates(
        requirements.semantic_query,
        destination_id,
        match_count=40,
        root_latitude=active_lat,
        root_longitude=active_lon,
        max_radius_km=active_radius_km,
    )
    used_ids = {item.reference_id for item in scheduled if item is not target}
    anchor = _candidate_anchor(scheduled, hotel, target, requirements)
    eligible = []
    for candidate in candidates:
        if not candidate.id or candidate.id in used_ids or not _candidate_matches_requirements(candidate, requirements):
            continue
        duration = requirements.duration_minutes or (target.duration_minutes if target and requirements.preserve_duration else default_duration_minutes(candidate, requirements.item_kind))
        if not fits_opening_hours(candidate, start_time, duration):
            continue
        if anchor and not candidate.coordinate_pair:
            continue
        eligible.append(candidate)
    if not eligible:
        raise ValueError("Không tìm thấy địa điểm thật phù hợp với yêu cầu này.")

    if anchor:
        radii = (3.0, 5.0) if requirements.item_kind == "breakfast" else (5.0, 10.0, 15.0)
        nearby: List[PlaceCandidate] = []
        for radius in radii:
            nearby = [candidate for candidate in eligible if haversine_distance_km(anchor, candidate.coordinate_pair) <= radius]
            if nearby:
                break
        if not nearby:
            label = "gần khách sạn" if requirements.item_kind == "breakfast" else "gần cụm hoạt động"
            raise ValueError(f"Không tìm thấy địa điểm thật {label} trong phạm vi cho phép.")
        eligible = nearby
    return max(
        eligible,
        key=lambda candidate: (
            candidate.similarity,
            float(candidate.rating or 0.0),
            -(haversine_distance_km(anchor, candidate.coordinate_pair) if anchor and candidate.coordinate_pair else 0.0),
        ),
    )


def _scheduled_target(scheduled: List[ScheduledItem], target_id: str, current_data: Dict[str, Any]) -> tuple[int, ScheduledItem]:
    raw = next((item for item in current_data.get("itinerary_items") or [] if str(item.get("id")) == target_id), None)
    if raw is None:
        raise ValueError("Không tìm thấy hoạt động cần chỉnh sửa.")
    order_index = int(raw.get("order_index") or 0)
    for index, item in enumerate(scheduled):
        if item.order_index == order_index:
            return index, item
    raise ValueError("Không thể đọc hoạt động cần chỉnh sửa.")


def _apply_replace_or_add(current_data: Dict[str, Any], operation: EditOperation) -> List[str]:
    if not operation.requirements:
        raise ValueError("Thiếu yêu cầu địa điểm mới.")
    day_number = operation.day_number or (operation.target.day_number if operation.target else None)
    if not day_number:
        raise ValueError("Thiếu ngày cần chỉnh sửa.")
    scheduled, hotel = _scheduled_day_from_json(current_data, day_number)
    target = None
    target_index = None
    if operation.target and operation.target.item_id:
        target_index, target = _scheduled_target(scheduled, operation.target.item_id, current_data)
    if operation.operation == "replace_item" and target is None:
        raise ValueError("Thiếu hoạt động cần thay thế.")
    start_time = operation.requirements.preferred_start_time or (target.start_time if target else "09:00:00")
    candidate = _select_edit_candidate(
        current_data,
        scheduled,
        hotel,
        operation.requirements,
        target=target,
        start_time=start_time,
    )
    duration = operation.requirements.duration_minutes or (target.duration_minutes if target and operation.requirements.preserve_duration else None)
    kind = target.kind if target else operation.requirements.item_kind
    replacement = ScheduledItem.from_candidate(
        day_number,
        target.order_index if target else len(scheduled) + 1,
        candidate,
        kind,
        start_time,
        duration,
    )
    if target_index is None:
        scheduled.append(replacement)
    else:
        scheduled[target_index] = replacement
    adjustments = _replace_scheduled_day(current_data, day_number, scheduled)
    return [f"Đã chọn địa điểm thật {candidate.name}.", *adjustments]


def _apply_time_update(current_data: Dict[str, Any], operation: EditOperation) -> List[str]:
    if not operation.target or not operation.target.item_id:
        raise ValueError("Thiếu hoạt động cần đổi giờ.")
    day_number = operation.target.day_number
    if not day_number:
        raise ValueError("Thiếu ngày cần đổi giờ.")
    scheduled, _hotel = _scheduled_day_from_json(current_data, day_number)
    index, target = _scheduled_target(scheduled, operation.target.item_id, current_data)
    original_start = _clock_minutes(target.start_time)
    original_end = _clock_minutes(target.end_time)
    if operation.shift_minutes is not None:
        start_minutes = original_start + operation.shift_minutes
        end_minutes = original_end + operation.shift_minutes
    else:
        start_minutes = _clock_minutes(operation.start_time) if operation.start_time else original_start
        end_minutes = _clock_minutes(operation.end_time) if operation.end_time else start_minutes + target.duration_minutes
    if end_minutes <= start_minutes:
        raise ValueError("Giờ kết thúc phải sau giờ bắt đầu.")
    updated = ScheduledItem.from_candidate(
        target.day_number,
        target.order_index,
        PlaceCandidate(
            id=target.reference_id,
            name=target.place_name,
            category=target.category,
            coordinates=target.coordinates,
            opening_time=target.opening_time,
            closing_time=target.closing_time,
            estimated_duration_minutes=end_minutes - start_minutes,
        ),
        target.kind,
        f"{start_minutes // 60:02d}:{start_minutes % 60:02d}:00",
        end_minutes - start_minutes,
    )
    scheduled[index] = updated
    adjustments = _replace_scheduled_day(current_data, day_number, scheduled)
    return [f"Đã đổi giờ {target.place_name}.", *adjustments]


def _alternative_theme(current_data: Dict[str, Any], day_number: int) -> dict[str, str]:
    itinerary = _itinerary_record(current_data)
    used = {
        str(theme.get("title") or "").casefold()
        for theme in itinerary.get("day_themes") or []
        if int(theme.get("day_number") or 0) != day_number
    }
    options = (
        {"title": "Thiên nhiên và không gian xanh", "query": "nature parks gardens outdoor"},
        {"title": "Ẩm thực và đời sống địa phương", "query": "local food markets neighbourhood life"},
        {"title": "Văn hóa và di sản", "query": "museums culture heritage history"},
        {"title": "Giải trí và khám phá thành phố", "query": "city entertainment landmarks"},
    )
    return next((option for option in options if option["title"].casefold() not in used), options[0])


def _apply_day_replan(current_data: Dict[str, Any], operation: EditOperation) -> List[str]:
    if not operation.day_number or not operation.theme:
        raise ValueError("Thiếu ngày hoặc chủ đề cần lập lại.")
    destination, duration, people, preferences = _current_trip_parameters(current_data)
    itinerary = _itinerary_record(current_data)
    theme = dict(operation.theme)
    if theme.get("selection_mode") == "choose_alternative" and not theme.get("semantic_query"):
        theme = {**theme, **_alternative_theme(current_data, operation.day_number)}
    query = str(theme.get("semantic_query") or theme.get("query") or "").strip()
    title = str(theme.get("title") or "").strip()
    if not query:
        raise ValueError("Chủ đề mới cần có truy vấn tìm kiếm.")
    if not title:
        title = "Khám phá điểm đến theo chủ đề mới"
    if any(term in title.casefold() for term in ("ẩm thực", "food", "culinary")) and not any(
        term in query.casefold() for term in ("market", "chợ", "culinary", "ẩm thực", "food")
    ):
        query = f"{query} local food markets culinary culture"
    themes = [dict(value) for value in itinerary.get("day_themes") or []]
    if not themes:
        raise ValueError("Kế hoạch hiện tại không có chủ đề theo ngày.")
    for value in themes:
        if int(value.get("day_number") or 0) == operation.day_number:
            value.update({"day_number": operation.day_number, "title": title, "query": query})
    rebuilt = _build_trip_data(
        destination,
        duration,
        people,
        preferences,
        themes_override=themes,
        preselected_hotel=dict(current_data.get("hotel") or {}),
        planning_constraints=dict(itinerary.get("planning_constraints") or {}),
    )
    rebuilt_scheduled, _hotel = _scheduled_day_from_json(rebuilt, operation.day_number)
    _replace_day_in_json(current_data, operation.day_number, rebuilt_scheduled)
    itinerary["day_themes"] = themes
    _reapply_planning_constraints(current_data, only_days=(operation.day_number,))
    return [f"Đã lập lại ngày {operation.day_number} theo chủ đề {title}."]


def apply_trip_edit_plan(current_data: Dict[str, Any], plan: TripEditPlan) -> List[str]:
    """Apply a validated edit plan atomically to an in-memory trip bundle."""
    if plan.decision != "apply":
        raise ValueError("Chỉ kế hoạch chỉnh sửa đã được phê duyệt mới có thể áp dụng.")
    working = deepcopy(current_data)
    adjustments: List[str] = []
    for operation in plan.operations:
        if operation.operation == "remove_item":
            if not operation.target or not operation.target.item_id:
                raise ValueError("Thiếu hoạt động cần bỏ.")
            if operation.gap_policy == "replace":
                replacement = replace(operation, operation="replace_item")
                adjustments.extend(_apply_replace_or_add(working, replacement))
                continue
            removed = _remove_item_by_id(working, operation.target.item_id)
            if operation.gap_policy == "close_gap":
                _close_gap_after_removal(working, removed)
                scheduled, _hotel = _scheduled_day_from_json(working, int(removed.get("day_number") or 0))
                adjustments.extend(_replace_scheduled_day(working, int(removed.get("day_number") or 0), scheduled))
            adjustments.append(f"Đã bỏ {removed.get('activity') or 'hoạt động'}.")
            continue
        if operation.operation == "set_meal_preference":
            adjustments.extend(_set_meal_preference(working, operation))
            continue
        if operation.operation == "set_schedule_policy":
            adjustments.extend(_apply_schedule_policy(working, operation))
            continue
        if operation.operation == "change_hotel":
            raise ValueError("Đổi khách sạn cần chọn một khách sạn mới trước khi áp dụng.")
        if operation.operation in {"replace_item", "add_item"}:
            adjustments.extend(_apply_replace_or_add(working, operation))
            continue
        if operation.operation == "update_time":
            adjustments.extend(_apply_time_update(working, operation))
            continue
        if operation.operation == "replan_day":
            adjustments.extend(_apply_day_replan(working, operation))
            continue
        raise ValueError(f"Thao tác {operation.operation} chưa thể áp dụng.")

    itinerary = _itinerary_record(working)
    itinerary["status"] = "Draft"
    itinerary["updated_at"] = datetime.now().isoformat()
    itinerary.pop("summary", None)
    current_data.clear()
    current_data.update(working)
    return adjustments


def _item_kind(item: Dict[str, Any]) -> str:
    explicit = item.get("item_kind") or item.get("kind")
    if explicit in {
        "breakfast",
        "attraction",
        "lunch",
        "rest",
        "coffee",
        "dinner",
        "evening",
    }:
        return explicit
    activity = str(item.get("activity") or "").casefold()
    if "ăn sáng" in activity:
        return "breakfast"
    if "ăn trưa" in activity:
        return "lunch"
    if "ăn tối" in activity:
        return "dinner"
    if "cà phê" in activity or "coffee" in activity or "thư giãn" in activity:
        return "coffee"
    if "nghỉ" in activity:
        return "rest"
    if "dạo" in activity or "buổi tối" in activity:
        return "evening"
    return "attraction"


def _apply_self_selected_meal_constraint(
    current_data: Dict[str, Any],
    meal_kind: str,
    *,
    only_days: tuple[int, ...] | None = None,
) -> List[str]:
    itinerary_rows = current_data.get("itineraries") or [{}]
    itinerary = itinerary_rows[0] if isinstance(itinerary_rows, list) else itinerary_rows
    if not isinstance(itinerary, dict):
        raise ValueError("Kế hoạch hiện tại không có bản ghi lịch trình hợp lệ.")

    selected_days = set(only_days or ())
    kept_items = []
    removed_count = 0
    for item in current_data.get("itinerary_items") or []:
        day_number = int(item.get("day_number") or 0)
        in_scope = not selected_days or day_number in selected_days
        if in_scope and _item_kind(item) == meal_kind:
            removed_count += 1
            continue
        kept_items.append(item)

    kept_items.sort(
        key=lambda item: (
            int(item.get("day_number") or 0),
            int(item.get("order_index") or 0),
        )
    )
    next_index_by_day: Dict[int, int] = {}
    for item in kept_items:
        day_number = int(item.get("day_number") or 0)
        next_index_by_day[day_number] = next_index_by_day.get(day_number, 0) + 1
        item["order_index"] = next_index_by_day[day_number]
    current_data["itinerary_items"] = kept_items

    constraints = dict(itinerary.get("planning_constraints") or {})
    if selected_days:
        by_day = dict(constraints.get("meal_preferences_by_day") or {})
        for day_number in selected_days:
            day_preferences = dict(by_day.get(str(day_number)) or {})
            day_preferences[meal_kind] = "self_selected"
            by_day[str(day_number)] = day_preferences
        constraints["meal_preferences_by_day"] = by_day
    else:
        meal_preferences = dict(constraints.get("meal_preferences") or {})
        meal_preferences[meal_kind] = "self_selected"
        constraints["meal_preferences"] = meal_preferences
    itinerary["planning_constraints"] = constraints

    labels = {"breakfast": "bữa sáng", "lunch": "bữa trưa", "dinner": "bữa tối"}
    meal_label = labels[meal_kind]
    if removed_count:
        return [
            f"Đã để bạn tự chọn {meal_label} và bỏ {removed_count} gợi ý tự động; các hoạt động khác được giữ nguyên."
        ]
    return [f"Đã lưu lựa chọn để bạn tự chọn {meal_label}; không thêm địa điểm tự động."]


def _scheduled_day_from_json(current_data: Dict[str, Any], day_number: int) -> tuple[List[ScheduledItem], PlaceCandidate]:
    hotel_data = current_data.get("hotel") or {}
    hotel = PlaceCandidate.from_mapping({**hotel_data, "category": "Hotel"})
    if not hotel.id or not hotel.coordinate_pair:
        raise ValueError("Khách sạn hiện tại không có tọa độ hợp lệ.")
    rows = [
        item
        for item in current_data.get("itinerary_items", [])
        if int(item.get("day_number") or 0) == day_number
    ]
    attraction_ids = [
        str(item.get("reference_id"))
        for item in rows
        if item.get("reference_type") == "Attraction"
        and item.get("reference_id")
        and re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", str(item.get("reference_id")))
    ]
    attraction_by_id: Dict[str, Dict[str, Any]] = {}
    if attraction_ids:
        supabase = get_supabase_client()
        response = (
            supabase.table("attractions")
            .select(
                "id,name,description,category,is_tour,estimated_duration_minutes,"
                "opening_time,closing_time,rating,coordinates"
            )
            .in_("id", attraction_ids)
            .execute()
        )
        attraction_by_id = {str(row["id"]): row for row in response.data or []}

    scheduled = []
    for row in rows:
        reference_id = str(row.get("reference_id") or "")
        if row.get("reference_type") == "Hotel":
            candidate = hotel
        else:
            candidate_row = attraction_by_id.get(reference_id)
            if candidate_row:
                candidate = PlaceCandidate.from_mapping(candidate_row)
            else:
                # Saved plans already carry the minimum scheduling fields.  A
                # missing/deleted attraction must not make a local edit lose
                # the rest of its day, and test fixtures must not need live DB IDs.
                candidate = PlaceCandidate.from_mapping(
                    {
                        "id": reference_id,
                        "name": row.get("place_name") or row.get("activity") or "Địa điểm đã lưu",
                        "category": row.get("category") or "Other activities",
                        "coordinates": row.get("coordinates"),
                        "opening_time": row.get("opening_time"),
                        "closing_time": row.get("closing_time"),
                    }
                )
        kind = _item_kind(row)
        start_time = str(row.get("start_time") or "08:00:00")
        if len(start_time) == 5:
            start_time += ":00"
        duration = None
        end_time = row.get("end_time")
        if isinstance(end_time, str):
            start_hour, start_minute, *_ = start_time.split(":")
            end_hour, end_minute, *_ = end_time.split(":")
            duration = (int(end_hour) * 60 + int(end_minute)) - (int(start_hour) * 60 + int(start_minute))
        scheduled.append(
            ScheduledItem.from_candidate(
                day_number,
                int(row.get("order_index") or len(scheduled) + 1),
                candidate,
                kind,
                start_time,
                duration if duration and duration > 0 else None,
            )
        )
    return scheduled, hotel


def _replace_day_in_json(
    current_data: Dict[str, Any],
    day_number: int,
    scheduled_items: List[ScheduledItem],
) -> None:
    existing = [
        item
        for item in current_data.get("itinerary_items", [])
        if int(item.get("day_number") or 0) == day_number
    ]
    existing_by_key: Dict[tuple[str, str], List[Dict[str, Any]]] = {}
    for item in existing:
        existing_by_key.setdefault((str(item.get("reference_id")), _item_kind(item)), []).append(item)
    itinerary_id = str((current_data.get("itineraries") or [{}])[0].get("id"))
    now_iso = datetime.now().isoformat()
    replacements = []
    for scheduled in scheduled_items:
        key = (scheduled.reference_id, scheduled.kind)
        old = existing_by_key.get(key, []).pop(0) if existing_by_key.get(key) else None
        record = _serialize_schedule_item(scheduled, itinerary_id, now_iso)
        if old:
            record["id"] = old.get("id") or record["id"]
            record["created_at"] = old.get("created_at") or record["created_at"]
        replacements.append(record)
    untouched = [
        item
        for item in current_data.get("itinerary_items", [])
        if int(item.get("day_number") or 0) != day_number
    ]
    current_data["itinerary_items"] = sorted(
        [*untouched, *replacements],
        key=lambda item: (int(item.get("day_number") or 0), int(item.get("order_index") or 0)),
    )


def _apply_local_trip_change(
    current_data: Dict[str, Any],
    change: TripChange,
    modification_request: str,
) -> List[str]:
    if change.action == "set_meal_self_selected":
        if change.meal_kind not in {"breakfast", "lunch", "dinner"}:
            raise ValueError("Hãy nêu rõ bạn muốn tự chọn bữa sáng, bữa trưa hay bữa tối.")
        return _apply_self_selected_meal_constraint(current_data, change.meal_kind)

    if change.action == "set_latest_outing_start":
        day_numbers = change.day_numbers or (
            (change.day_number,) if change.day_number is not None else ()
        )
        if not day_numbers:
            raise ValueError("Hãy nêu rõ ngày cần áp dụng giới hạn giờ, hoặc chọn tất cả các ngày.")
        if not change.requested_time:
            raise ValueError("Hãy cung cấp giờ giới hạn theo dạng HH:MM.")
        return _apply_latest_outing_constraint(current_data, day_numbers, change.requested_time)

    if not change.day_number:
        raise ValueError("Hãy nêu rõ ngày cần chỉnh sửa.")
    scheduled, hotel = _scheduled_day_from_json(current_data, change.day_number)
    if not scheduled:
        raise ValueError(f"Không có hoạt động hợp lệ ở ngày {change.day_number}.")
    target_index = (change.order_index or 1) - 1
    if target_index < 0 or target_index >= len(scheduled):
        raise ValueError("Số thứ tự hoạt động cần chỉnh sửa không hợp lệ.")

    adjustments = []
    protected_reference_id = None
    if change.action == "reschedule":
        if not change.requested_time:
            raise ValueError("Hãy cung cấp giờ mới theo dạng HH:MM.")
        target = scheduled[target_index]
        new_time = change.requested_time if len(change.requested_time) > 5 else f"{change.requested_time}:00"
        scheduled[target_index] = ScheduledItem.from_candidate(
            target.day_number,
            target.order_index,
            PlaceCandidate(
                id=target.reference_id,
                name=target.place_name,
                category=target.category,
                coordinates=target.coordinates,
                opening_time=target.opening_time,
                closing_time=target.closing_time,
                estimated_duration_minutes=target.duration_minutes,
            ),
            target.kind,
            new_time,
            target.duration_minutes,
        )
    elif change.action == "remove_place":
        removed = scheduled.pop(target_index)
        adjustments.append(f"Đã bỏ {removed.place_name} khỏi ngày {change.day_number}.")
        if len(scheduled) < 7:
            fallback_start = scheduled[-1].end_time if scheduled else "08:00:00"
            scheduled.append(
                ScheduledItem.from_candidate(
                    change.day_number,
                    len(scheduled) + 1,
                    hotel,
                    "rest",
                    fallback_start,
                    60,
                )
            )
            adjustments.append("Đã thêm thời gian nghỉ tại khách sạn để giữ nhịp lịch cân bằng.")
    else:
        destination_id = str(current_data.get("hotel", {}).get("destination_id") or "")
        if not destination_id:
            raise ValueError("Thiếu mã điểm đến để tìm địa điểm thay thế.")
        constraints = dict(_itinerary_record(current_data).get("planning_constraints") or current_data.get("planning_constraints") or {})
        active_radius_km = constraints.get("semantic_search_radius_km")
        active_lat, active_lon = (None, None)
        if active_radius_km is not None and hotel and hotel.coordinate_pair:
            active_lat, active_lon = hotel.coordinate_pair
            active_radius_km = float(active_radius_km)

        candidates = _search_attraction_candidates(
            change.query or modification_request,
            destination_id,
            match_count=15,
            root_latitude=active_lat,
            root_longitude=active_lon,
            max_radius_km=active_radius_km,
        )
        used_ids = {item.reference_id for item in scheduled}
        target = scheduled[target_index]
        anchor_coordinates = target.coordinates or hotel.coordinate_pair
        candidates = [candidate for candidate in candidates if candidate.id not in used_ids]
        if not candidates:
            raise ValueError("Không tìm thấy địa điểm thật phù hợp để áp dụng thay đổi.")
        candidates.sort(
            key=lambda candidate: (
                -candidate.similarity,
                haversine_distance_km(anchor_coordinates, candidate.coordinate_pair),
            )
        )
        start_time = change.requested_time or target.start_time
        if len(start_time) == 5:
            start_time += ":00"
        candidate = next(
            (
                value
                for value in candidates
                if fits_opening_hours(value, start_time, default_duration_minutes(value, target.kind))
            ),
            None,
        )
        if not candidate:
            raise ValueError("Các địa điểm tìm được đều đóng cửa vào thời gian yêu cầu.")
        replacement = ScheduledItem.from_candidate(
            change.day_number,
            target.order_index,
            candidate,
            target.kind if change.action == "replace_place" else "attraction",
            start_time,
        )
        if change.action == "add_place":
            scheduled.append(replacement)
        else:
            scheduled[target_index] = replacement
        protected_reference_id = candidate.id
        adjustments.append(f"Đã chọn địa điểm thật {candidate.name} và kiểm tra lại lịch ngày.")

    _, _, people, preferences = _current_trip_parameters(current_data)
    child_context = f"{people} {preferences}".casefold()
    child_focused = any(
        keyword in child_context
        for keyword in ("trẻ em", "tre em", "children", "child", "kids", "gia đình", "gia dinh")
    )
    outside_playgrounds = sum(
        1
        for item in current_data.get("itinerary_items", [])
        if int(item.get("day_number") or 0) != change.day_number
        and any(
            keyword in str(item.get("activity") or "").casefold()
            for keyword in ("playground", "trẻ em", "khu vui chơi trẻ em")
        )
    )
    playground_allowance = 1 if child_focused else max(0, 1 - outside_playgrounds)
    repaired, repair_adjustments = validate_or_repair_day(
        scheduled,
        hotel,
        child_focused=child_focused,
        playground_allowance=playground_allowance,
    )
    while len(repaired) > 8:
        removable_index = next(
            (
                index
                for index, item in enumerate(repaired)
                if item.kind == "rest" and item.reference_id != protected_reference_id
            ),
            len(repaired) - 1,
        )
        removed = repaired.pop(removable_index)
        adjustments.append(f"Đã bỏ {removed.activity} để giữ tối đa 8 điểm trong ngày.")
    repaired = [replace(item, order_index=index) for index, item in enumerate(repaired, start=1)]
    _replace_day_in_json(current_data, change.day_number, repaired)
    constraint_adjustments = _reapply_planning_constraints(
        current_data, only_days=(change.day_number,)
    )
    return [*adjustments, *repair_adjustments, *constraint_adjustments]


def parse_duration_to_days(duration_str: str) -> int:
    """Parse Vietnamese duration string (e.g. '1 tuần', '2 ngày', '1 tháng', 'một tuần') into integer days."""
    if not duration_str:
        return 3
        
    s = duration_str.lower().strip()
    
    if "tuần" in s or "tuan" in s:
        if "hai" in s or "2" in s: return 14
        if "ba" in s or "3" in s: return 21
        digits = [int(word) for word in s.replace("-", " ").split() if word.isdigit()]
        if digits and digits[0] > 0: return digits[0] * 7
        return 7
        
    if "tháng" in s or "thang" in s:
        if "hai" in s or "2" in s: return 60
        digits = [int(word) for word in s.replace("-", " ").split() if word.isdigit()]
        if digits and digits[0] > 0: return digits[0] * 30
        return 30
        
    if "ngày" in s or "ngay" in s:
        if "một" in s or "mot" in s: return 1
        if "hai" in s: return 2
        if "ba" in s: return 3
        if "bốn" in s or "bon" in s: return 4
        if "năm" in s or "nam" in s: return 5
        digits = [int(word) for word in s.replace("-", " ").split() if word.isdigit()]
        if digits and digits[0] > 0: return digits[0]
        
    digits = [int(word) for word in s.replace("-", " ").split() if word.isdigit()]
    if digits and digits[0] > 0:
        return digits[0]
        
    return 3


def build_natural_activity_string(name: str, category: str = "") -> str:
    """Format activity text naturally in Vietnamese based on attraction name and category."""
    if not name:
        return "Tham quan điểm du lịch"
        
    s = name.strip()
    s_lower = s.lower()
    cat_lower = (category or "").lower()
    
    for verb in ["tham quan", "trải nghiệm", "vui chơi", "thưởng thức", "khám phá", "ghé", "dạo"]:
        if s_lower.startswith(verb):
            return s
            
    if any(k in s_lower for k in ["lặn biển", "tắm biển", "chèo sup", "tour", "camp", "diving", "surfing", "chèo thuyền"]):
        return f"Trải nghiệm {s}"
    elif any(k in s_lower for k in ["coffee", "cà phê", "quán", "nhà hàng", "quán ăn", "ẩm thực"]) or "food" in cat_lower or "drink" in cat_lower:
        return f"Ghé {s}"
    elif any(k in s_lower for k in ["chợ", "phố"]):
        return f"Dạo {s}"
    elif any(k in s_lower for k in ["đảo", "vịnh", "núi", "hang"]):
        return f"Khám phá {s}"
    else:
        return f"Tham quan {s}"


def format_trip_response_from_json(trip_data: Dict[str, Any]) -> str:
    """Format structured trip JSON into concise user text response."""
    hotel = trip_data.get("hotel", {})
    itineraries = trip_data.get("itineraries", [])
    if isinstance(itineraries, dict):
        itineraries = [itineraries]
    itinerary_items = trip_data.get("itinerary_items", [])
    
    output = []
    
    hotel_name = hotel.get("name", "Khách sạn chưa xác định")
    star_rating = hotel.get("star_rating")
    stars_str = f" ({star_rating} sao)" if star_rating else ""
    description = hotel.get("description", "")
    
    matched_rooms = (hotel.get("matched_rooms") or hotel.get("matched_room_names") or [])[:2]
    rooms_str = f" | Phòng gợi ý: {', '.join(matched_rooms)}" if matched_rooms else ""
    
    output.append(f"Hotel: {hotel_name}{stars_str}{rooms_str}")
    if description:
        output.append(f"Tóm tắt: {description}")
    output.append("------")
    
    day_themes: Dict[int, str] = {}
    stored_day_themes = []
    if itineraries and isinstance(itineraries[0], dict):
        stored_day_themes = itineraries[0].get("day_themes", [])
    raw_day_themes = [theme for theme in (stored_day_themes or []) if isinstance(theme, dict)]
    if any(theme.get("query") for theme in raw_day_themes):
        theme_day_numbers = [
            int(theme["day_number"])
            for theme in raw_day_themes
            if str(theme.get("day_number") or "").isdigit()
        ]
        normalized_themes = normalize_day_themes(
            raw_day_themes,
            max(theme_day_numbers, default=1),
        )
        for theme in normalized_themes:
            day_themes[theme.day_number] = theme.title
    for theme in raw_day_themes:
        if theme.get("query"):
            continue
        if isinstance(theme, dict) and theme.get("day_number") and theme.get("title"):
            day_themes[int(theme["day_number"])] = str(theme["title"])
    for itin in itineraries:
        if isinstance(itin, dict):
            d_num = itin.get("day_number", 1)
            title = itin.get("title") or itin.get("description")
            if title:
                day_themes[d_num] = title
                
    items_by_day: Dict[int, List[Dict[str, Any]]] = {}
    for item in itinerary_items:
        day = item.get("day_number") or item.get("day", 1)
        if day not in items_by_day:
            items_by_day[day] = []
        items_by_day[day].append(item)
    
    duration_days = len(itineraries) if itineraries and len(itineraries) > 1 else 1
    if itineraries and isinstance(itineraries[0], dict) and "duration_days" in itineraries[0]:
        duration_days = itineraries[0].get("duration_days", 1)
        
    max_days = max(duration_days, max(items_by_day.keys()) if items_by_day else 1)
    
    for day_num in range(1, max_days + 1):
        theme_suffix = f" - {day_themes[day_num]}" if day_num in day_themes else ""
        output.append(f"Ngày {day_num}{theme_suffix}:")
        
        day_items = sorted(items_by_day.get(day_num, []), key=lambda x: x.get("order_index", 1))
        if day_items:
            for item in day_items:
                start_time = item.get("start_time") or item.get("time", "08:00:00")
                end_time = item.get("end_time")
                start_text = start_time[:5] if len(start_time) >= 5 else start_time
                end_text = end_time[:5] if isinstance(end_time, str) and len(end_time) >= 5 else None
                time_str = f"{start_text}-{end_text}" if end_text else start_text
                activity = item.get("activity") or item.get("name") or "Tham quan điểm du lịch"
                output.append(f"{time_str} - {activity}")
        else:
            output.append("Chưa có hoạt động hợp lệ cho ngày này.")
        output.append("------")

    adjustments = [str(value) for value in trip_data.get("adjustments", []) if value]
    if adjustments:
        output.append("Điều chỉnh tự động:")
        output.extend(f"- {adjustment}" for adjustment in adjustments)

    return "\n".join(output)


def format_hotel_options(options: List[tuple[Dict[str, Any], PlaceCandidate]]) -> str:
    """Render a ranked hotel candidate list as numbered Vietnamese chat text."""
    if not options:
        return "Không tìm thấy khách sạn phù hợp. Bạn thử mô tả khác hoặc đổi điểm đến xem sao."

    lines = ["Mình tìm được vài khách sạn phù hợp, bạn chọn giúp mình nhé:", "------"]
    for data, _candidate in options:
        rank = data.get("rank", "?")
        name = data.get("name") or "Khách sạn chưa xác định"
        star_rating = data.get("star_rating")
        stars_str = f" ({star_rating} sao)" if star_rating else ""

        review_score = data.get("review_score")
        review_count = data.get("review_count")
        review_str = ""
        if review_score:
            review_str = f" | Đánh giá: {review_score}/10"
            if review_count:
                review_str += f" ({review_count} lượt)"

        lowest_price = data.get("lowest_price")
        price_str = ""
        if lowest_price is not None:
            currency = data.get("currency") or "VND"
            try:
                price_str = f" | Giá từ: {float(lowest_price):,.0f} {currency}"
            except (TypeError, ValueError):
                price_str = f" | Giá từ: {lowest_price} {currency}"

        lines.append(f"{rank}. {name}{stars_str}{review_str}{price_str}")

        description = data.get("description")
        if description:
            lines.append(f"   {description}")

        matched_rooms = (data.get("matched_rooms") or [])[:2]
        if matched_rooms:
            lines.append(f"   Phòng gợi ý: {', '.join(matched_rooms)}")

        covered_meals = data.get("covered_meals") or []
        if covered_meals:
            lines.append(f"   Bữa ăn đã bao gồm: {', '.join(covered_meals)}")

        lines.append("------")

    lines.append("Trả lời bằng số thứ tự hoặc tên khách sạn để chọn.")
    return "\n".join(lines)
