"""Service module for data hydration, candidate retrieval, theme generation, and trip plan mutations."""

from __future__ import annotations
import unicodedata

import json
import logging
import os
import re
import uuid
from collections.abc import Callable, Collection
from copy import deepcopy
from dataclasses import replace
from datetime import datetime
from functools import lru_cache
from typing import Any, Mapping, Sequence

from src.api.streaming import emit_phase
from src.config import get_settings
from src.i18n import t
from src.services.hotel_selection import (
    _parse_free_text_price,
    fetch_hotel_by_id,
    rank_hotel_candidates,
    select_hotel_candidates,
)
from src.services.itinerary_reuse import (
    ItineraryReuseQuery,
    ItineraryTemplate,
    classify_reuse_candidate,
    validate_template_bundle,
)
from src.services.itinerary_store import ItineraryStore, ItineraryStoreError
from src.services.llm import get_reasoning_llm as get_llm
from src.services.supabase_search import (
    search_attractions as rpc_search_attractions,
    search_attractions_tiered as rpc_search_attractions_tiered,
)
from src.services.trip_edit_planner import EditOperation, NewItemRequirements, TripEditPlan
from src.services.trip_formatter import format_hotel_options, format_trip_response_from_json, parse_duration_to_days
from src.services.trip_intake import (
    DestinationOption,
    destination_options_from_rows,
)
from src.services.trip_scheduler import (
    DayTheme,
    PlaceCandidate,
    ScheduledItem,
    TripChange,
    apply_latest_outing_start,
    build_itinerary,
    build_itinerary_with_hotel_reselection,
    default_duration_minutes,
    fits_opening_hours,
    haversine_distance_km,
    normalize_day_themes,
    serialize_day_themes,
    validate_or_repair_day,
)
from supabase import Client, create_client

logger = logging.getLogger(__name__)

SESSION_DATA_DIR = "data"
CURRENT_TRIP_PLAN_FILE = os.path.join(SESSION_DATA_DIR, "current_trip_plan.json")
PENDING_HOTEL_SELECTION_FILE = os.path.join(SESSION_DATA_DIR, "pending_hotel_selection.json")
ENABLE_ITINERARY_REUSE = os.getenv("ENABLE_ITINERARY_REUSE", "false").casefold() in {"1", "true", "yes"}
ITINERARY_REUSE_TIER1_THRESHOLD = float(os.getenv("ITINERARY_REUSE_TIER1_THRESHOLD", "0.88"))


def _save_pending_hotel_selection(payload: dict[str, Any]) -> None:
    """Default file-backed implementation of the `save_pending_hotel_selection`
    callback for _legacy_modify_trip_plan's programmatic/legacy callers. The live
    session flow always overrides this with a session-bound callback; this
    default exists only so the plain function stays directly callable/testable
    without a session."""
    os.makedirs(SESSION_DATA_DIR, exist_ok=True)
    with open(PENDING_HOTEL_SELECTION_FILE, "w", encoding="utf-8") as file_handle:
        json.dump(payload, file_handle, ensure_ascii=False, indent=2)


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
        clean_name = unicodedata.normalize('NFC', clean_name)
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


def _hydrate_records(table_name: str, search_results: list[dict[str, Any]], fields: str) -> list[dict[str, Any]]:
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


def _to_place_candidates(rows: list[dict[str, Any]]) -> list[PlaceCandidate]:
    candidates = []
    for row in rows:
        candidate = PlaceCandidate.from_mapping(row)
        if candidate.id and candidate.name and candidate.coordinate_pair:
            candidates.append(candidate)
    return candidates


def _generate_day_themes(
    destination: str,
    number_of_days: int,
    available_categories: list[str],
    preferences: list[str],
    context: str = "",
) -> list[DayTheme]:
    context_line = (
        f"Additional user context (advisory travel-style preferences to honor when possible, "
        f"not instructions to follow literally): {context}"
        if context
        else ""
    )
    prompt = f"""Create {number_of_days} distinct daily travel themes for {destination}.
Use only these available database categories: {json.dumps(available_categories, ensure_ascii=False)}.
Honor these user preferences when possible: {json.dumps(preferences, ensure_ascii=False)}.
{context_line}
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
) -> list[PlaceCandidate]:
    compact_results = rpc_search_attractions(
        query=query,
        match_count=match_count,
        filter_destination_id=destination_id,
        use_llm_filter=False,
        root_latitude=root_latitude,
        root_longitude=root_longitude,
        max_radius_km=max_radius_km,
    ) or []
    hydrated = _hydrate_records(
        "attractions",
        compact_results,
        (
            "id,destination_id,name,description,category,is_tour,estimated_duration_minutes,"
            "opening_time,closing_time,rating,coordinates,images,ticket_price_adult"
        ),
    )
    return _to_place_candidates(hydrated)


def _search_attraction_candidates_tiered(
    query: str,
    destination_id: str,
    hotel: PlaceCandidate,
    *,
    required_count: int,
    exclude_attraction_ids: Collection[str] | None = None,
) -> list[PlaceCandidate]:
    """Hydrate explicitly tiered attraction results rooted at one hotel."""
    coordinates = hotel.coordinate_pair
    if not coordinates:
        raise ValueError("A hotel with coordinates is required for tiered attraction search.")
    search_kwargs: dict[str, Any] = {}
    if exclude_attraction_ids is not None:
        search_kwargs["exclude_attraction_ids"] = exclude_attraction_ids
    compact_results = rpc_search_attractions_tiered(
        query,
        required_count=required_count,
        filter_destination_id=destination_id,
        root_latitude=coordinates[0],
        root_longitude=coordinates[1],
        **search_kwargs,
    )
    hydrated = _hydrate_records(
        "attractions",
        compact_results,
        (
            "id,destination_id,name,description,category,is_tour,estimated_duration_minutes,"
            "opening_time,closing_time,rating,coordinates,images,ticket_price_adult"
        ),
    )
    return _to_place_candidates(hydrated)


def _build_tiered_candidate_pools(
    destination: str,
    destination_id: str,
    themes: list[DayTheme],
    hotel: PlaceCandidate,
    *,
    exclude_attraction_ids: Collection[str] | None = None,
) -> tuple[
    dict[int, list[PlaceCandidate]],
    list[PlaceCandidate],
    list[PlaceCandidate],
    list[PlaceCandidate],
    list[PlaceCandidate],
    ]:
    """Fetch final schedule pools from the hotel selected for this itinerary."""
    search_kwargs: dict[str, Any] = {}
    if exclude_attraction_ids is not None:
        search_kwargs["exclude_attraction_ids"] = exclude_attraction_ids
    # A single itinerary needs several non-duplicate places across its days.
    # Three results per theme often overlap with the preceding day's selected
    # places, which leaves a later afternoon slot empty before tiered search
    # can lower its threshold or widen its radius.
    theme_pool_size = max(6, len(themes) + 4)
    themed_candidates = {
        theme.day_number: _search_attraction_candidates_tiered(
            f"{theme.query}. Destination: {destination}",
            destination_id,
            hotel,
            required_count=theme_pool_size,
            **search_kwargs,
        )
        for theme in themes
    }
    # Keep theme matches as the primary source for every day.  If all eligible
    # themed candidates have already been used (or cannot fit the slot's
    # opening-hour/cluster constraints), the scheduler may use this nearby,
    # non-theme pool instead of emitting a local-exploration placeholder.
    nearby_fallbacks = _search_attraction_candidates_tiered(
        f"nearby local attractions landmarks museums parks sightseeing in {destination}",
        destination_id,
        hotel,
        required_count=theme_pool_size,
        **search_kwargs,
    )
    fallback_tier = (
        max(
            (
                candidate.retrieval_tier
                for candidates in themed_candidates.values()
                for candidate in candidates
            ),
            default=4,
        )
        + 1
    )
    for day_number, candidates in themed_candidates.items():
        themed_ids = {candidate.id for candidate in candidates if candidate.id}
        candidates.extend(
            replace(candidate, retrieval_tier=fallback_tier)
            for candidate in nearby_fallbacks
            if candidate.id and candidate.id not in themed_ids
        )
    meal_pool_size = max(len(themes) + 2, 5)
    restaurants = (
        _search_attraction_candidates_tiered(
            f"local restaurant lunch Vietnamese food in {destination}",
            destination_id,
            hotel,
            required_count=meal_pool_size,
            **search_kwargs,
        )
        if "lunch" not in hotel.covered_meals
        else []
    )
    cafes = _search_attraction_candidates_tiered(
        f"coffee shop cafe relaxation in {destination}",
        destination_id,
        hotel,
        required_count=meal_pool_size,
        **search_kwargs,
    )
    breakfasts = (
        _search_attraction_candidates_tiered(
            f"breakfast restaurant cafe morning food in {destination}",
            destination_id,
            hotel,
            required_count=meal_pool_size,
            **search_kwargs,
        )
        if "breakfast" not in hotel.covered_meals
        else []
    )
    dinners = (
        _search_attraction_candidates_tiered(
            f"dinner restaurant evening dining in {destination}",
            destination_id,
            hotel,
            required_count=meal_pool_size,
            **search_kwargs,
        )
        if "dinner" not in hotel.covered_meals
        else []
    )
    return themed_candidates, restaurants, cafes, breakfasts, dinners


def _select_real_hotel(
    destination: str,
    destination_id: str,
    people: str,
    hotel_query: str | None = None,
) -> list[tuple[dict[str, Any], PlaceCandidate]]:
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
    number_of_adults: int = 1,
) -> dict[str, Any]:
    estimated_cost = None
    if item.ticket_price_adult is not None:
        try:
            estimated_cost = round(float(item.ticket_price_adult) * max(1, int(number_of_adults)), 2)
        except (TypeError, ValueError):
            estimated_cost = None
    return {
        "id": str(uuid.uuid4()),
        "itinerary_id": itinerary_id,
        "day_number": item.day_number,
        "order_index": item.order_index,
        "start_time": item.start_time,
        "end_time": item.end_time,
        "reference_type": item.reference_type,
        "reference_id": item.reference_id,
        "estimated_cost": estimated_cost,
        "created_at": timestamp,
        "updated_at": timestamp,
        "activity": item.activity,
        "kind": item.kind,
        "item_kind": item.kind,
        "coordinates": item.coordinates,
        "image_url": item.image_url,
    }


def _calculate_trip_budget(hotel: Mapping[str, Any], items: Sequence[Mapping[str, Any]]) -> float | None:
    """Return the known trip total without inventing meal or missing activity prices."""
    total = 0.0
    has_known_cost = False

    hotel_total = hotel.get("total_stay_price")
    if hotel_total is None:
        nightly = hotel.get("average_nightly_price", hotel.get("lowest_price"))
        nights = hotel.get("stay_night_count")
        if nightly is not None and nights is not None:
            try:
                hotel_total = float(nightly) * max(0, int(nights))
            except (TypeError, ValueError):
                hotel_total = None
    if hotel_total is not None:
        try:
            total += max(0.0, float(hotel_total))
            has_known_cost = True
        except (TypeError, ValueError):
            pass

    for item in items:
        try:
            cost = item.get("estimated_cost")
        except AttributeError:
            continue
        if cost is None:
            continue
        try:
            total += max(0.0, float(cost))
            has_known_cost = True
        except (TypeError, ValueError):
            continue

    return round(total, 2) if has_known_cost else None


def _persist_itinerary_metadata(trip_data: dict[str, Any]) -> None:
    """Persist a complete bundle, falling back only for an unapplied migration."""
    itineraries = trip_data.get("itineraries") or []
    itinerary = itineraries[0] if isinstance(itineraries, list) else itineraries
    if not isinstance(itinerary, dict) or not itinerary.get("id"):
        return
    # Emitted right before the FIRST external write (sessions.upsert below) —
    # this is also the point-of-no-return anchor for Phase 4 cancellation: a
    # key placed any earlier (before the guard) would sometimes fire without
    # any write happening at all.
    emit_phase("persisting")
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
            "start_date",
            "end_date",
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
    themes_override: list[dict[str, Any]] | None = None,
    preselected_hotel: dict[str, Any] | None = None,
    planning_constraints: dict[str, Any] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    session_id: str = "poc_trip_planner_1",
    intake_context: str = "",
    language: str = "vi",
    exclude_attraction_ids: Collection[str] | None = None,
) -> dict[str, Any]:
    destination_id = _get_destination_id(destination)
    if not destination_id:
        raise ValueError(t("Không tìm thấy dữ liệu điểm đến cho {destination}.", language, destination=destination))
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
            raise ValueError(t("Khách sạn đã chọn thiếu tọa độ hợp lệ; không thể lập lịch trình.", language))
        hotel_options = [(preselected_hotel, preselected_candidate)]
    else:
        hotel_options = _select_real_hotel(destination, destination_id, people, hotel_query)
        if not hotel_options:
            raise ValueError(
                t(
                    "Không tìm thấy khách sạn có tọa độ hợp lệ tại {destination}; không thể lập lịch trình theo vị trí khách sạn.",
                    language,
                    destination=destination,
                )
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
        themes = _generate_day_themes(destination, number_of_days, categories, preferences, context=intake_context)

    if preselected_hotel is not None:
        hotel_candidate = hotel_candidates[0]
    else:
        # Keep the established broad semantic pass only for choosing a viable
        # hotel. The itinerary shown to the user is rebuilt from GPS-rooted
        # pools after this selection completes.
        themed_candidates = {
            theme.day_number: _search_attraction_candidates(
                f"{theme.query}. Destination: {destination}",
                destination_id,
                match_count=20,
            )
            for theme in themes
        }
        pool_size = min(max(number_of_days * 3, 15), 50)
        restaurants = (
            _search_attraction_candidates(
                f"local restaurant lunch Vietnamese food in {destination}",
                destination_id,
                match_count=pool_size,
            )
            if any("lunch" not in hotel.covered_meals for hotel in hotel_candidates)
            else []
        )
        cafes = _search_attraction_candidates(
            f"coffee shop cafe relaxation in {destination}",
            destination_id,
            match_count=pool_size,
        )
        breakfasts = (
            _search_attraction_candidates(
                f"breakfast restaurant cafe morning food in {destination}",
                destination_id,
                match_count=pool_size,
            )
            if any("breakfast" not in hotel.covered_meals for hotel in hotel_candidates)
            else []
        )
        dinners = (
            _search_attraction_candidates(
                f"dinner restaurant evening dining in {destination}",
                destination_id,
                match_count=pool_size,
            )
            if any("dinner" not in hotel.covered_meals for hotel in hotel_candidates)
            else []
        )
        hotel_candidate, _ = build_itinerary_with_hotel_reselection(
            hotel_candidates,
            themes,
            themed_candidates,
            restaurants,
            cafes,
            breakfasts=breakfasts,
            dinners=dinners,
            child_focused=child_focused,
        )

    pool_kwargs: dict[str, Any] = {}
    if exclude_attraction_ids is not None:
        pool_kwargs["exclude_attraction_ids"] = exclude_attraction_ids
    (
        themed_candidates,
        restaurants,
        cafes,
        breakfasts,
        dinners,
    ) = _build_tiered_candidate_pools(
        destination,
        destination_id,
        themes,
        hotel_candidate,
        **pool_kwargs,
    )
    schedule = build_itinerary(
        hotel_candidate,
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
        "session_id": session_id,
        "duration_days": number_of_days,
        "start_date": start_date,
        "end_date": end_date,
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
    serialized_items = [
        _serialize_schedule_item(item, itinerary_id, now_iso, number_of_people) for item in schedule.items
    ]
    itinerary_record["budget"] = _calculate_trip_budget(hotel_data, serialized_items)
    return {
        "hotel": hotel_data,
        "itineraries": [itinerary_record],
        "itinerary_items": serialized_items,
        "adjustments": [
            *schedule.adjustments,
            *(["Đã dùng chủ đề từ lịch trình tương tự và lập lại lịch mới theo dữ liệu hiện tại."] if reusable_template else []),
        ],
    }


def _save_trip_data(trip_data: dict[str, Any], *, persist: bool = True) -> None:
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


def _current_trip_parameters(current_data: dict[str, Any]) -> tuple[str, str, str, str]:
    itineraries = current_data.get("itineraries") or [{}]
    itinerary = itineraries[0] if isinstance(itineraries, list) else itineraries
    preferences = list(itinerary.get("preferences") or [])
    destination = str(preferences[0]) if preferences else ""
    duration = f"{int(itinerary.get('duration_days') or 1)} ngày"
    people = f"{int(itinerary.get('number_of_adults') or 1)} người"
    preference_text = ", ".join(str(value) for value in preferences[1:])
    return destination, duration, people, preference_text


def _apply_latest_outing_constraint(
    current_data: dict[str, Any],
    day_numbers: tuple[int, ...],
    cutoff: str,
) -> list[str]:
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
    current_data: dict[str, Any],
    *,
    only_days: tuple[int, ...] | None = None,
) -> list[str]:
    itinerary_rows = current_data.get("itineraries") or [{}]
    itinerary = itinerary_rows[0] if isinstance(itinerary_rows, list) else itinerary_rows
    if not isinstance(itinerary, dict):
        return []
    planning_constraints = itinerary.get("planning_constraints") or {}
    cutoff_by_day = planning_constraints.get(
        "latest_outing_start_by_day"
    ) or {}
    selected_days = set(only_days or ())
    grouped: dict[str, list[int]] = {}
    for day_text, cutoff in cutoff_by_day.items():
        try:
            day_number = int(day_text)
        except (TypeError, ValueError):
            continue
        if selected_days and day_number not in selected_days:
            continue
        grouped.setdefault(str(cutoff), []).append(day_number)

    adjustments: list[str] = []
    for cutoff, days in grouped.items():
        adjustments.extend(
            _apply_latest_outing_constraint(current_data, tuple(sorted(days)), cutoff)
        )
    end_cutoff_by_day = planning_constraints.get("latest_outing_end_by_day") or {}
    end_grouped: dict[str, list[int]] = {}
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


def _itinerary_record(current_data: dict[str, Any]) -> dict[str, Any]:
    rows = current_data.get("itineraries") or [{}]
    itinerary = rows[0] if isinstance(rows, list) else rows
    if not isinstance(itinerary, dict):
        raise ValueError("Kế hoạch hiện tại không có bản ghi lịch trình hợp lệ.")
    return itinerary


def _clock_minutes(value: str) -> int:
    hour_text, minute_text, *_ = value.split(":")
    return int(hour_text) * 60 + int(minute_text)


def _renumber_items(current_data: dict[str, Any], day_numbers: tuple[int, ...] | None = None) -> None:
    selected_days = set(day_numbers or ())
    items = sorted(
        current_data.get("itinerary_items") or [],
        key=lambda item: (int(item.get("day_number") or 0), str(item.get("start_time") or ""), int(item.get("order_index") or 0)),
    )
    counts: dict[int, int] = {}
    for item in items:
        day = int(item.get("day_number") or 0)
        if not selected_days or day in selected_days:
            counts[day] = counts.get(day, 0) + 1
            item["order_index"] = counts[day]
    current_data["itinerary_items"] = items


def _remove_item_by_id(current_data: dict[str, Any], item_id: str) -> dict[str, Any]:
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


def _close_gap_after_removal(current_data: dict[str, Any], removed: dict[str, Any]) -> None:
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
    current_data: dict[str, Any],
    operation: EditOperation,
) -> list[str]:
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
    current_data: dict[str, Any],
    day_numbers: tuple[int, ...],
    cutoff: str,
) -> list[str]:
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


def _apply_schedule_policy(current_data: dict[str, Any], operation: EditOperation) -> list[str]:
    itinerary = _itinerary_record(current_data)
    duration_days = int(itinerary.get("duration_days") or 1)
    days = operation.day_numbers or ((operation.day_number,) if operation.day_number else tuple(range(1, duration_days + 1)))
    constraints = dict(itinerary.get("planning_constraints") or {})
    adjustments: list[str] = []
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


def _child_focused_trip(current_data: dict[str, Any]) -> bool:
    _, _, people, preferences = _current_trip_parameters(current_data)
    text = f"{people} {preferences}".casefold()
    return any(keyword in text for keyword in ("trẻ em", "tre em", "children", "child", "kids", "gia đình", "gia dinh"))


def _replace_scheduled_day(current_data: dict[str, Any], day_number: int, scheduled: list[ScheduledItem]) -> list[str]:
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
    scheduled: list[ScheduledItem],
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
    current_data: dict[str, Any],
    scheduled: list[ScheduledItem],
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
        
    anchor = _candidate_anchor(scheduled, hotel, target, requirements)
    max_radius = 5.0 if requirements.item_kind == "breakfast" else 15.0
    
    candidates = _search_attraction_candidates(
        requirements.semantic_query, 
        destination_id, 
        match_count=40,
        root_latitude=anchor[0] if anchor else None,
        root_longitude=anchor[1] if anchor else None,
        max_radius_km=max_radius if anchor else None,
    )
    used_ids = {item.reference_id for item in scheduled}
    
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
        nearby: list[PlaceCandidate] = []
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


def _scheduled_target(scheduled: list[ScheduledItem], target_id: str, current_data: dict[str, Any]) -> tuple[int, ScheduledItem]:
    raw = next((item for item in current_data.get("itinerary_items") or [] if str(item.get("id")) == target_id), None)
    if raw is None:
        raise ValueError("Không tìm thấy hoạt động cần chỉnh sửa.")
    order_index = int(raw.get("order_index") or 0)
    for index, item in enumerate(scheduled):
        if item.order_index == order_index:
            return index, item
    raise ValueError("Không thể đọc hoạt động cần chỉnh sửa.")


def _apply_replace_or_add(current_data: dict[str, Any], operation: EditOperation) -> list[str]:
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


def _apply_time_update(current_data: dict[str, Any], operation: EditOperation) -> list[str]:
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


def _alternative_theme(current_data: dict[str, Any], day_number: int) -> dict[str, str]:
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


def _apply_day_replan(current_data: dict[str, Any], operation: EditOperation) -> list[str]:
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
        exclude_attraction_ids=_scheduled_attraction_ids(current_data),
    )
    rebuilt_scheduled, _hotel = _scheduled_day_from_json(rebuilt, operation.day_number)
    _replace_day_in_json(current_data, operation.day_number, rebuilt_scheduled)
    itinerary["day_themes"] = themes
    _reapply_planning_constraints(current_data, only_days=(operation.day_number,))
    return [f"Đã lập lại ngày {operation.day_number} theo chủ đề {title}."]


def apply_trip_edit_plan(current_data: dict[str, Any], plan: TripEditPlan) -> list[str]:
    """Apply a validated edit plan atomically to an in-memory trip bundle."""
    if plan.decision != "apply":
        raise ValueError("Chỉ kế hoạch chỉnh sửa đã được phê duyệt mới có thể áp dụng.")
    working = deepcopy(current_data)
    adjustments: list[str] = []
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
    itinerary["budget"] = _calculate_trip_budget(
        dict(working.get("hotel") or {}),
        list(working.get("itinerary_items") or []),
    )
    itinerary["status"] = "Draft"
    itinerary["updated_at"] = datetime.now().isoformat()
    itinerary.pop("summary", None)
    current_data.clear()
    current_data.update(working)
    return adjustments


def resolve_trip_edit_request(
    trip_data: dict[str, Any] | None,
    modification_request: str,
    plan: TripEditPlan,
    language: str = "vi",
) -> tuple[str | None, dict[str, Any]]:
    """Pure core of executing an already-validated LLM edit plan against a
    saved Draft: reads only `trip_data`, returns `(reply_or_None, updates)`
    instead of mutating a session in place.

    Moved here (Phase 4, 260802-1437-langgraph-full-orchestration-and-
    durable-state) from `src.agents.session.execute_trip_edit_request` so the
    `modify_trip_plan` tool can call it without importing `TripSession` --
    `src.agents.session` keeps a thin same-signature wrapper around this
    function for `_run_edit_draft` and the many existing tests that
    monkeypatch `session_module.execute_trip_edit_request` directly.
    """
    if trip_data is None:
        return t("SYSTEM ERROR: Chưa có kế hoạch chuyến đi để chỉnh sửa.", language), {}
    current_data = trip_data

    saved_itinerary = (current_data.get("itineraries") or [{}])[0]
    if isinstance(saved_itinerary, dict) and str(saved_itinerary.get("status") or "").casefold() == "finalized":
        return (
            t("Kế hoạch đã xác nhận không thể chỉnh sửa. Hãy tạo một kế hoạch mới nếu cần thay đổi.", language),
            {},
        )
    if plan.decision == "clarify":
        return plan.clarification_question or t("Bạn muốn chỉnh sửa phần nào của lịch trình?", language), {}
    if plan.decision == "not_edit":
        return None, {}

    hotel_change = next((operation for operation in plan.operations if operation.operation == "change_hotel"), None)
    if hotel_change:
        try:
            destination, duration, people, preferences = _current_trip_parameters(current_data)
            destination_id = str(saved_itinerary.get("destination_id") or _get_destination_id(destination) or "")
            if not destination or not destination_id:
                raise ValueError("Kế hoạch hiện tại thiếu điểm đến để đổi khách sạn.")
            hotel_query = hotel_change.hotel_query or modification_request
            archived_options = current_data.get("hotel_selection_options")
            if isinstance(archived_options, Mapping) and archived_options.get("options"):
                pending_payload = deepcopy(dict(archived_options))
                pending_payload.update(
                    {
                        "mode": "change_hotel",
                        "destination": destination,
                        "destination_id": destination_id,
                        "duration": duration,
                        "people": people,
                        "preferences_text": preferences,
                        "hotel_query": hotel_query,
                        "planning_constraints": dict(saved_itinerary.get("planning_constraints") or {}),
                        "created_at": datetime.now().isoformat(),
                    }
                )
                return (
                    t(
                        "Mình đã giữ lại danh sách khách sạn trước đó. Bạn hãy chọn khách sạn khác trong tab Khách sạn nhé!",
                        language,
                    ),
                    {"pending_hotel_selection": pending_payload},
                )
            options = rank_hotel_candidates(
                select_hotel_candidates(destination, destination_id, people, hotel_query=hotel_query)
            )
            if not options:
                raise ValueError(f"Không tìm thấy khách sạn phù hợp tại {destination}.")
            pending_payload = {
                "mode": "change_hotel",
                "destination": destination,
                "destination_id": destination_id,
                "duration": duration,
                "people": people,
                "preferences_text": preferences,
                "hotel_query": hotel_query,
                "planning_constraints": dict(saved_itinerary.get("planning_constraints") or {}),
                "created_at": datetime.now().isoformat(),
                "options": [data for data, _candidate in options],
            }
            return (
                t(
                    "Mình đã tìm danh sách khách sạn phù hợp. Bạn hãy chọn trong tab Khách sạn nhé!",
                    language,
                ),
                {"pending_hotel_selection": pending_payload},
            )
        except Exception as exc:
            logger.exception("Failed to prepare hotel change")
            return f"SYSTEM ERROR: {exc}", {}

    try:
        adjustments = apply_trip_edit_plan(current_data, plan)
        current_data.setdefault("adjustments", []).extend(adjustments)
        _persist_itinerary_metadata(current_data)
        logger.info("Applied LLM edit plan: %s", [operation.operation for operation in plan.operations])
        reply = "Adjustment applied." if language == "en" else "Điều chỉnh đã áp dụng."
        return reply, {"trip_data": current_data}
    except Exception as exc:
        logger.exception("Failed to apply LLM edit plan")
        return f"SYSTEM ERROR: {exc}", {}


def _item_kind(item: dict[str, Any]) -> str:
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
    current_data: dict[str, Any],
    meal_kind: str,
    *,
    only_days: tuple[int, ...] | None = None,
) -> list[str]:
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
    next_index_by_day: dict[int, int] = {}
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


def _scheduled_attraction_ids(current_data: Mapping[str, Any]) -> list[str]:
    """Return only attraction records already used by the saved itinerary.

    Candidate IDs returned by earlier semantic searches are intentionally not
    represented in ``trip_data`` and therefore are never excluded here.
    """
    result: list[str] = []
    for item in current_data.get("itinerary_items") or []:
        if not isinstance(item, Mapping) or str(item.get("reference_type") or "").casefold() != "attraction":
            continue
        reference_id = str(item.get("reference_id") or "")
        if not reference_id or reference_id in result:
            continue
        result.append(reference_id)
    return result


def _scheduled_day_from_json(current_data: dict[str, Any], day_number: int) -> tuple[list[ScheduledItem], PlaceCandidate]:
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
    attraction_by_id: dict[str, dict[str, Any]] = {}
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
    current_data: dict[str, Any],
    day_number: int,
    scheduled_items: list[ScheduledItem],
) -> None:
    existing = [
        item
        for item in current_data.get("itinerary_items", [])
        if int(item.get("day_number") or 0) == day_number
    ]
    existing_by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in existing:
        existing_by_key.setdefault((str(item.get("reference_id")), _item_kind(item)), []).append(item)
    itinerary_id = str((current_data.get("itineraries") or [{}])[0].get("id"))
    now_iso = datetime.now().isoformat()
    replacements = []
    for scheduled in scheduled_items:
        key = (scheduled.reference_id, scheduled.kind)
        old = existing_by_key.get(key, []).pop(0) if existing_by_key.get(key) else None
        number_of_adults = int((current_data.get("itineraries") or [{}])[0].get("number_of_adults") or 1)
        record = _serialize_schedule_item(scheduled, itinerary_id, now_iso, number_of_adults)
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
    current_data: dict[str, Any],
    change: TripChange,
    modification_request: str,
) -> list[str]:
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
        target = scheduled[target_index]
        anchor_coordinates = target.coordinates or hotel.coordinate_pair
        candidates = _search_attraction_candidates(
            change.query or modification_request,
            destination_id,
            match_count=15,
            root_latitude=anchor_coordinates[0] if anchor_coordinates else None,
            root_longitude=anchor_coordinates[1] if anchor_coordinates else None,
            max_radius_km=15.0 if anchor_coordinates else None,
        )
        used_ids = {item.reference_id for item in scheduled}
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


def generate_full_itinerary(
    destination: str,
    duration: str,
    people: str,
    preferences: str = "",
    *,
    hotel_id: str = "",
    session_id: str = "poc_trip_planner_1",
    save: Callable[[dict[str, Any]], None] | None = None,
    language: str = "vi",
) -> str:
    """Direct/programmatic entry point that generates a trip plan in one shot.

    Plain function, not an agent @tool — it is NOT registered with
    create_react_agent. The conversational flow goes through recommend_hotels
    then select_hotel instead, so the user picks a hotel before the itinerary
    is built; wiring this into the agent would let the LLM bypass that gate.
    If `hotel_id` is given, that exact hotel is used (no search). If empty, a
    hotel is auto-selected (legacy behavior, kept for direct/programmatic callers).

    `save` is an injected callback (e.g. a session-bound `_save_trip_data`) so
    this stays a plain service function with no dependency on agents/ state.
    """
    preselected_hotel = None
    if hotel_id:
        destination_id = _get_destination_id(destination)
        resolved = fetch_hotel_by_id(hotel_id, str(destination_id) if destination_id else None)
        if not resolved:
            return t("SYSTEM ERROR: Không tìm thấy khách sạn với id đã cho tại điểm đến này.", language)
        preselected_hotel, _candidate = resolved

    logger.info(
        "Executing balanced itinerary pipeline for destination=%r, duration=%r, people=%r, hotel_id=%r",
        destination,
        duration,
        people,
        hotel_id,
    )
    return _generate_and_save_itinerary(
        destination,
        duration,
        people,
        preferences,
        preselected_hotel=preselected_hotel,
        session_id=session_id,
        save=save,
        language=language,
    )


def _generate_and_save_itinerary(
    destination: str,
    duration: str,
    people: str,
    preferences: str = "",
    *,
    hotel_query: str | None = None,
    preselected_hotel: dict[str, Any] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    session_id: str = "poc_trip_planner_1",
    intake_context: str = "",
    save: Callable[[dict[str, Any]], None] | None = None,
    language: str = "vi",
) -> str:
    """Shared build/save/format sequence used by generate_full_itinerary and
    the select_hotel tool. `save` defaults to the module's own file-backed
    _save_trip_data for direct/programmatic callers; a session-bound tool
    passes its own session-aware save callback instead."""
    emit_phase("itinerary_build")
    try:
        build_kwargs: dict[str, Any] = {
            "hotel_query": hotel_query,
            "preselected_hotel": preselected_hotel,
            "session_id": session_id,
            "intake_context": intake_context,
            "language": language,
        }
        # Keep direct/legacy callers compatible while the guided date-aware
        # flow always supplies the complete interval.
        if start_date is not None or end_date is not None:
            build_kwargs["start_date"] = start_date
            build_kwargs["end_date"] = end_date
        trip_data = _build_trip_data(
            destination,
            duration,
            people,
            preferences,
            **build_kwargs,
        )
        (save or _save_trip_data)(trip_data)
    except Exception as exc:
        logger.exception("Itinerary generation failed")
        return f"SYSTEM ERROR: {exc}"

    return format_trip_response_from_json(trip_data, language)


def _legacy_modify_trip_plan(
    current_data: dict[str, Any],
    modification_request: str,
    *,
    save: Callable[[dict[str, Any]], None] | None = None,
    save_pending_hotel_selection: Callable[[dict[str, Any]], None] | None = None,
    language: str = "vi",
) -> str:
    """Use this when the user wants to change, modify, or update an existing trip
    plan (e.g. change hotel, edit schedule, swap attractions). Superseded in the
    live conversation flow by modify_trip_plan/plan_trip_edit; kept as a plain,
    directly-callable function for programmatic/legacy callers and its own tests.

    `current_data` is the caller's already-loaded trip bundle (a session's
    trip_data, or a file read by a script) — this function performs no file I/O
    of its own. `save`/`save_pending_hotel_selection` default to the module's
    own file-backed helpers.
    """
    saved_itinerary = (current_data.get("itineraries") or [{}])[0]
    if isinstance(saved_itinerary, dict) and str(saved_itinerary.get("status") or "").casefold() == "finalized":
        return t("Kế hoạch đã xác nhận không thể chỉnh sửa. Hãy tạo một kế hoạch mới nếu cần thay đổi.", language)

    logger.info(f"Modifying trip plan based on request: {modification_request}")
    save = save or _save_trip_data
    save_pending_hotel_selection = save_pending_hotel_selection or _save_pending_hotel_selection
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
            # `change.query` only carries free-text venue wants (from the LLM edit
            # classifier); it has no dedicated price field, so parse a budget number
            # off the raw request with the same deterministic parser the guided
            # budget question uses, rather than hoping the search's own LLM query
            # parser re-discovers it downstream.
            parsed_target_price = _parse_free_text_price(modification_request)
            options = rank_hotel_candidates(
                select_hotel_candidates(
                    destination, destination_id, people, hotel_query=hotel_query, max_price=parsed_target_price
                ),
                target_price=parsed_target_price,
            )
            if not options:
                raise ValueError(f"Không tìm thấy khách sạn phù hợp tại {destination}.")
            save_pending_hotel_selection(
                {
                    "mode": "change_hotel",
                    "destination": destination,
                    "destination_id": destination_id,
                    "duration": duration,
                    "people": people,
                    "preferences_text": preferences,
                    "hotel_query": hotel_query,
                    "planning_constraints": dict(
                        ((current_data.get("itineraries") or [{}])[0]).get(
                            "planning_constraints"
                        )
                        or {}
                    ),
                    "created_at": datetime.now().isoformat(),
                    "options": [data for data, _candidate in options],
                }
            )
            return format_hotel_options(options, language)

        updated_data = current_data
        adjustments = _apply_local_trip_change(updated_data, change, modification_request)
        updated_data.setdefault("adjustments", []).extend(adjustments)
        updated_itinerary = (updated_data.get("itineraries") or [{}])[0]
        if isinstance(updated_itinerary, dict):
            updated_itinerary["status"] = "Draft"
            updated_itinerary.pop("summary", None)
        save(updated_data)
        logger.info("Successfully applied structured trip change: %s", change.action)
    except Exception as exc:
        logger.exception("Failed to apply structured trip modification")
        return f"SYSTEM ERROR: {exc}"

    return format_trip_response_from_json(updated_data, language)

