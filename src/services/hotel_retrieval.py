"""Retrieval-shape rendering for hotel search results (Phase 4 of
plans/260724-0925-hotel-normalize-dedupe-for-vector-rag).

Collapses hotels sharing an auto-approved cross-OTA canonical group
(`hotel_pipeline.assign_physical_hotel_groups`) into one RAG-facing result
with multiple OTA offers, so AI presentation never shows the same physical
hotel twice. `pending_review` and ungrouped hotels always render individually
— a group awaiting manual approval must never look merged to the AI/user.

This has no live Qdrant/DB dependency: it operates purely on hotel-shaped
dicts (either the DAG's in-memory records, or Qdrant payloads hydrated back
into the same shape by `src/services/hotel_search.py`). Moved here from
`src/airflow/dags/data_pipeline/` in Phase 5 so both the DAG (via its `src`
mount) and the backend process can import it without a `sys.path` hack.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List

# Mirrors hotel_pipeline.AUTO_APPROVED (src/airflow/dags/data_pipeline/hotel_pipeline.py).
# Not imported directly: that module is Airflow-only (pulls in psycopg2 and the
# full ETL pipeline as import side effects) and isn't on this process's path.
# hotel_pipeline.py is the source of truth for the value; keep them in sync.
AUTO_APPROVED = "auto_approved"

# scraped_at is timezone-aware (UTC); datetime.min alone is naive and would
# raise TypeError when compared against it in the tie-breaker sort key below.
_MIN_DATETIME_UTC = datetime.min.replace(tzinfo=timezone.utc)


def _listing_id(hotel: Dict[str, Any]) -> str:
    return f"{hotel['source_platform']}:{hotel['source_hotel_id']}"


def _build_offer(hotel: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "source_platform": hotel["source_platform"],
        "source_hotel_id": hotel["source_hotel_id"],
        # Present only once Phase 4's Supabase load has run for this hotel
        # (sync_to_supabase on) and Phase 5's writer resolved it into the
        # Qdrant payload; None otherwise (DAG-side in-memory hotel dicts,
        # pre-Qdrant, never have this key either — hotel.get() is safe).
        "supabase_hotel_id": hotel.get("supabase_hotel_id"),
        "min_price": hotel.get("lowest_price"),
        "currency": hotel.get("currency"),
        "check_in_date": hotel.get("price_check_in_date"),
        "check_out_date": hotel.get("price_check_out_date"),
        "source_url": hotel.get("source_url"),
    }


def _pick_best_listing(members: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Most complete record wins display duties: has description, then higher
    review count, then newest scrape — matches Phase 3's tie-breaker rule."""
    return max(
        members,
        key=lambda h: (
            1 if h.get("description") else 0,
            h.get("review_count") or 0,
            h.get("scraped_at") or _MIN_DATETIME_UTC,
        ),
    )


def _render_result(group_key: Any, members: List[Dict[str, Any]]) -> Dict[str, Any]:
    best = _pick_best_listing(members)
    return {
        "canonical_hotel_key": group_key,
        "display_name": best["name"],
        "matched_listing_ids": [_listing_id(m) for m in members],
        "best_source_listing_id": _listing_id(best),
        "offers": [_build_offer(m) for m in members],
        "grounding_facts": best["retrieval"]["grounding_facts"],
    }


def render_hotel_search_results(hotels: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build the RAG result shape: one entry per canonical hotel, `offers`
    holding every underlying OTA listing. `hotels` rows themselves are never
    mutated or merged — this only changes how results are presented."""
    groups: Dict[str, List[Dict[str, Any]]] = {}
    singles: List[Dict[str, Any]] = []

    for hotel in hotels:
        canonical = hotel["canonical"]
        group_key = canonical.get("canonical_hotel_key")
        if group_key and canonical.get("group_review_status") == AUTO_APPROVED:
            groups.setdefault(group_key, []).append(hotel)
        else:
            singles.append(hotel)

    results = [_render_result(group_key, members) for group_key, members in groups.items()]
    results += [_render_result(_listing_id(hotel), [hotel]) for hotel in singles]
    return results
