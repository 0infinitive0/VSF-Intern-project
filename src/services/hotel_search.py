"""Dedupe-aware hotel search over `hotels_vector` (Phase 5). Two correctness
properties the pre-Phase-5 design missed, both fixed here rather than by
over-fetching (see phase-05's "Retrieval side" section):

1. Group completeness comes from a second, filtered lookup on the indexed
   `canonical_hotel_key` field, not from widening the vector-query fetch
   window — a `k*3` window still silently drops a cross-OTA twin that ranks
   outside it.
2. `scraped_at` is parsed back from Qdrant's JSON string into a tz-aware
   datetime before hydration, so `hotel_retrieval._pick_best_listing`'s sort
   key never compares `str` to `datetime` (a `TypeError` at query time, in
   the agent's hot path, for any group with a mixed-availability member).
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from qdrant_client.http import models

from src.services.hotel_retrieval import AUTO_APPROVED, render_hotel_search_results
from src.services.qdrant_schema import HOTELS_VECTOR
from src.services.qdrant_writer import PAYLOAD_VERSION
from src.services.supabase_search import extract_search_filters, get_embeddings
from src.services.vector_store import get_qdrant_client

logger = logging.getLogger(__name__)

# Over-fetch beyond `k` so collapsing cross-OTA groups still tends to leave
# `k` results, not fewer. A heuristic, not a correctness guarantee — group
# completeness itself comes from the indexed canonical_hotel_key lookup
# below, not from this multiplier (see module docstring point 1).
_FETCH_MULTIPLIER = 2


def _destination_filter(destination_id: Optional[str]) -> Optional[models.Filter]:
    if not destination_id:
        return None
    return models.Filter(
        must=[models.FieldCondition(key="destination_id", match=models.MatchValue(value=str(destination_id)))]
    )


def _parse_scraped_at(raw: Any) -> Optional[datetime]:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw
    try:
        return datetime.fromisoformat(str(raw))
    except ValueError:
        logger.warning("hotel_search: could not parse scraped_at %r", raw)
        return None


def _hydrate(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Reconstruct the hotel_retrieval-shaped dict `render_hotel_search_results()`
    expects from a flat Qdrant payload. `grounding_facts` carries the exact-value
    fields (`lowest_price`, `currency`, `source_url`, `scraped_at`, `review_count`,
    ...) that `build_hotel_payload()` deliberately excludes as a filter payload —
    flatten them onto the root so `_build_offer()`/`_pick_best_listing()` (which
    read those keys off the hotel dict directly) work unchanged.

    Known divergence from the DAG-side path: `_pick_best_listing()`'s first
    tie-breaker is `hotel.get("description")`, but `description` is in
    neither `build_hotel_payload()` nor `build_grounding_facts()`. Every
    hydrated hotel scores 0 there, so "most complete record wins display
    duties" silently falls through to review_count/scraped_at for every
    group. Not a crash — just a weaker tie-break than the in-memory DAG path
    uses. Fixing it means extending one of those two contracts, which a
    prior phase's design deliberately keeps untouched."""
    grounding_facts = dict(payload.get("grounding_facts") or {})
    hotel = {
        **grounding_facts,
        "source_platform": payload.get("source_platform"),
        "source_hotel_id": payload.get("source_hotel_id"),
        "supabase_hotel_id": payload.get("supabase_hotel_id"),
        "name": payload.get("name"),
        "scraped_at": _parse_scraped_at(grounding_facts.get("scraped_at")),
        "canonical": {
            "canonical_hotel_key": payload.get("canonical_hotel_key"),
            "group_review_status": payload.get("group_review_status"),
        },
        "retrieval": {
            "grounding_facts": grounding_facts,
        },
    }
    return hotel


def _fetch_group_members(client, canonical_hotel_keys: List[str]) -> List[Dict[str, Any]]:
    """One filtered scroll for every group needing completion, not one per
    key — `MatchAny` avoids an N-round-trip loop in the agent's hot path."""
    if not canonical_hotel_keys:
        return []
    records, _next_offset = client.scroll(
        collection_name=HOTELS_VECTOR.name,
        scroll_filter=models.Filter(
            must=[models.FieldCondition(key="canonical_hotel_key", match=models.MatchAny(any=canonical_hotel_keys))]
        ),
        # A physical-hotel group is at most one listing per OTA; the *2 is
        # slack for multiple distinct groups sharing this single lookup.
        limit=64 * len(canonical_hotel_keys),
        with_payload=True,
        with_vectors=False,
    )
    return [record.payload or {} for record in records]


def search_hotels(
    query: str,
    destination_id: Optional[str] = None,
    k: int = 5,
    use_llm_filter: bool = True,
    model: str = "qwen2.5:7b-instruct",
) -> List[Dict[str, Any]]:
    """Semantic search over `hotels_vector` -> group-completion lookup by
    `canonical_hotel_key` -> hydrate -> `render_hotel_search_results()`.
    Returns at most `k` results, best-scoring first; a result may bundle
    multiple OTA `offers` for an auto-approved cross-OTA group. Each result
    carries `id`/`score` for callers that key off a stable identifier (the
    Airflow dashboard) — `id` is the resolved `supabase_hotel_id` of the
    best-scoring underlying offer, `None` until Phase 4's Supabase load has
    run for that hotel."""
    search_query = query
    min_star_rating = None
    max_price = None

    if use_llm_filter:
        filters = extract_search_filters(query, search_type="hotel", model=model)
        if filters.get("clean_query"):
            search_query = filters["clean_query"]
        if destination_id is None and filters.get("destination_name"):
            from src.services.supabase_search import _get_destination_id_by_name
            destination_id = _get_destination_id_by_name(filters["destination_name"])
        min_star_rating = filters.get("min_star_rating")
        # max_price was extracted but never applied by the pre-Phase-5 hotel
        # search either (build_hotel_payload()'s "min_price" is the cheapest
        # room's price observed at crawl time, not a queryable filter field
        # here) — preserved as-is, not a new gap introduced by this phase.
        max_price = filters.get("max_price")  # noqa: F841

    client = get_qdrant_client()
    query_vector = get_embeddings().embed_query(search_query)

    response = client.query_points(
        collection_name=HOTELS_VECTOR.name,
        query=query_vector,
        query_filter=_destination_filter(destination_id),
        limit=k * _FETCH_MULTIPLIER,
    )

    payloads_by_key: Dict[str, Dict[str, Any]] = {}
    scores_by_key: Dict[str, float] = {}
    canonical_keys_to_complete = set()
    skipped_stale_payload = 0

    for point in response.points:
        payload = point.payload or {}
        # Guards against reading a not-yet-migrated (or future-shape)
        # collection: a Gen-1 nested payload, or a mid-migration alias
        # target, has no `payload_version` and would otherwise silently
        # collapse into one garbage "None:None" result instead of just
        # returning nothing for this point.
        if payload.get("payload_version") != PAYLOAD_VERSION:
            skipped_stale_payload += 1
            continue

        star = payload.get("star_rating")
        if min_star_rating and min_star_rating > 0 and star is not None and float(star) < float(min_star_rating):
            continue

        identity_key = f"{payload.get('source_platform')}:{payload.get('source_hotel_id')}"
        payloads_by_key[identity_key] = payload
        scores_by_key[identity_key] = point.score
        canonical_hotel_key = payload.get("canonical_hotel_key")
        if canonical_hotel_key and payload.get("group_review_status") == AUTO_APPROVED:
            canonical_keys_to_complete.add(canonical_hotel_key)

    if skipped_stale_payload:
        logger.warning(
            "hotel_search: skipped %d point(s) with payload_version != %s "
            "(hotels_vector not yet synced by Phase 5's writer, or a shape mismatch)",
            skipped_stale_payload, PAYLOAD_VERSION,
        )

    for member_payload in _fetch_group_members(client, sorted(canonical_keys_to_complete)):
        identity_key = f"{member_payload.get('source_platform')}:{member_payload.get('source_hotel_id')}"
        payloads_by_key.setdefault(identity_key, member_payload)

    hotels = [_hydrate(payload) for payload in payloads_by_key.values()]
    results = render_hotel_search_results(hotels)

    for result in results:
        member_scores = [scores_by_key[lid] for lid in result["matched_listing_ids"] if lid in scores_by_key]
        result["score"] = max(member_scores) if member_scores else 0.0
        best_offer = next(
            (o for o in result["offers"] if o.get("supabase_hotel_id")), None
        )
        result["id"] = best_offer["supabase_hotel_id"] if best_offer else None

    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:k]
