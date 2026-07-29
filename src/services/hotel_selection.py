"""Hotel Selection Service.

Handles searching, filtering, meal amenity detection, and selecting verified
hotel candidates for itinerary planning.
"""

from __future__ import annotations

import logging
import os
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
            .select("id,destination_id,name,star_rating,description,coordinates,amenities,amenity_groups")
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
        }
        options.append((hotel_data, candidate))
        
    return options


def select_primary_hotel(
    options: List[Tuple[Dict[str, Any], PlaceCandidate]]
) -> Tuple[Dict[str, Any], PlaceCandidate] | None:
    """Return the primary (first available) chosen hotel option."""
    if not options:
        return None
    return options[0]
