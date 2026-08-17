import logging
from typing import Any, Collection

from src.clients.supabase_client import get_supabase_client
from src.services.supabase_search import (
    rpc_search_attractions,
    rpc_search_attractions_tiered,
)
from src.services.trip_scheduler import PlaceCandidate

logger = logging.getLogger(__name__)


def hydrate_records(table_name: str, search_results: list[dict[str, Any]], fields: str) -> list[dict[str, Any]]:
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


def to_place_candidates(rows: list[dict[str, Any]]) -> list[PlaceCandidate]:
    candidates = []
    for row in rows:
        candidate = PlaceCandidate.from_mapping(row)
        if candidate.id and candidate.name and candidate.coordinate_pair:
            candidates.append(candidate)
    return candidates


def search_attraction_candidates(
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
    hydrated = hydrate_records(
        "attractions",
        compact_results,
        (
            "id,destination_id,name,description,category,is_tour,estimated_duration_minutes,"
            "opening_time,closing_time,rating,coordinates,images,ticket_price_adult"
        ),
    )
    return to_place_candidates(hydrated)


def search_attraction_candidates_tiered(
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
    hydrated = hydrate_records(
        "attractions",
        compact_results,
        (
            "id,destination_id,name,description,category,is_tour,estimated_duration_minutes,"
            "opening_time,closing_time,rating,coordinates,images,ticket_price_adult"
        ),
    )
    return to_place_candidates(hydrated)
