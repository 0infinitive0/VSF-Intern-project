import json
import logging
import os
from functools import lru_cache
from typing import Any, Dict, List, Optional

import requests
from langchain_core.embeddings import Embeddings
from langchain_ollama import OllamaEmbeddings
from supabase import Client, create_client

from src.config import get_settings

logger = logging.getLogger(__name__)


@lru_cache
def get_supabase_client() -> Client:
    settings = get_settings()
    url = getattr(settings, "supabase_url", None) or os.environ.get("SUPABASE_URL")
    key = getattr(settings, "supabase_service_key", None) or os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise ValueError("Missing SUPABASE_URL or SUPABASE_SERVICE_KEY in environment or settings.")
    return create_client(url, key)


from src.services.llm import get_embeddings as factory_get_embeddings, get_llm


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
) -> List[Dict[str, Any]]:
    """Tìm kiếm semantic hotels và rooms cùng nhau sử dụng Supabase RPC match_hotels_with_rooms và local Ollama LLM filtering."""
    supabase = get_supabase_client()
    embeddings = get_embeddings()

    search_query = query
    min_star_rating = None
    max_price = None

    if use_llm_filter:
        filters = extract_search_filters(query, search_type="hotel", model=model)
        if filters.get("clean_query"):
            search_query = filters["clean_query"]
        if filter_destination_id is None and filters.get("destination_name"):
            filter_destination_id = _get_destination_id_by_name(filters["destination_name"])
        min_star_rating = filters.get("min_star_rating")
        max_price = filters.get("max_price")

    query_vector = embeddings.embed_query(search_query)

    fetch_count = match_count * 3 if (min_star_rating or max_price) else match_count
    params: Dict[str, Any] = {
        "query_embedding": query_vector,
        "match_threshold": match_threshold,
        "match_count": fetch_count,
    }
    if filter_destination_id is not None:
        params["filter_destination_id"] = filter_destination_id

    res = supabase.rpc("match_hotels_with_rooms", params).execute()
    data = res.data or []

    filtered_data = []
    for h in data:
        if min_star_rating is not None and min_star_rating > 0:
            star = h.get("star_rating")
            if star is not None and int(star) < int(min_star_rating):
                continue
        if max_price is not None and max_price > 0:
            price = h.get("lowest_price")
            if price is not None and float(price) > float(max_price):
                continue
        filtered_data.append(h)

    if not filtered_data and (min_star_rating or max_price) and len(data) > 0:
        logger.info(f"No hotels met strict filters (star>={min_star_rating}, price<={max_price}). Returning semantic matches.")
        return data[:match_count]

    return filtered_data[:match_count]


def search_attractions(
    query: str,
    match_threshold: float = 0.4,
    match_count: int = 10,
    filter_destination_id: Optional[str] = None,
    use_llm_filter: bool = True,
    model: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Tìm kiếm semantic attractions sử dụng Supabase RPC match_attractions và local Ollama LLM filtering."""
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

    res = supabase.rpc("match_attractions", params).execute()
    data = res.data or []

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
