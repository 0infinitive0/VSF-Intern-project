"""Semantic search for attractions/hotels/rooms backed by Qdrant, replacing the
Supabase pgvector RPC path. Returns `{"id": <supabase_row_id>, ...}` dicts —
the same minimal shape `poc_trip_planner.py`'s `_hydrate_records()` expects,
since it re-fetches canonical fields from Supabase by `id` anyway."""

import logging
from typing import Any, Dict, List, Optional

from qdrant_client.http import models

from src.services.qdrant_schema import ATTRACTIONS_VECTOR, HOTELS_VECTOR, ROOMS_VECTOR
from src.services.supabase_search import extract_search_filters, get_embeddings
from src.services.vector_store import get_qdrant_client

logger = logging.getLogger(__name__)


def _match_filter(field: str, value: Any) -> models.FieldCondition:
    return models.FieldCondition(key=f"metadata.{field}", match=models.MatchValue(value=str(value)))


def _destination_filter(destination_id: Optional[str]) -> Optional[models.Filter]:
    if not destination_id:
        return None
    return models.Filter(must=[_match_filter("destination_id", destination_id)])


def search_attractions(
    query: str,
    match_count: int = 10,
    filter_destination_id: Optional[str] = None,
    use_llm_filter: bool = True,
    model: str = "qwen2.5:7b-instruct",
) -> List[Dict[str, Any]]:
    """Semantic search over `attractions_vector`. Mirrors
    `supabase_search.search_attractions()`'s LLM query-filter step, swaps the
    Supabase RPC retrieval for a Qdrant query."""
    search_query = query
    category_filter = None
    max_price = None

    if use_llm_filter:
        filters = extract_search_filters(query, search_type="attraction", model=model)
        if filters.get("clean_query"):
            search_query = filters["clean_query"]
        if filter_destination_id is None and filters.get("destination_name"):
            from src.services.supabase_search import _get_destination_id_by_name
            filter_destination_id = _get_destination_id_by_name(filters["destination_name"])
        category_filter = filters.get("category")
        max_price = filters.get("max_price")

    query_vector = get_embeddings().embed_query(search_query)
    fetch_count = match_count * 3 if (category_filter or max_price) else match_count

    client = get_qdrant_client()
    response = client.query_points(
        collection_name=ATTRACTIONS_VECTOR.name,
        query=query_vector,
        query_filter=_destination_filter(filter_destination_id),
        limit=fetch_count,
    )

    results = []
    for point in response.points:
        meta = (point.payload or {}).get("metadata", {})
        attraction_id = meta.get("attraction_id")
        if not attraction_id:
            continue
        if category_filter and category_filter.lower() not in (meta.get("category") or "").lower():
            continue
        if max_price is not None and max_price > 0:
            price = meta.get("ticket_price_adult")
            if price is not None and float(price) > float(max_price):
                continue
        results.append({"id": attraction_id, "score": point.score, "category": meta.get("category")})

    return results[:match_count]


def _matched_room_names(client, hotel_id: str, query_vector: List[float], limit: int = 3) -> List[str]:
    response = client.query_points(
        collection_name=ROOMS_VECTOR.name,
        query=query_vector,
        query_filter=models.Filter(must=[_match_filter("hotel_id", hotel_id)]),
        limit=limit,
    )
    names = []
    for point in response.points:
        name = (point.payload or {}).get("metadata", {}).get("name")
        if name:
            names.append(name)
    return names


def search_hotels_with_rooms(
    query: str,
    match_count: int = 10,
    filter_destination_id: Optional[str] = None,
    use_llm_filter: bool = True,
    model: str = "qwen2.5:7b-instruct",
) -> List[Dict[str, Any]]:
    """Semantic search over `hotels_vector`, with a follow-up per-hotel query
    against `rooms_vector` for `matched_room_names` (mirrors what the old
    `match_hotels_with_rooms` RPC returned in one call)."""
    search_query = query
    min_star_rating = None
    max_price = None

    if use_llm_filter:
        filters = extract_search_filters(query, search_type="hotel", model=model)
        if filters.get("clean_query"):
            search_query = filters["clean_query"]
        if filter_destination_id is None and filters.get("destination_name"):
            from src.services.supabase_search import _get_destination_id_by_name
            filter_destination_id = _get_destination_id_by_name(filters["destination_name"])
        min_star_rating = filters.get("min_star_rating")
        max_price = filters.get("max_price")

    query_vector = get_embeddings().embed_query(search_query)
    fetch_count = match_count * 3 if (min_star_rating or max_price) else match_count

    client = get_qdrant_client()
    response = client.query_points(
        collection_name=HOTELS_VECTOR.name,
        query=query_vector,
        query_filter=_destination_filter(filter_destination_id),
        limit=fetch_count,
    )

    filtered = []
    for point in response.points:
        meta = (point.payload or {}).get("metadata", {})
        hotel_id = meta.get("hotel_id")
        if not hotel_id:
            continue
        star = meta.get("star_rating")
        if min_star_rating is not None and min_star_rating > 0 and star is not None and float(star) < float(min_star_rating):
            continue
        filtered.append((point, meta, hotel_id))

    if not filtered and (min_star_rating or max_price) and response.points:
        logger.info("No hotels met strict filters (star>=%s); returning semantic matches.", min_star_rating)
        filtered = [
            (p, (p.payload or {}).get("metadata", {}), (p.payload or {}).get("metadata", {}).get("hotel_id"))
            for p in response.points
            if (p.payload or {}).get("metadata", {}).get("hotel_id")
        ]

    results = []
    for point, meta, hotel_id in filtered[:match_count]:
        results.append({
            "id": hotel_id,
            "score": point.score,
            "matched_room_names": _matched_room_names(client, hotel_id, query_vector),
        })
    return results
