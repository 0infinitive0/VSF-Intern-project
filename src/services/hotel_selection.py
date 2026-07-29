"""Hotel Selection Service.

Handles searching, filtering, meal amenity detection, and selecting verified
hotel candidates for itinerary planning.
"""

from __future__ import annotations

import logging
import os
import re
import unicodedata
from typing import Any, Dict, List, Tuple

from supabase import Client, create_client

from src.config import get_settings
from src.services.supabase_search import search_hotels_with_rooms
from src.services.trip_scheduler import PlaceCandidate, detect_covered_hotel_meals

logger = logging.getLogger(__name__)


def _get_supabase_client() -> Client:
    settings = get_settings()
    url = getattr(settings, "supabase_url", None) or os.environ.get("SUPABASE_URL")
    key = getattr(settings, "supabase_service_key", None) or os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise ValueError("Missing SUPABASE_URL or SUPABASE_SERVICE_KEY in environment or settings.")
    return create_client(url, key)


def _hydrate_hotel_records(search_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merge compact RPC hotel search results with canonical Supabase hotel rows."""
    result_ids = [str(result.get("id")) for result in search_results if result.get("id")]
    if not result_ids:
        return []
    try:
        supabase = _get_supabase_client()
        response = (
            supabase.table("hotels")
            .select(
                "id,destination_id,name,star_rating,description,coordinates,amenities,amenity_groups,"
                "review_score,review_count,address,area_name,lowest_price,currency,image_url"
            )
            .in_("id", result_ids)
            .execute()
        )
        canonical_by_id = {str(row["id"]): row for row in response.data or [] if row.get("id")}
    except Exception as exc:
        logger.error("Failed to hydrate hotel search results: %s", exc)
        return []
    hydrated = []
    for result in search_results:
        canonical = canonical_by_id.get(str(result.get("id")))
        if canonical:
            hydrated.append({**result, **canonical})
    return hydrated


def select_hotel_candidates(
    destination: str,
    destination_id: str,
    people: str,
    hotel_query: str | None = None,
    match_count: int = 5,
) -> List[Tuple[Dict[str, Any], PlaceCandidate]]:
    """Search and return verified hotel options along with PlaceCandidate objects.
    
    Each returned tuple contains:
    1. hotel_data (Dict): Structured hotel details (id, name, rating, coordinates, matched rooms, covered meals).
    2. candidate (PlaceCandidate): Geo-located candidate object used by the itinerary scheduler.
    """
    query = hotel_query or f"Hotel in {destination} for {people} people"
    search_results = search_hotels_with_rooms(
        query=query,
        match_count=match_count,
        filter_destination_id=destination_id,
    ) or []
    
    hydrated = _hydrate_hotel_records(search_results)
    options: List[Tuple[Dict[str, Any], PlaceCandidate]] = []
    
    for hotel in hydrated:
        if str(hotel.get("destination_id")) != destination_id:
            continue
            
        covered_meals = detect_covered_hotel_meals(
            hotel.get("amenities"),
            hotel.get("amenity_groups"),
            hotel.get("matched_room_names"),
        )
        
        candidate = PlaceCandidate.from_mapping(
            {**hotel, "category": "Hotel", "covered_meals": covered_meals}
        )
        
        if not candidate.coordinate_pair:
            continue
            
        hotel_data = {
            "id": candidate.id,
            "destination_id": destination_id,
            "name": candidate.name,
            "star_rating": hotel.get("star_rating"),
            "description": hotel.get("description") or "Khách sạn có dữ liệu vị trí đã được xác minh.",
            "coordinates": hotel.get("coordinates"),
            "matched_rooms": (hotel.get("matched_room_names") or [])[:2],
            "covered_meals": sorted(covered_meals),
            "review_score": hotel.get("review_score"),
            "review_count": hotel.get("review_count"),
            "address": hotel.get("address"),
            "area_name": hotel.get("area_name"),
            "lowest_price": hotel.get("lowest_price"),
            "currency": hotel.get("currency"),
            "image_url": hotel.get("image_url"),
            "similarity": hotel.get("similarity"),
        }
        options.append((hotel_data, candidate))

    return options


def rank_hotel_candidates(
    options: List[Tuple[Dict[str, Any], PlaceCandidate]],
) -> List[Tuple[Dict[str, Any], PlaceCandidate]]:
    """Sort search results by a weighted blend of similarity, rating, review score, and price.

    Similarity stays dominant (0.55) since it reflects how well the hotel matches what the
    user asked for; rating/review/price only refine the order among otherwise-similar hits.
    """
    if not options:
        return []

    def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
        return max(low, min(value, high))

    prices = [
        float(data["lowest_price"])
        for data, _ in options
        if data.get("lowest_price") is not None
    ]
    min_price, max_price = (min(prices), max(prices)) if prices else (None, None)

    def _price_score(data: Dict[str, Any]) -> float:
        price = data.get("lowest_price")
        if price is None or min_price is None or max_price is None:
            return 0.0
        if max_price == min_price:
            return 1.0
        return _clamp(1.0 - (float(price) - min_price) / (max_price - min_price))

    def _composite_score(data: Dict[str, Any], candidate: PlaceCandidate) -> float:
        similarity_score = _clamp(float(data.get("similarity") or candidate.similarity or 0.0))
        rating_score = _clamp(float(data.get("star_rating") or 0.0) / 5.0)
        review_score_norm = _clamp(float(data.get("review_score") or 0.0) / 10.0)
        price_score = _price_score(data)
        return (
            0.55 * similarity_score
            + 0.20 * rating_score
            + 0.15 * review_score_norm
            + 0.10 * price_score
        )

    ranked = sorted(
        options,
        key=lambda option: _composite_score(option[0], option[1]),
        reverse=True,
    )
    for index, (data, _candidate) in enumerate(ranked, start=1):
        data["rank"] = index
        data["recommendation_score"] = _composite_score(data, _candidate)
    return ranked


def resolve_hotel_selection(
    selection: str,
    options: List[Tuple[Dict[str, Any], PlaceCandidate]],
) -> Tuple[Dict[str, Any], PlaceCandidate] | None:
    """Resolve a free-text chat reply against a previously shown, ranked option list.

    Tries a leading rank number first (matching the numbered list users are shown), then
    falls back to a case/diacritic-insensitive substring match against the hotel name.
    Returns None on no match or an ambiguous (multi-match) name.
    """
    if not options:
        return None

    stripped = selection.strip()
    match = re.match(r"\d+", stripped)
    if match:
        rank = int(match.group())
        for data, candidate in options:
            if data.get("rank") == rank:
                return data, candidate
        return None

    normalized_selection = _normalize_for_match(stripped)
    if not normalized_selection:
        return None
    matches = [
        (data, candidate)
        for data, candidate in options
        if normalized_selection in _normalize_for_match(str(data.get("name") or ""))
    ]
    if len(matches) == 1:
        return matches[0]
    return None


def _normalize_for_match(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.replace("Đ", "D").replace("đ", "d"))
    return "".join(char for char in decomposed if not unicodedata.combining(char)).casefold().strip()


def fetch_hotel_by_id(
    hotel_id: str,
    destination_id: str | None = None,
) -> Tuple[Dict[str, Any], PlaceCandidate] | None:
    """Fetch a single hotel by id, in the same (hotel_data, PlaceCandidate) shape as
    select_hotel_candidates, for re-hydrating a hotel the caller already chose."""
    hydrated = _hydrate_hotel_records([{"id": hotel_id}])
    if not hydrated:
        return None
    hotel = hydrated[0]
    if destination_id is not None and str(hotel.get("destination_id")) != str(destination_id):
        return None

    covered_meals = detect_covered_hotel_meals(
        hotel.get("amenities"),
        hotel.get("amenity_groups"),
    )
    candidate = PlaceCandidate.from_mapping(
        {**hotel, "category": "Hotel", "covered_meals": covered_meals}
    )
    if not candidate.coordinate_pair:
        return None

    hotel_data = {
        "id": candidate.id,
        "destination_id": str(hotel.get("destination_id") or destination_id or ""),
        "name": candidate.name,
        "star_rating": hotel.get("star_rating"),
        "description": hotel.get("description") or "Khách sạn có dữ liệu vị trí đã được xác minh.",
        "coordinates": hotel.get("coordinates"),
        "matched_rooms": [],
        "covered_meals": sorted(covered_meals),
        "review_score": hotel.get("review_score"),
        "review_count": hotel.get("review_count"),
        "address": hotel.get("address"),
        "area_name": hotel.get("area_name"),
        "lowest_price": hotel.get("lowest_price"),
        "currency": hotel.get("currency"),
        "image_url": hotel.get("image_url"),
    }
    return hotel_data, candidate
