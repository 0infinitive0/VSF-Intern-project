"""Service module for data hydration, candidate retrieval, theme generation, and trip plan mutations."""

from __future__ import annotations

import json
import logging
import os
import uuid
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
from src.services.trip_scheduler import (
    DayTheme,
    PlaceCandidate,
    ScheduledItem,
    TripChange,
    build_itinerary_with_hotel_reselection,
    default_duration_minutes,
    detect_covered_hotel_meals,
    fits_opening_hours,
    haversine_distance_km,
    infer_trip_change,
    normalize_day_themes,
    serialize_day_themes,
    validate_or_repair_day,
)

logger = logging.getLogger(__name__)

CURRENT_TRIP_PLAN_FILE = "current_trip_plan.json"
PENDING_HOTEL_SELECTION_FILE = "pending_hotel_selection.json"
ENABLE_ITINERARY_REUSE = os.getenv("ENABLE_ITINERARY_REUSE", "false").casefold() in {"1", "true", "yes"}
ITINERARY_REUSE_TIER1_THRESHOLD = float(os.getenv("ITINERARY_REUSE_TIER1_THRESHOLD", "0.88"))


def clear_session_history() -> None:
    """Clear transient current trip plan, pending hotel selections, and working session files."""
    for filename in (
        CURRENT_TRIP_PLAN_FILE,
        PENDING_HOTEL_SELECTION_FILE,
        os.path.join("data", CURRENT_TRIP_PLAN_FILE),
        os.path.join("data", PENDING_HOTEL_SELECTION_FILE),
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


def _search_attraction_candidates(query: str, destination_id: str, match_count: int = 20) -> List[PlaceCandidate]:
    compact_results = rpc_search_attractions(
        query=query,
        match_count=match_count,
        filter_destination_id=destination_id,
        use_llm_filter=False,
    ) or []
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

    themed_candidates: Dict[int, List[PlaceCandidate]] = {}
    for theme in themes:
        themed_candidates[theme.day_number] = _search_attraction_candidates(
            f"{theme.query}. Destination: {destination}",
            destination_id,
            match_count=20,
        )
    pool_size = min(max(number_of_days * 3, 15), 50)
    restaurants = []
    if any("lunch" not in hotel.covered_meals for hotel in hotel_candidates):
        restaurants = _search_attraction_candidates(
            f"local restaurant lunch Vietnamese food in {destination}",
            destination_id,
            match_count=pool_size,
        )
    cafes = _search_attraction_candidates(
        f"coffee shop cafe relaxation in {destination}",
        destination_id,
        match_count=pool_size,
    )
    breakfasts = []
    if any("breakfast" not in hotel.covered_meals for hotel in hotel_candidates):
        breakfasts = _search_attraction_candidates(
            f"breakfast restaurant cafe morning food in {destination}",
            destination_id,
            match_count=pool_size,
        )
    dinners = []
    if any("dinner" not in hotel.covered_meals for hotel in hotel_candidates):
        dinners = _search_attraction_candidates(
            f"dinner restaurant evening dining in {destination}",
            destination_id,
            match_count=pool_size,
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


def _save_trip_data(trip_data: Dict[str, Any]) -> None:
    with open(CURRENT_TRIP_PLAN_FILE, "w", encoding="utf-8") as file_handle:
        json.dump(trip_data, file_handle, ensure_ascii=False, indent=2)
    _persist_itinerary_metadata(trip_data)


def _parse_trip_change(modification_request: str) -> TripChange:
    deterministic = infer_trip_change(modification_request)
    if deterministic:
        return deterministic
    prompt = f"""Classify this Vietnamese trip-plan edit request into one deterministic change.
Request: {modification_request}
Return raw JSON only with this schema:
{{
  "action": "change_hotel|replace_place|reschedule|add_place|remove_place",
  "day_number": 1,
  "order_index": 1,
  "query": "venue or hotel requirements",
  "requested_time": "HH:MM"
}}
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
        if action in {"change_hotel", "replace_place", "reschedule", "add_place", "remove_place"}:
            return TripChange(
                action=action,
                day_number=int(raw["day_number"]) if raw.get("day_number") else None,
                order_index=int(raw["order_index"]) if raw.get("order_index") else None,
                query=str(raw.get("query") or modification_request),
                requested_time=str(raw["requested_time"]) if raw.get("requested_time") else None,
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
        if item.get("reference_type") == "Attraction" and item.get("reference_id")
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
            if not candidate_row:
                continue
            candidate = PlaceCandidate.from_mapping(candidate_row)
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
        candidates = _search_attraction_candidates(
            change.query or modification_request,
            destination_id,
            match_count=15,
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
    return [*adjustments, *repair_adjustments]


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
        output.append(f"Day {day_num}{theme_suffix}:")
        
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
