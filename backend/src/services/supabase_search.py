import unicodedata
import json
import logging
import math
import os
from datetime import date
from functools import lru_cache
from typing import Any, Collection, Dict, List, Optional
from uuid import UUID

import requests
from langchain_core.embeddings import Embeddings
from langchain_ollama import OllamaEmbeddings
from supabase import Client, create_client
from langsmith import traceable

from src.config import get_settings

logger = logging.getLogger(__name__)


class RadiusFilter:
    def __init__(self, root_latitude: float, root_longitude: float, max_radius_km: float):
        self.root_latitude = root_latitude
        self.root_longitude = root_longitude
        self.max_radius_km = max_radius_km


def validate_radius_filter(
    root_latitude: Any = None,
    root_longitude: Any = None,
    max_radius_km: Any = None,
) -> Optional[RadiusFilter]:
    args = [root_latitude, root_longitude, max_radius_km]
    non_nulls = [a for a in args if a is not None]
    if len(non_nulls) == 0:
        return None
    if len(non_nulls) != 3:
        raise ValueError("radius_filter_requires_latitude_longitude_and_radius")

    for val in args:
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            raise ValueError("invalid_parameter_type_for_radius_filter")

    lat = float(root_latitude)
    lon = float(root_longitude)
    rad = float(max_radius_km)

    if not (math.isfinite(lat) and math.isfinite(lon) and math.isfinite(rad)):
        raise ValueError("radius_filter_parameters_must_be_finite")

    if not (-90.0 <= lat <= 90.0):
        raise ValueError("root_latitude_out_of_range")
    if not (-180.0 <= lon <= 180.0):
        raise ValueError("root_longitude_out_of_range")
    if rad < 0.0:
        raise ValueError("max_radius_km_must_be_finite_and_non_negative")

    return RadiusFilter(lat, lon, rad)


def validate_stay_dates(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> tuple[str, str] | None:
    """Validate an exclusive hotel checkout interval before it reaches the RPC."""
    if start_date is None and end_date is None:
        return None
    if not start_date or not end_date:
        raise ValueError("stay_dates_must_be_provided_together")
    try:
        parsed_start = date.fromisoformat(start_date)
        parsed_end = date.fromisoformat(end_date)
    except (TypeError, ValueError) as exc:
        raise ValueError("stay_dates_must_use_iso_format") from exc
    if parsed_end <= parsed_start:
        raise ValueError("end_date_must_be_after_start_date")
    return parsed_start.isoformat(), parsed_end.isoformat()


@lru_cache
def get_supabase_client() -> Client:
    settings = get_settings()
    url = getattr(settings, "supabase_url", None) or os.environ.get("SUPABASE_URL")
    key = getattr(settings, "supabase_service_key", None) or os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise ValueError("Missing SUPABASE_URL or SUPABASE_SERVICE_KEY in environment or settings.")
    return create_client(url, key)


@traceable(name="supabase_rpc", run_type="retriever")
def _execute_rpc(rpc_name: str, params: dict) -> list:
    """Wrapper function to log Supabase RPC calls via LangSmith."""
    supabase = get_supabase_client()
    res = supabase.rpc(rpc_name, params).execute()
    return res.data or []


from src.services.llm import get_embeddings as factory_get_embeddings, get_reasoning_llm as get_llm


@lru_cache
def get_embeddings() -> Embeddings:
    return factory_get_embeddings()


def extract_search_filters(query: str, search_type: str = "hotel", model: Optional[str] = None) -> Dict[str, Any]:
    """Sử dụng LLM (configured via Settings/get_llm) để trích xuất filters từ câu truy vấn."""
    if search_type == "hotel":
        prompt = f"""You are an expert travel search query analyzer for Vietnam tourism.
Analyze the user query and extract filtering criteria for hotel accommodation.
Return ONLY valid JSON (without markdown code blocks or explanations) matching this schema:
{{
  "clean_query": "string - the core semantic concept to search for (e.g., 'giường lớn', 'hồ bơi view biển', 'gần trung tâm'). REMOVE city names, star ratings, and prices from this string!",
  "destination_name": "string or null - city/province name if mentioned (e.g. 'Nha Trang', 'Đà Nẵng', 'Hồ Chí Minh', 'Hà Nội', 'Huế', 'Hội An', 'Điện Bàn')",
  "min_star_rating": "integer or null - minimum star rating 1 to 5 if mentioned (e.g. 4 for '4 sao')",
  "max_price": "number or null - maximum price in VND if mentioned (e.g. 1000000 for 'dưới 1 triệu')"
}}

User query: "{query}"
"""
    else:
        prompt = f"""You are an expert travel search query analyzer for Vietnam tourism.
Analyze the user query and extract filtering criteria for tourist attractions.
Return ONLY valid JSON (without markdown code blocks or explanations) matching this schema:
{{
  "clean_query": "string - the core semantic concept to search for (e.g., 'chơi cho trẻ em', 'chùa linh thiêng', 'biển đẹp'). REMOVE city names and prices from this string!",
  "destination_name": "string or null - city/province name if mentioned (e.g. 'Nha Trang', 'Đà Nẵng', 'Hồ Chí Minh', 'Hà Nội', 'Huế', 'Hội An')",
  "category": "string or null - attraction category if mentioned",
  "max_price": "number or null - maximum ticket price in VND if mentioned"
}}

User query: "{query}"
"""

    try:
        llm = get_llm(model=model, temperature=0.0)
        from langchain_core.messages import HumanMessage, SystemMessage
        response = llm.invoke([
            SystemMessage(content="You analyze travel search queries and return valid JSON only."),
            HumanMessage(content=prompt),
        ])
        content = str(response.content).strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        return json.loads(content.strip())
    except Exception as e:
        logger.warning(f"Filter extraction failed for query '{query}': {e}")

    return {"clean_query": query}


def _get_destination_id_by_name(destination_name: str) -> Optional[str]:
    """Tìm destination_id từ tên thành phố/tỉnh trong Supabase."""
    if not destination_name:
        return None
    try:
        supabase = get_supabase_client()
        destination_name = unicodedata.normalize('NFC', destination_name)
        res = supabase.table("destinations").select("id").ilike("name", f"%{destination_name}%").limit(1).execute()
        if res.data and len(res.data) > 0:
            return res.data[0]["id"]
    except Exception as e:
        logger.warning(f"Error lookup destination_id for '{destination_name}': {e}")
    return None


def search_hotels_with_rooms(
    query: str,
    match_threshold: float = 0.35,
    match_count: int = 10,
    filter_destination_id: Optional[str] = None,
    use_llm_filter: bool = True,
    model: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    exclude_hotel_ids: Collection[str] | None = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    root_latitude: Optional[float] = None,
    root_longitude: Optional[float] = None,
    max_radius_km: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """Tìm kiếm semantic hotels và rooms cùng nhau sử dụng Supabase RPC match_hotels_with_rooms và local Ollama LLM filtering."""
    radius = validate_radius_filter(root_latitude, root_longitude, max_radius_km)
    stay_dates = validate_stay_dates(start_date, end_date)

    supabase = get_supabase_client()
    embeddings = get_embeddings()

    search_query = query
    min_star_rating = None
    resolved_min_price = min_price
    resolved_max_price = max_price

    if use_llm_filter:
        filters = extract_search_filters(query, search_type="hotel", model=model)
        if filters.get("clean_query"):
            search_query = filters["clean_query"]
        if filter_destination_id is None and filters.get("destination_name"):
            filter_destination_id = _get_destination_id_by_name(filters["destination_name"])
        min_star_rating = filters.get("min_star_rating")
        if resolved_max_price is None:
            resolved_max_price = filters.get("max_price")

    query_vector = embeddings.embed_query(search_query)

    fetch_count = match_count * 3 if min_star_rating else match_count
    params: Dict[str, Any] = {
        "query_embedding": query_vector,
        "match_threshold": match_threshold,
        "match_count": fetch_count,
    }
    if filter_destination_id is not None:
        params["filter_destination_id"] = filter_destination_id
    if resolved_min_price is not None:
        params["filter_min_price"] = resolved_min_price
    if resolved_max_price is not None:
        params["filter_max_price"] = resolved_max_price
    valid_excluded_ids: list[str] = []
    if exclude_hotel_ids:
        for hotel_id in exclude_hotel_ids:
            try:
                normalized_id = str(UUID(str(hotel_id)))
            except (TypeError, ValueError, AttributeError):
                logger.warning("Ignoring invalid hotel exclusion ID: %r", hotel_id)
                continue
            if normalized_id not in valid_excluded_ids:
                valid_excluded_ids.append(normalized_id)
        if valid_excluded_ids:
            params["filter_exclude_hotel_ids"] = valid_excluded_ids
    if stay_dates is not None:
        params["filter_start_date"], params["filter_end_date"] = stay_dates
    if radius is not None:
        params["root_latitude"] = radius.root_latitude
        params["root_longitude"] = radius.root_longitude
        params["max_radius_km"] = radius.max_radius_km

    try:
        data = _execute_rpc("match_hotels_with_rooms", params)
    except Exception as exc:
        # Deploying the exclusion-aware RPC can lag behind the backend. Keep the
        # hotel search available against the prior date/radius-aware signature
        # while filtering already-presented hotels locally.
        if not valid_excluded_ids or not _is_missing_exclusion_rpc_signature(exc):
            raise
        fallback_params = params.copy()
        fallback_params.pop("filter_exclude_hotel_ids", None)
        fallback_params["match_count"] = fetch_count + len(valid_excluded_ids)
        logger.warning(
            "match_hotels_with_rooms lacks filter_exclude_hotel_ids; using local exclusion fallback"
        )
        data = _execute_rpc("match_hotels_with_rooms", fallback_params)

    if valid_excluded_ids:
        excluded_id_set = set(valid_excluded_ids)
        data = [hotel for hotel in data if str(hotel.get("id")) not in excluded_id_set]

    if not min_star_rating or min_star_rating <= 0:
        return data[:match_count]

    filtered_data = []
    for h in data:
        star = h.get("star_rating")
        if star is not None and int(star) < int(min_star_rating):
            continue
        filtered_data.append(h)

    if not filtered_data and len(data) > 0:
        logger.info(f"No hotels met strict filters (star>={min_star_rating}). Returning semantic matches.")
        return data[:match_count]

    return filtered_data[:match_count]


def _is_missing_exclusion_rpc_signature(exc: Exception) -> bool:
    """Return whether PostgREST rejected only the newly added exclusion parameter."""
    error_text = str(exc)
    return "PGRST202" in error_text and "filter_exclude_hotel_ids" in error_text


def search_attractions(
    query: str,
    match_threshold: float = 0.4,
    match_count: int = 10,
    filter_destination_id: Optional[str] = None,
    use_llm_filter: bool = True,
    model: Optional[str] = None,
    root_latitude: Optional[float] = None,
    root_longitude: Optional[float] = None,
    max_radius_km: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """Tìm kiếm semantic attractions sử dụng Supabase RPC match_attractions và local Ollama LLM filtering."""
    radius = validate_radius_filter(root_latitude, root_longitude, max_radius_km)

    supabase = get_supabase_client()
    embeddings = get_embeddings()

    search_query = query
    category_filter = None
    max_price = None

    if use_llm_filter:
        filters = extract_search_filters(query, search_type="attraction", model=model)
        if filters.get("clean_query"):
            search_query = filters["clean_query"]
        if filter_destination_id is None and filters.get("destination_name"):
            filter_destination_id = _get_destination_id_by_name(filters["destination_name"])
        category_filter = filters.get("category")
        max_price = filters.get("max_price")

    query_vector = embeddings.embed_query(search_query)

    fetch_count = match_count * 3 if (category_filter or max_price) else match_count
    params: Dict[str, Any] = {
        "query_embedding": query_vector,
        "match_threshold": match_threshold,
        "match_count": fetch_count,
    }
    if filter_destination_id is not None:
        params["filter_destination_id"] = filter_destination_id
    if radius is not None:
        params["root_latitude"] = radius.root_latitude
        params["root_longitude"] = radius.root_longitude
        params["max_radius_km"] = radius.max_radius_km

    data = _execute_rpc("match_attractions", params)

    filtered_data = []
    for a in data:
        if category_filter and category_filter.lower() not in (a.get("category") or "").lower():
            continue
        if max_price is not None and max_price > 0:
            price = a.get("ticket_price_adult")
            if price is not None and float(price) > float(max_price):
                continue
        filtered_data.append(a)

    if not filtered_data and (category_filter or max_price) and len(data) > 0:
        return data[:match_count]

    return filtered_data[:match_count]

