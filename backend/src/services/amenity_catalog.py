"""Server-side access to the approved hotel amenity catalog.

The catalog is intentionally read through the service-role Supabase client.  It
is not a user-facing data endpoint: callers receive only approved definitions
that have already passed the amenity-classification review flow.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import re
import time
from typing import Collection, Iterable

from langchain_core.messages import HumanMessage, SystemMessage

from src.services.llm import get_fast_llm
from src.services.supabase_search import get_supabase_client


logger = logging.getLogger(__name__)

_AMENITY_ID_PATTERN = re.compile(r"^[a-z0-9_]{1,64}$")
_CATALOG_TABLE = "hotel_amenity_catalog"
_CATALOG_FIELDS = "id,label,match_keywords"
_MAX_REQUESTED_IDS = 100
_MAX_DISCOVERY_CANDIDATES = 8
_MAX_MATCH_KEYWORDS = 8
_MAX_KEYWORD_LENGTH = 80


@dataclass(frozen=True)
class AmenityCatalogEntry:
    """One approved amenity and the normalized phrases used to match hotels."""

    id: str
    label: str
    match_keywords: tuple[str, ...]


def query_approved_amenities(
    amenity_ids: Collection[str] | None = None,
) -> list[AmenityCatalogEntry]:
    """Return approved catalog entries, optionally restricted to valid IDs.

    Invalid IDs are never interpolated into the database query.  If the
    migration is not deployed yet, or Supabase is temporarily unavailable, the
    caller receives an empty result so unreviewed preferences do not become
    filter pills.
    """

    requested_ids = _valid_amenity_ids(amenity_ids)
    if amenity_ids is not None and not requested_ids:
        return []

    try:
        query = (
            get_supabase_client()
            .table(_CATALOG_TABLE)
            .select(_CATALOG_FIELDS)
            .eq("is_approved", True)
        )
        if requested_ids:
            query = query.in_("id", requested_ids)
        response = query.limit(_MAX_REQUESTED_IDS).execute()
    except Exception as exc:  # Supabase may lag behind the backend migration.
        logger.warning("Approved amenity catalog query failed: %s", type(exc).__name__)
        return []

    return _parse_catalog_entries(getattr(response, "data", None) or [])


_ALL_AMENITIES_CACHE_SECONDS = 60.0
_all_amenities_cache: tuple[tuple[AmenityCatalogEntry, ...], float] | None = None


def all_approved_amenities() -> tuple[AmenityCatalogEntry, ...]:
    """TTL-cached wrapper around `query_approved_amenities()` (no ID filter)
    for hot-path callers -- e.g. `respond`'s per-turn `all_preferences` field
    -- that need the full approved catalog without a Supabase round-trip on
    every turn."""

    global _all_amenities_cache
    now = time.monotonic()
    if _all_amenities_cache is not None and now - _all_amenities_cache[1] < _ALL_AMENITIES_CACHE_SECONDS:
        return _all_amenities_cache[0]
    entries = tuple(query_approved_amenities())
    _all_amenities_cache = (entries, now)
    return entries


def clear_all_approved_amenities_cache() -> None:
    """Invalidate `all_approved_amenities()` after a newly approved amenity
    is stored, and for tests that need a fresh Supabase read."""

    global _all_amenities_cache
    _all_amenities_cache = None


def discover_and_store_amenities(
    candidates: Collection[dict[str, str]],
) -> list[AmenityCatalogEntry]:
    """Classify unknown hotel-only preferences and persist approved amenities.

    The fast model is an untrusted classifier, not an authority over database
    structure: it can only approve IDs submitted by this backend call and all
    returned keywords are bounded before they are stored.
    """

    candidate_by_id = _valid_discovery_candidates(candidates)
    if not candidate_by_id:
        return []

    approved_rows = _approved_discovery_rows(candidate_by_id)
    if not approved_rows:
        return []

    try:
        get_supabase_client().table(_CATALOG_TABLE).insert(approved_rows).execute()
    except Exception as exc:
        # A concurrent request may insert the same row first. The next catalog
        # lookup will see it; never turn an LLM classification failure into a
        # recommendation error.
        logger.warning("Amenity catalog discovery write failed: %s", type(exc).__name__)
        return []

    clear_all_approved_amenities_cache()
    logger.info("Amenity catalog discovery added %d approved amenity entries", len(approved_rows))
    return [
        AmenityCatalogEntry(
            id=row["id"],
            label=row["label"],
            match_keywords=tuple(row["match_keywords"]),
        )
        for row in approved_rows
    ]


def _valid_discovery_candidates(
    candidates: Collection[dict[str, str]],
) -> dict[str, str]:
    """Return bounded candidate IDs and labels suitable for the classifier."""

    valid: dict[str, str] = {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        amenity_id = str(candidate.get("id") or "").strip().lower()
        label = str(candidate.get("label") or "").strip()
        if (
            not _AMENITY_ID_PATTERN.fullmatch(amenity_id)
            or not label
            or len(label) > _MAX_KEYWORD_LENGTH
            or amenity_id in valid
        ):
            continue
        valid[amenity_id] = label
        if len(valid) == _MAX_DISCOVERY_CANDIDATES:
            break
    return valid


def _approved_discovery_rows(candidate_by_id: dict[str, str]) -> list[dict[str, object]]:
    """Ask the fast model for bounded amenity classifications, failing closed."""

    prompt_candidates = [
        {"id": amenity_id, "label": label}
        for amenity_id, label in candidate_by_id.items()
    ]
    try:
        response = get_fast_llm(temperature=0.0).invoke(
            [
                SystemMessage(
                    content=(
                        "Classify hotel preferences. A hotel amenity is a physical facility, "
                        "service, room feature, or included hotel offering. Exclude trip themes, "
                        "activities, destinations, prices, ratings, and generic travel preferences. "
                        "When a submitted label is Vietnamese, include direct Vietnamese hotel-data "
                        "matching terms (with Vietnamese diacritics) as well as any useful English "
                        "synonym; never return English-only keywords for a Vietnamese preference. "
                        "Return JSON only."
                    )
                ),
                HumanMessage(
                    content=(
                        "For each submitted candidate, return exactly this JSON shape: "
                        '{"amenities":[{"id":"submitted_id","is_amenity":true|false,'
                        '"match_keywords":["short phrase"]}]}. '
                        "Use only submitted IDs. Include 1 to 8 hotel-data matching keywords only "
                        "when is_amenity is true. Candidates: "
                        + json.dumps(prompt_candidates, ensure_ascii=False)
                    )
                ),
            ]
        )
        payload = _parse_model_json(getattr(response, "content", ""))
    except Exception as exc:
        logger.warning("Amenity catalog discovery classification failed: %s", type(exc).__name__)
        return []

    results = payload.get("amenities") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        return []

    rows: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    for result in results:
        if not isinstance(result, dict) or result.get("is_amenity") is not True:
            continue
        amenity_id = result.get("id")
        if not isinstance(amenity_id, str) or amenity_id not in candidate_by_id or amenity_id in seen_ids:
            continue
        keywords = _validated_match_keywords(result.get("match_keywords"))
        if not keywords:
            continue
        canonical_keyword = amenity_id.replace("_", " ")
        if canonical_keyword not in keywords:
            keywords.insert(0, canonical_keyword)
        seen_ids.add(amenity_id)
        rows.append(
            {
                "id": amenity_id,
                "label": candidate_by_id[amenity_id],
                "match_keywords": keywords,
                "source": "fast_model",
                "is_approved": True,
            }
        )
    return rows


def _parse_model_json(content: object) -> object:
    """Parse a model JSON response without accepting prose or code fences."""

    if not isinstance(content, str):
        return {}
    text = content.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return json.loads(text.strip())


def _validated_match_keywords(value: object) -> list[str]:
    """Return unique, bounded plain-text matching phrases from model output."""

    if not isinstance(value, list) or not 1 <= len(value) <= _MAX_MATCH_KEYWORDS:
        return []
    keywords: list[str] = []
    for raw_keyword in value:
        if not isinstance(raw_keyword, str):
            return []
        keyword = raw_keyword.strip().lower()
        if not keyword or len(keyword) > _MAX_KEYWORD_LENGTH or keyword in keywords:
            continue
        keywords.append(keyword)
    return keywords


def _valid_amenity_ids(amenity_ids: Collection[str] | None) -> list[str]:
    """Normalize, de-duplicate, and bound IDs before they reach PostgREST."""

    valid_ids: list[str] = []
    for raw_id in amenity_ids or ():
        amenity_id = str(raw_id).strip().lower()
        if not _AMENITY_ID_PATTERN.fullmatch(amenity_id) or amenity_id in valid_ids:
            continue
        valid_ids.append(amenity_id)
        if len(valid_ids) == _MAX_REQUESTED_IDS:
            break
    return valid_ids


def _parse_catalog_entries(rows: Iterable[object]) -> list[AmenityCatalogEntry]:
    """Discard malformed rows rather than allowing bad catalog data downstream."""

    entries: list[AmenityCatalogEntry] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        amenity_id = row.get("id")
        label = row.get("label")
        raw_keywords = row.get("match_keywords")
        if (
            not isinstance(amenity_id, str)
            or not _AMENITY_ID_PATTERN.fullmatch(amenity_id)
            or not isinstance(label, str)
            or not label.strip()
            or not isinstance(raw_keywords, list)
        ):
            continue
        keywords = tuple(
            keyword.strip().lower()
            for keyword in raw_keywords
            if isinstance(keyword, str) and keyword.strip()
        )
        if not keywords:
            continue
        entries.append(
            AmenityCatalogEntry(
                id=amenity_id,
                label=label.strip(),
                match_keywords=keywords,
            )
        )
    return entries
