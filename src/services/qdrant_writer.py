"""Staged, batched Qdrant writer for hotels: embed -> upsert into a fresh
`hotels_vector_{run_id}` collection -> atomic alias swap on success. Replaces
the Gen-1 hotel sync (`scripts/sync_accommodations_to_qdrant.py`'s hotel
branch), which upserted in place with no explicit IDs and duplicated the
corpus on every run. Writing beside the live collection and swapping the
`hotels_vector` alias only on success means a mid-run failure (Ollama
timeout, Qdrant write error) leaves the previous corpus serving reads
untouched — see phase-05's "Atomicity" section for the failure mode this
avoids.
"""

import json
import logging
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from qdrant_client import QdrantClient
from qdrant_client.http.models import (
    CreateAlias,
    CreateAliasOperation,
    DeleteAlias,
    DeleteAliasOperation,
    PointStruct,
)

from src.services.qdrant_schema import HOTELS_VECTOR, CollectionSpec, ensure_collection, point_id
from src.services.supabase_search import get_embeddings

logger = logging.getLogger(__name__)

# Bumped whenever the payload shape changes, so a reader can tell old points
# (pre-Phase-5, if any ever survive) from new ones during debugging.
PAYLOAD_VERSION = 1

# Mirrors hotel_quality_gate.MAX_PAYLOAD_BYTES (dags/data_pipeline/) — that
# gate measures only hotel_pipeline's retrieval["payload"], not the full
# payload actually assembled here (which adds grounding_facts, an unbounded
# `warnings` list, destination_id, etc.), so it can pass while the real
# upserted payload is larger. This is the authoritative check, against the
# real payload, raised before any batch is upserted (still pre-swap, so
# failure here safely drops the staging collection like any other error).
_MAX_PAYLOAD_BYTES = 32 * 1024

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

_EMBED_RETRIES = 3
_EMBED_BACKOFF_SECONDS = 2


@dataclass
class UpsertStats:
    hotels_embedded: int = 0
    hotels_upserted: int = 0
    identity_resolved: int = 0
    staging_collection: str = ""


def _strip_control_chars(value: Any) -> Any:
    """Untrusted scraped OTA text lands in `grounding_facts` verbatim
    (hotel_pipeline.build_grounding_facts). Stripping control characters at
    write time is the minimum handling phase-05 commits to — not full prompt
    injection defense (source_url allowlisting is recorded as follow-up)."""
    if isinstance(value, str):
        return _CONTROL_CHARS_RE.sub("", value)
    if isinstance(value, list):
        return [_strip_control_chars(v) for v in value]
    if isinstance(value, dict):
        return {k: _strip_control_chars(v) for k, v in value.items()}
    return value


def _identity_key(source_platform: str, source_hotel_id: Any) -> str:
    return f"{source_platform}:{source_hotel_id}"


def _build_payload(hotel: Dict[str, Any], identity: Dict[str, Any]) -> Dict[str, Any]:
    retrieval = hotel["retrieval"]
    canonical = hotel["canonical"]
    return {
        **retrieval["payload"],
        # None when Phase 4's Supabase load hasn't run for this hotel
        # (sync_to_supabase off, or the hotel wasn't in that run's batch) —
        # filters/readers must treat a missing destination_id as "unknown",
        # not as an error.
        "destination_id": identity.get("destination_id"),
        "supabase_hotel_id": identity.get("supabase_hotel_id"),
        "canonical_hotel_key": canonical.get("canonical_hotel_key"),
        "group_review_status": canonical.get("group_review_status"),
        "grounding_facts": _strip_control_chars(retrieval["grounding_facts"]),
        "payload_version": PAYLOAD_VERSION,
    }


def _embed_with_retry(texts: List[str]) -> List[List[float]]:
    embeddings = get_embeddings()
    last_exc: Optional[Exception] = None
    for attempt in range(1, _EMBED_RETRIES + 1):
        try:
            return embeddings.embed_documents(texts)
        except Exception as exc:  # Ollama timeout/connection errors, etc.
            last_exc = exc
            if attempt < _EMBED_RETRIES:
                delay = _EMBED_BACKOFF_SECONDS * attempt
                logger.warning(
                    "embed_documents attempt %d/%d failed (%s); retrying in %ds",
                    attempt, _EMBED_RETRIES, exc, delay,
                )
                time.sleep(delay)
    raise last_exc  # type: ignore[misc]


def _swap_alias(client: QdrantClient, alias_name: str, new_collection_name: str) -> None:
    """Point `alias_name` at `new_collection_name`, atomically dropping any
    prior alias mapping. One-time migration case: if `alias_name` is
    currently a *literal* collection (true for `hotels_vector` before this
    phase's first successful run — Phase 2's `ensure_collection` created it
    directly), Qdrant won't let an alias share that name, so it must be
    deleted first. That leaves a brief window with neither a collection nor
    an alias at `alias_name`; acceptable as a one-time migration cost."""
    literal_names = {c.name for c in client.get_collections().collections}
    if alias_name in literal_names:
        client.delete_collection(alias_name)

    operations = []
    existing_aliases = client.get_aliases().aliases
    for alias in existing_aliases:
        if alias.alias_name == alias_name:
            operations.append(DeleteAliasOperation(delete_alias=DeleteAlias(alias_name=alias_name)))
            break
    operations.append(
        CreateAliasOperation(
            create_alias=CreateAlias(collection_name=new_collection_name, alias_name=alias_name)
        )
    )
    client.update_collection_aliases(change_aliases_operations=operations)


def _sweep_stale_staging_collections(client: QdrantClient, alias_prefix: str, keep: str) -> None:
    """Best-effort cleanup of orphaned `hotels_vector_*` collections left by
    a prior failed run (a killed process never reaches the failure-path
    delete in `upsert_hotels`). Relies on `hotel_dag`'s `max_active_runs=1`
    to rule out two concurrent runs' staging collections colliding here —
    this function does not itself guard against that."""
    for collection in client.get_collections().collections:
        name = collection.name
        if name == keep or not name.startswith(f"{alias_prefix}_"):
            continue
        try:
            client.delete_collection(name)
            logger.info("Swept stale staging collection %s", name)
        except Exception as exc:
            logger.warning("Could not sweep stale staging collection %s: %s", name, exc)


def upsert_hotels(
    client: QdrantClient,
    hotels: List[Dict[str, Any]],
    identity_map: Dict[str, Dict[str, Any]],
    *,
    batch_size: int = 100,
) -> UpsertStats:
    """Embed and upsert normalized hotel records (as produced by
    `hotel_pipeline.normalize_hotels()` / `assign_physical_hotel_groups()`)
    into a staging collection, then swap the `hotels_vector` alias onto it.
    `identity_map` is the `(source_platform, source_hotel_id) ->
    {supabase_hotel_id, destination_id}` mapping from Phase 4's Supabase
    load; an empty dict (Supabase sync off) is valid and yields
    `destination_id: None` payloads throughout.
    """
    if not hotels:
        # An empty batch must never reach _swap_alias: that would point the
        # live alias at a zero-point collection, silently wiping the corpus
        # for every reader. Caught here so the guard holds regardless of caller.
        raise ValueError("upsert_hotels: hotels list is empty; refusing to swap the live alias onto it")

    stats = UpsertStats()
    run_id = uuid.uuid4().hex[:12]
    staging_name = f"{HOTELS_VECTOR.name}_{run_id}"
    stats.staging_collection = staging_name

    staging_spec = CollectionSpec(
        name=staging_name,
        payload_indexes=HOTELS_VECTOR.payload_indexes,
        vector_size=HOTELS_VECTOR.vector_size,
        distance=HOTELS_VECTOR.distance,
    )

    # Once the alias swap has started, `_swap_alias` may already have deleted
    # the pre-existing literal `hotels_vector` collection (the one-time
    # migration case) before `update_collection_aliases` itself fails. If the
    # failure path below still deleted `staging_name` in that case, both the
    # old and the new corpus would be gone with no recovery path — exactly
    # the incident this writer exists to prevent. So once swap_started is
    # True, the staging collection is deliberately left in place on failure.
    swap_started = False
    try:
        ensure_collection(client, staging_spec)

        for i in range(0, len(hotels), batch_size):
            batch = hotels[i : i + batch_size]
            texts = [h["retrieval"]["embedding_text"] for h in batch]
            vectors = _embed_with_retry(texts)
            stats.hotels_embedded += len(batch)

            points = []
            for hotel, vector in zip(batch, vectors):
                key = _identity_key(hotel["source_platform"], hotel["source_hotel_id"])
                identity = identity_map.get(key, {})
                if identity:
                    stats.identity_resolved += 1
                payload = _build_payload(hotel, identity)
                payload_bytes = len(json.dumps(payload, default=str))
                if payload_bytes > _MAX_PAYLOAD_BYTES:
                    raise ValueError(
                        f"Payload for {key} is {payload_bytes} bytes, exceeding the "
                        f"{_MAX_PAYLOAD_BYTES} byte limit (grounding_facts/warnings likely "
                        "oversized) — refusing to upsert this batch"
                    )
                points.append(
                    PointStruct(
                        id=point_id("hotel", hotel["source_platform"], hotel["source_hotel_id"]),
                        vector=vector,
                        payload=payload,
                    )
                )
            client.upsert(collection_name=staging_name, points=points)
            stats.hotels_upserted += len(points)

        swap_started = True
        _swap_alias(client, HOTELS_VECTOR.name, staging_name)
        try:
            _sweep_stale_staging_collections(client, HOTELS_VECTOR.name, keep=staging_name)
        except Exception as sweep_exc:
            # Best-effort by design (docstring); the swap itself already
            # succeeded, so a sweep failure must not fail the whole run or
            # trigger the staging-collection cleanup below.
            logger.warning("Post-swap sweep failed (non-fatal): %s", sweep_exc)
    except Exception:
        if swap_started:
            logger.error(
                "upsert_hotels: alias swap phase failed for %s -> %s. The prior "
                "literal `%s` collection may already be gone, and %s is "
                "deliberately NOT deleted — recover manually by pointing the "
                "alias at it: client.update_collection_aliases(...).",
                HOTELS_VECTOR.name, staging_name, HOTELS_VECTOR.name, staging_name,
            )
            raise
        logger.error("upsert_hotels failed before the alias swap; dropping staging collection %s", staging_name)
        try:
            client.delete_collection(staging_name)
        except Exception as cleanup_exc:
            logger.warning("Failed to clean up staging collection %s: %s", staging_name, cleanup_exc)
        raise

    logger.info(
        "upsert_hotels: embedded %d, upserted %d (%d with resolved Supabase identity) into %s, alias %s -> %s",
        stats.hotels_embedded, stats.hotels_upserted, stats.identity_resolved,
        staging_name, HOTELS_VECTOR.name, staging_name,
    )
    return stats
