"""Server-side access and binding for the approved shared amenity catalog."""

from __future__ import annotations

import json
import logging
import math
import re
import time
import unicodedata
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage

from src.services.llm import get_embeddings, get_fast_llm, response_text
from src.services.supabase_search import get_supabase_client

logger = logging.getLogger(__name__)

AmenityScope = Literal["hotel", "room"]
_AMENITY_ID_PATTERN = re.compile(r"^[a-z0-9_]{1,64}$")
_CATALOG_TABLE = "amenity_catalog"
_CATALOG_FIELDS = "id,label_vi,label_en,scope,category,icon_key,match_keywords,parent_id"
_LEGACY_CATALOG_FIELDS = "id,label_vi,label_en,scope,category,icon_key,match_keywords"
_MAX_REQUESTED_IDS = 100
_CATALOG_PAGE_SIZE = 500
_MAX_DISCOVERY_CANDIDATES = 8
_MAX_MATCH_KEYWORDS = 8
_MAX_KEYWORD_LENGTH = 80
AMENITY_CATEGORIES = frozenset({
    "accessibility", "business", "connectivity", "facility", "family", "food", "general", "language",
    "outdoor", "policies", "room_comfort", "safety", "transport", "wellness",
})
_ROOM_CANONICAL_OVERRIDES = {
    "cac loai khan": "types_of_towels",
    "can ho rieng trong toa nha": "private_apartment_in_the_building",
    "iron": "iron",
    "kitchen": "kitchen",
    "nha ve sinh": "toilet",
    "toilet": "toilet",
    "xe lan co the di den moi noi trong toan bo khuon vien": "wheelchair_accessible_throughout_property",
    "don lap": "detached_unit",
}


@dataclass(frozen=True)
class AmenityCatalogEntry:
    id: str
    label: str
    match_keywords: tuple[str, ...]
    label_en: str = ""
    scope: str = "hotel"
    category: str = "general"
    icon_key: str | None = None
    source_id: str | None = None
    parent_id: str | None = None


@dataclass(frozen=True)
class AmenityBindingResult:
    ids: tuple[str, ...]
    unresolved: tuple[str, ...]
    created: int = 0
    proposals: tuple[AmenityCatalogEntry, ...] = ()
    ambiguities: tuple[AmenityResolution, ...] = ()


@dataclass(frozen=True)
class AmenityCandidate:
    id: str
    label: str
    lexical_score: float
    semantic_score: float
    coverage: int


@dataclass(frozen=True)
class AmenityResolution:
    phrase: str
    status: Literal["resolved", "ambiguous", "unresolved"]
    candidate: AmenityCandidate | None = None
    candidates: tuple[AmenityCandidate, ...] = ()


def query_approved_amenities(amenity_ids: Collection[str] | None = None) -> list[AmenityCatalogEntry]:
    """Return approved shared-catalog entries, optionally limited by safe IDs."""
    requested_ids = _valid_amenity_ids(amenity_ids)
    if amenity_ids is not None and not requested_ids:
        return []
    try:
        return _query_approved_amenities(requested_ids, fields=_CATALOG_FIELDS)
    except Exception as exc:
        # Rolling deploy compatibility: application code may start before the
        # additive parent_id migration reaches Supabase. Retry the old field
        # set; hierarchy stays inactive until the schema is present.
        logger.warning("Approved amenity catalog query with hierarchy failed: %s", type(exc).__name__)
        try:
            return _query_approved_amenities(requested_ids, fields=_LEGACY_CATALOG_FIELDS)
        except Exception as fallback_exc:
            logger.warning("Approved amenity catalog query failed: %s", type(fallback_exc).__name__)
            return []


def _query_approved_amenities(requested_ids: list[str], *, fields: str) -> list[AmenityCatalogEntry]:
    """Execute one field-compatible approved catalog read."""
    if requested_ids:
        response = (
            get_supabase_client().table(_CATALOG_TABLE).select(fields)
            .eq("is_approved", True).in_("id", requested_ids).limit(_MAX_REQUESTED_IDS).execute()
        )
        return _parse_catalog_entries(getattr(response, "data", None) or [])
    rows: list[object] = []
    start = 0
    while True:
        response = (
            get_supabase_client().table(_CATALOG_TABLE).select(fields)
            .eq("is_approved", True).range(start, start + _CATALOG_PAGE_SIZE - 1).execute()
        )
        page = getattr(response, "data", None) or []
        rows.extend(page)
        if len(page) < _CATALOG_PAGE_SIZE:
            break
        start += _CATALOG_PAGE_SIZE
    return _parse_catalog_entries(rows)


def query_all_approved_amenities_by_ids(amenity_ids: Collection[str]) -> list[AmenityCatalogEntry]:
    """Return every approved catalog entry requested by a trusted response path.

    ``query_approved_amenities`` intentionally retains its 100-ID limit for
    general callers. Hotel response serialization already owns the IDs from a
    finite list of returned cards, so it can safely preserve every distinct ID
    by issuing bounded PostgREST ``IN`` queries in batches.
    """
    requested_ids = _valid_amenity_ids_unbounded(amenity_ids)
    entries: list[AmenityCatalogEntry] = []
    for start in range(0, len(requested_ids), _MAX_REQUESTED_IDS):
        entries.extend(query_approved_amenities(requested_ids[start : start + _MAX_REQUESTED_IDS]))
    return entries


_ALL_AMENITIES_CACHE_SECONDS = 60.0
_all_amenities_cache: tuple[tuple[AmenityCatalogEntry, ...], float] | None = None
_hotel_amenity_coverage_cache: tuple[dict[str, int], float] | None = None
_catalog_embedding_cache: tuple[tuple[str, ...], tuple[tuple[float, ...], ...]] | None = None


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

    global _all_amenities_cache, _hotel_amenity_coverage_cache, _catalog_embedding_cache
    _all_amenities_cache = None
    _hotel_amenity_coverage_cache = None
    _catalog_embedding_cache = None


def hotel_amenity_coverage() -> dict[str, int]:
    """Return hotel counts per canonical amenity ID on the catalog TTL.

    Hotel rows already store canonical IDs, so one paged read is enough to
    keep zero-coverage catalog artifacts out of the user-facing binder. A
    failed read returns an empty map and preserves the existing fail-closed
    resolver behavior.
    """

    global _hotel_amenity_coverage_cache
    now = time.monotonic()
    if (
        _hotel_amenity_coverage_cache is not None
        and now - _hotel_amenity_coverage_cache[1] < _ALL_AMENITIES_CACHE_SECONDS
    ):
        return dict(_hotel_amenity_coverage_cache[0])

    counts: dict[str, int] = {}
    start = 0
    try:
        while True:
            response = (
                get_supabase_client().table("hotels").select("amenities")
                .range(start, start + _CATALOG_PAGE_SIZE - 1).execute()
            )
            page = getattr(response, "data", None) or []
            for row in page:
                if not isinstance(row, dict):
                    continue
                ids = {
                    str(value).strip().lower()
                    for value in (row.get("amenities") or [])
                    if isinstance(value, str) and _AMENITY_ID_PATTERN.fullmatch(value.strip().lower())
                }
                for amenity_id in ids:
                    counts[amenity_id] = counts.get(amenity_id, 0) + 1
            if len(page) < _CATALOG_PAGE_SIZE:
                break
            start += _CATALOG_PAGE_SIZE
    except Exception as exc:
        logger.warning("Hotel amenity coverage query failed: %s", type(exc).__name__)
        return {}

    _hotel_amenity_coverage_cache = (counts, now)
    return dict(counts)


def resolve_hotel_amenity_ids(values: Collection[object]) -> AmenityBindingResult:
    """Resolve chat-supplied hotel amenities to approved catalog IDs only.

    This lookup deliberately never invokes discovery: a request term that is
    not an unambiguous approved hotel/both catalog entry remains unresolved
    instead of becoming an unverified hard search constraint.
    """
    entries = all_approved_amenities()
    coverage = hotel_amenity_coverage()
    ids: list[str] = []
    unresolved: list[str] = []
    ambiguities: list[AmenityResolution] = []
    for raw in _valid_raw_values(values):
        resolution = resolve_hotel_amenity(raw, entries=entries, coverage=coverage)
        if resolution.status == "ambiguous":
            resolution = _choose_ambiguous_candidate(resolution)
        if resolution.status == "ambiguous":
            ambiguities.append(resolution)
        if resolution.status != "resolved" or resolution.candidate is None:
            if raw not in unresolved:
                unresolved.append(raw)
            continue
        if resolution.candidate.id not in ids:
            ids.append(resolution.candidate.id)
    return AmenityBindingResult(
        ids=tuple(ids), unresolved=tuple(unresolved), ambiguities=tuple(ambiguities)
    )


def resolve_hotel_amenity(
    phrase: str,
    *,
    entries: Collection[AmenityCatalogEntry] | None = None,
    coverage: dict[str, int] | None = None,
) -> AmenityResolution:
    """Resolve one phrase with lexical and semantic candidates.

    Embeddings only run for a phrase the deterministic matcher cannot decide.
    A semantic hit still has to clear a score and margin gate, and measured
    zero-coverage leaves are excluded. This keeps embeddings a candidate
    generator rather than an authority.
    """
    catalog = tuple(entries if entries is not None else all_approved_amenities())
    raw_coverage = coverage if coverage is not None else hotel_amenity_coverage()
    effective_coverage = _coverage_with_descendants(catalog, raw_coverage)
    eligible = tuple(
        entry for entry in catalog
        if _scope_is_eligible(entry.scope, "hotel") and effective_coverage.get(entry.id, 0) > 0
    )
    if not eligible:
        return AmenityResolution(phrase=phrase, status="unresolved")

    deterministic = _match_catalog_entry(phrase, eligible, "hotel", coverage=effective_coverage)
    if deterministic is not None:
        score = _catalog_match_score(phrase, deterministic)
        candidate = AmenityCandidate(
            deterministic.id, deterministic.label, score, 0.0,
            effective_coverage.get(deterministic.id, 0),
        )
        return AmenityResolution(phrase, "resolved", candidate, (candidate,))

    semantic_scores = _semantic_scores(phrase, eligible)
    ranked: list[AmenityCandidate] = []
    for index, entry in enumerate(eligible):
        lexical = _catalog_match_score(phrase, entry)
        semantic = semantic_scores[index] if index < len(semantic_scores) else 0.0
        ranked.append(AmenityCandidate(
            entry.id,
            entry.label,
            lexical,
            semantic,
            effective_coverage.get(entry.id, 0),
        ))
    ranked.sort(
        key=lambda item: (-(0.55 * item.lexical_score + 0.45 * item.semantic_score), -item.coverage, item.id)
    )
    top = tuple(ranked[:3])
    if not top:
        return AmenityResolution(phrase, "unresolved")
    combined = [0.55 * item.lexical_score + 0.45 * item.semantic_score for item in top]
    margin = combined[0] - (combined[1] if len(combined) > 1 else 0.0)
    if combined[0] >= 0.82 and margin >= 0.06:
        return AmenityResolution(phrase, "resolved", top[0], top)
    if combined[0] >= 0.62:
        return AmenityResolution(phrase, "ambiguous", candidates=top)
    return AmenityResolution(phrase, "unresolved", candidates=top)


def _coverage_with_descendants(
    entries: Collection[AmenityCatalogEntry], coverage: dict[str, int]
) -> dict[str, int]:
    """Give a zero-row parent the union signal of its covered descendants."""
    if not coverage:
        # A transient coverage-read outage must not make the whole approved
        # catalog look unused. Confirmed zeroes are guarded only when the map
        # itself was successfully populated.
        return {entry.id: 1 for entry in entries}

    children: dict[str, list[str]] = {}
    for entry in entries:
        if entry.parent_id:
            children.setdefault(entry.parent_id, []).append(entry.id)

    def total(amenity_id: str, seen: frozenset[str] = frozenset()) -> int:
        if amenity_id in seen:
            return 0
        return coverage.get(amenity_id, 0) + sum(
            total(child, seen | {amenity_id}) for child in children.get(amenity_id, ())
        )

    return {entry.id: total(entry.id) for entry in entries}


def _choose_ambiguous_candidate(resolution: AmenityResolution) -> AmenityResolution:
    """One bounded fast-model choice; output is constrained to supplied IDs."""
    allowed = {candidate.id: candidate for candidate in resolution.candidates}
    if not allowed:
        return resolution
    lexical = sorted((candidate.lexical_score for candidate in resolution.candidates), reverse=True)
    if lexical[0] < 0.75 or len(lexical) > 1 and lexical[0] - lexical[1] < 0.05:
        # The phrase itself supplies too little discriminating evidence. A
        # model choice here would merely turn an honest clarification into a
        # confident guess (for example "view đẹp" among several view types).
        return resolution
    try:
        response = get_fast_llm(temperature=0.0).invoke([
            SystemMessage(content=(
                "Choose the catalog amenity that exactly matches the user's phrase. "
                "Return JSON only. You may choose only a supplied id, or null when context is insufficient."
            )),
            HumanMessage(content=json.dumps({
                "phrase": resolution.phrase,
                "candidates": [
                    {"id": item.id, "label": item.label} for item in resolution.candidates
                ],
                "response_schema": {"id": "supplied id or null"},
            }, ensure_ascii=False)),
        ])
        payload = _parse_model_json(response_text(response))
        selected_id = payload.get("id") if isinstance(payload, dict) else None
    except Exception as exc:
        logger.info("Amenity ambiguity choice unavailable: %s", type(exc).__name__)
        return resolution
    selected = allowed.get(selected_id) if isinstance(selected_id, str) else None
    if selected is None:
        return resolution
    return AmenityResolution(
        phrase=resolution.phrase,
        status="resolved",
        candidate=selected,
        candidates=resolution.candidates,
    )


def _semantic_scores(
    phrase: str, entries: tuple[AmenityCatalogEntry, ...]
) -> tuple[float, ...]:
    global _catalog_embedding_cache
    signature = tuple(
        f"{entry.id}|{entry.label}|{entry.label_en}|{'|'.join(entry.match_keywords)}"
        for entry in entries
    )
    try:
        model = get_embeddings()
        if _catalog_embedding_cache is None or _catalog_embedding_cache[0] != signature:
            documents = [
                " | ".join((entry.label, entry.label_en, *entry.match_keywords))
                for entry in entries
            ]
            vectors = tuple(tuple(float(value) for value in vector) for vector in model.embed_documents(documents))
            _catalog_embedding_cache = (signature, vectors)
        query = tuple(float(value) for value in model.embed_query(phrase))
    except Exception as exc:
        logger.info("Amenity semantic candidates unavailable: %s", type(exc).__name__)
        return ()

    def cosine(vector: tuple[float, ...]) -> float:
        if len(vector) != len(query):
            return 0.0
        denominator = math.sqrt(sum(value * value for value in vector)) * math.sqrt(
            sum(value * value for value in query)
        )
        return max(0.0, sum(left * right for left, right in zip(vector, query)) / denominator) if denominator else 0.0

    return tuple(cosine(vector) for vector in _catalog_embedding_cache[1])


def expand_amenity_descendants(
    amenity_ids: Collection[str], *, scope: AmenityScope = "hotel"
) -> dict[str, frozenset[str]]:
    """Map each requested ID to itself plus reviewed descendants.

    Expansion is one-way: a general parent accepts a specific child; a child
    never accepts its parent or siblings. Scope filtering prevents room-only
    facilities from leaking into hotel predicates.
    """
    entries = all_approved_amenities()
    eligible = {
        entry.id: entry for entry in entries
        if _scope_is_eligible(entry.scope, scope)
    }
    children: dict[str, list[str]] = {}
    for entry in eligible.values():
        if entry.parent_id and entry.parent_id in eligible:
            children.setdefault(entry.parent_id, []).append(entry.id)

    expanded: dict[str, frozenset[str]] = {}
    for amenity_id in _valid_amenity_ids_unbounded(amenity_ids):
        seen = {amenity_id}
        stack = list(children.get(amenity_id, ()))
        while stack:
            child = stack.pop()
            if child in seen:
                continue
            seen.add(child)
            stack.extend(children.get(child, ()))
        expanded[amenity_id] = frozenset(seen)
    return expanded


def bind_amenities(
    values: Collection[object], *, scope: AmenityScope, persist: bool = True
) -> AmenityBindingResult:
    """Bind one amenity array through the page-safe catalog binder."""
    return bind_amenity_rows([values], scope=scope, persist=persist)[0]


def bind_amenity_rows(
    values_by_row: Collection[Collection[object]], *, scope: AmenityScope, persist: bool = True
) -> list[AmenityBindingResult]:
    """Bind a database page, deduplicating unknown raw values before model calls."""
    raw_rows = [_valid_raw_values(values) for values in values_by_row]
    entries = query_approved_amenities()
    entries_by_id = {entry.id: entry for entry in entries}
    known_ids: dict[str, str] = {}
    scope_promotions: dict[str, AmenityCatalogEntry] = {}
    unresolved: list[str] = []
    for raw_values in raw_rows:
        for raw in raw_values:
            if raw in known_ids:
                continue
            override_id = _ROOM_CANONICAL_OVERRIDES.get(_normalize_for_match(raw)) if scope == "room" else None
            existing_id = entries_by_id.get(override_id) or entries_by_id.get(raw.casefold())
            entry = existing_id if existing_id is not None and _scope_is_eligible(
                existing_id.scope, scope, allow_cross_scope=True
            ) else None
            entry = entry or _match_catalog_entry(raw, entries, scope, allow_cross_scope=True)
            if entry is None:
                if raw not in unresolved:
                    unresolved.append(raw)
            else:
                known_ids[raw] = entry.id
                if entry.scope != "both" and entry.scope != scope:
                    scope_promotions[entry.id] = entry

    discovered_by_raw: dict[str, str] = {}
    proposals_by_raw: dict[str, AmenityCatalogEntry] = {}
    for batch in _batches(unresolved, _MAX_DISCOVERY_CANDIDATES):
        candidates = _discovery_candidates(batch, reserved_ids=set(entries_by_id))
        discovered = discover_and_store_amenities(
            candidates, scope=scope, persist=persist, existing_entries=entries
        )
        for raw, candidate in zip(batch, candidates):
            entry = next((
                item for item in discovered if item.source_id == candidate["id"] or item.id == candidate["id"]
            ), None)
            if entry is not None and _scope_matches(entry.scope, scope):
                if entry.id in entries_by_id:
                    # A reviewed existing row may be reused immediately.
                    discovered_by_raw[raw] = entry.id
                else:
                    # A new row is only a staging proposal. Do not write its
                    # unapproved ID into hotel/room arrays before promotion.
                    proposals_by_raw[raw] = entry
        for entry in discovered:
            entries_by_id.setdefault(entry.id, entry)
        entries = list(entries_by_id.values())

    if persist and scope_promotions:
        try:
            get_supabase_client().table(_CATALOG_TABLE).upsert([
                {
                    "id": entry.id,
                    "label_vi": entry.label,
                    "label_en": entry.label_en,
                    "scope": "both",
                    "category": entry.category,
                    "icon_key": entry.icon_key,
                    "match_keywords": list(entry.match_keywords),
                    "is_approved": True,
                }
                for entry in scope_promotions.values()
            ], on_conflict="id").execute()
            clear_all_approved_amenities_cache()
        except Exception as exc:
            logger.warning("Amenity catalog scope promotion failed: %s", type(exc).__name__)

    results: list[AmenityBindingResult] = []
    for raw_values in raw_rows:
        ids: list[str] = []
        still_unresolved: list[str] = []
        proposals: list[AmenityCatalogEntry] = []
        for raw in raw_values:
            amenity_id = known_ids.get(raw) or discovered_by_raw.get(raw)
            proposal = proposals_by_raw.get(raw)
            if amenity_id is None:
                if raw not in still_unresolved:
                    still_unresolved.append(raw)
                if proposal is not None and proposal.id not in {item.id for item in proposals}:
                    proposals.append(proposal)
            elif amenity_id not in ids:
                ids.append(amenity_id)
                if proposal is not None and proposal.id not in {item.id for item in proposals}:
                    proposals.append(proposal)
        results.append(AmenityBindingResult(
            tuple(ids), tuple(still_unresolved), len(proposals), tuple(proposals)
        ))
    return results


def discover_and_store_amenities(
    candidates: Collection[dict[str, str]], *, scope: AmenityScope = "hotel", persist: bool = True,
    existing_entries: Collection[AmenityCatalogEntry] = (),
) -> list[AmenityCatalogEntry]:
    """Stage scope-compatible catalog proposals from unknown scraped values.

    Existing reviewed rows may receive aliases/scope promotion, but a newly
    invented row is always written with ``is_approved=false`` until a human
    review promotes it. Chat resolution never calls this function.
    """
    candidate_by_id = _valid_discovery_candidates(candidates)
    if not candidate_by_id:
        return []
    rows = _approved_discovery_rows(candidate_by_id, scope, existing_entries)
    if not rows:
        return []
    if persist:
        try:
            db_rows_by_id: dict[str, dict[str, object]] = {}
            for row in rows:
                db_row = {key: value for key, value in row.items() if key not in {"_source_id", "_existing"}}
                existing_row = db_rows_by_id.get(str(db_row["id"]))
                if existing_row is None:
                    db_rows_by_id[str(db_row["id"])] = db_row
                    continue
                existing_row["match_keywords"] = list(dict.fromkeys(
                    (*existing_row["match_keywords"], *db_row["match_keywords"])
                ))
            db_rows = list(db_rows_by_id.values())
            if db_rows:
                get_supabase_client().table(_CATALOG_TABLE).upsert(db_rows, on_conflict="id").execute()
                clear_all_approved_amenities_cache()
        except Exception as exc:
            logger.warning("Amenity catalog discovery write failed: %s", type(exc).__name__)
            return []
    return _parse_catalog_entries(rows)


def _approved_discovery_rows(
    candidate_by_id: dict[str, str], source_scope: AmenityScope, existing_entries: Collection[AmenityCatalogEntry] = ()
) -> list[dict[str, object]]:
    try:
        relevant_by_source = {
            source_id: _relevant_existing_entries([label], existing_entries, source_scope)
            for source_id, label in candidate_by_id.items()
        }
        relevant_entries_by_id = {
            entry["id"]: entry
            for entries in relevant_by_source.values()
            for entry in entries
        }
        response = get_fast_llm(temperature=0.0).invoke([
            SystemMessage(content=(
                "Classify unknown scraped hotel amenities. Return JSON only. A result must be a real "
                "hotel or room feature, service, facility, included offering, or spoken-language availability. For each candidate, "
                "choose category, an optional Material Symbol icon_key, 1-8 concise matching aliases, "
                "and a scope compatible with the source scope. Use a concise English canonical label, because "
                "the system derives the catalog ID from label_en. Aliases must identify this exact facility; "
                "Category must be one of accessibility, business, connectivity, facility, family, food, general, "
                "language, outdoor, policies, room_comfort, safety, transport, or wellness. Spoken languages "
                "must use category language. "
                "do not include broad parent terms that could match other facilities. If a candidate is the same "
                "meaning as an existing catalog entry, set existing_id to that listed catalog ID and is_amenity to false; "
                "never create a synonym or duplicate."
            )),
            HumanMessage(content=(
                'Return exactly {"amenities":[{"id":"submitted_id","existing_id":"listed_catalog_id"|null,"is_amenity":true|false,'
                '"label_vi":"...","label_en":"...","scope":"hotel|room|both",'
                '"category":"...","icon_key":"...|null","match_keywords":["..."]}]}. '
                "Use only submitted ids. For each candidate, existing_id may only be one of its eligible_existing_ids. "
                "Source scope is " + source_scope + ". Candidates: "
                + json.dumps([
                    {"id": key, "label": value, "eligible_existing_ids": [entry["id"] for entry in relevant_by_source[key]]}
                    for key, value in candidate_by_id.items()
                ], ensure_ascii=False)
                + ". Relevant existing catalog entries: "
                + json.dumps(list(relevant_entries_by_id.values()), ensure_ascii=False)
            )),
        ])
        payload = _parse_model_json(response_text(response))
    except Exception as exc:
        logger.warning("Amenity discovery classification failed: %s", type(exc).__name__)
        return []
    results = payload.get("amenities") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        return []
    rows: list[dict[str, object]] = []
    comparison_entries = list(existing_entries)
    existing_by_id = {entry.id: entry for entry in comparison_entries}
    used_ids: set[str] = set()
    for result in results:
        if not isinstance(result, dict):
            continue
        source_id = result.get("id")
        if not isinstance(source_id, str) or source_id not in candidate_by_id:
            continue
        selected_existing_id = result.get("existing_id")
        selected_existing = existing_by_id.get(selected_existing_id) if isinstance(selected_existing_id, str) else None
        if (
            selected_existing is not None
            and selected_existing_id in {entry["id"] for entry in relevant_by_source[source_id]}
            and _scope_is_eligible(selected_existing.scope, source_scope, allow_cross_scope=True)
        ):
            rows.append(_existing_catalog_row(selected_existing, source_id, candidate_by_id[source_id], source_scope))
            rows.extend(_conflicting_alias_rows(selected_existing, candidate_by_id[source_id], comparison_entries))
            continue
        if result.get("is_amenity") is not True:
            continue
        entry_scope = str(result.get("scope") or source_scope).strip().lower()
        if entry_scope not in {"hotel", "room", "both"} or not _scope_matches(entry_scope, source_scope):
            continue
        keywords = _validated_match_keywords(result.get("match_keywords"))
        label_vi = _bounded_label(result.get("label_vi")) or candidate_by_id[source_id]
        label_en = _bounded_label(result.get("label_en")) or label_vi
        keywords = _narrow_keywords(keywords, label_en)
        existing = (
            _match_catalog_entry(label_vi, comparison_entries, source_scope, allow_cross_scope=True)
            or _match_catalog_entry(label_en, comparison_entries, source_scope, allow_cross_scope=True)
            or _keyword_duplicate(keywords, comparison_entries, source_scope, allow_cross_scope=True)
        )
        if existing is not None:
            rows.append(_existing_catalog_row(existing, source_id, candidate_by_id[source_id], source_scope))
            rows.extend(_conflicting_alias_rows(existing, candidate_by_id[source_id], comparison_entries))
            continue
        amenity_id = _unique_canonical_id(label_en, used_ids)
        if amenity_id is None:
            continue
        if not keywords:
            keywords = [label_vi.lower()]
        row = {
            "id": amenity_id,
            "_source_id": source_id,
            "label_vi": label_vi,
            "label_en": label_en,
            "scope": entry_scope,
            "category": "language" if _is_spoken_language(label_vi, label_en) else _bounded_category(result.get("category")),
            "icon_key": _bounded_icon_key(result.get("icon_key")),
            "match_keywords": list(dict.fromkeys([*keywords, label_vi.lower()])),
            "is_approved": False,
        }
        rows.append(row)
        comparison_entries.extend(_parse_catalog_entries([row]))
    return rows


def _match_catalog_entry(
    raw: str,
    entries: Iterable[AmenityCatalogEntry],
    scope: AmenityScope,
    *,
    allow_cross_scope: bool = False,
    coverage: dict[str, int] | None = None,
) -> AmenityCatalogEntry | None:
    eligible = [entry for entry in entries if _scope_is_eligible(entry.scope, scope, allow_cross_scope=allow_cross_scope)]
    if coverage:
        # Explicitly measured zero-coverage rows can never satisfy a hotel
        # request. Unknown coverage (for a transient/partial read) retains the
        # old behavior; only confirmed zeroes are removed from contention.
        eligible = [entry for entry in eligible if coverage.get(entry.id) != 0]
    # An entry's OWN id/label/label_en is its identity; a `match_keywords`
    # hit is only a loose association (e.g. "sauna", "massage", and a dozen
    # other wellness entries all list bare "spa" as a keyword, alongside the
    # canonical `spa` entry whose id/label literally IS "spa"). Resolving
    # identity matches first, before the keyword-inclusive ambiguity check
    # below, is what lets a raw value that exactly names one entry bind to
    # it even though the plain keyword-overlap set is ambiguous -- reported:
    # "spa" came back unresolved despite an approved `spa` catalog row,
    # because 14 unrelated entries also carry "spa" as one keyword among
    # several and the old check gave every keyword hit equal weight to the
    # entry's own name.
    identity_matches = [entry for entry in eligible if _is_identity_match(raw, entry)]
    if len(identity_matches) == 1:
        return identity_matches[0]
    if len(identity_matches) > 1:
        return None

    scored = sorted(
        ((_catalog_match_score(raw, entry), entry) for entry in eligible),
        key=lambda item: (-item[0], item[1].id),
    )
    exact_matches = [entry for _, entry in scored if _is_exact_label_or_id(raw, entry)]
    if len(exact_matches) == 1:
        return exact_matches[0]
    if len(exact_matches) > 1 or not scored or scored[0][0] < 0.85:
        return None
    best_score, best_entry = scored[0]
    if len(scored) > 1 and best_score - scored[1][0] < 0.15:
        return None
    return best_entry


def _scope_matches(entry_scope: str, source_scope: AmenityScope) -> bool:
    return entry_scope in {source_scope, "both"}


def _scope_is_eligible(entry_scope: str, source_scope: AmenityScope, *, allow_cross_scope: bool = False) -> bool:
    return _scope_matches(entry_scope, source_scope) or allow_cross_scope and entry_scope in {"hotel", "room"}


def _valid_raw_values(values: Collection[object]) -> list[str]:
    result: list[str] = []
    for value in values:
        raw = value.strip() if isinstance(value, str) else ""
        if raw:
            result.append(raw)
    return result


def _discovery_candidates(values: Collection[str], *, reserved_ids: set[str] | None = None) -> list[dict[str, str]]:
    used = set(reserved_ids or ())
    candidates: list[dict[str, str]] = []
    for raw in values:
        base = re.sub(r"[^a-z0-9]+", "_", _normalize_for_match(raw)).strip("_")[:58] or "amenity"
        candidate_id = base
        index = 2
        while candidate_id in used:
            candidate_id = f"{base[:60]}_{index}"
            index += 1
        used.add(candidate_id)
        candidates.append({"id": candidate_id, "label": raw})
    return candidates


def _batches(values: Collection[str], size: int) -> Iterable[list[str]]:
    values = list(values)
    for start in range(0, len(values), size):
        yield values[start:start + size]


def _valid_discovery_candidates(candidates: Collection[dict[str, str]]) -> dict[str, str]:
    valid: dict[str, str] = {}
    for candidate in candidates:
        amenity_id = str(candidate.get("id") or "").strip().lower()
        label = str(candidate.get("label") or "").strip()
        if _AMENITY_ID_PATTERN.fullmatch(amenity_id) and label and len(label) <= _MAX_KEYWORD_LENGTH:
            valid.setdefault(amenity_id, label)
    return dict(list(valid.items())[:_MAX_DISCOVERY_CANDIDATES])


def _parse_model_json(content: object) -> object:
    if not isinstance(content, str):
        return {}
    text = content.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def _validated_match_keywords(value: object) -> list[str]:
    if not isinstance(value, list) or not 1 <= len(value) <= _MAX_MATCH_KEYWORDS:
        return []
    return list(dict.fromkeys(
        keyword.strip().lower() for keyword in value
        if isinstance(keyword, str) and 0 < len(keyword.strip()) <= _MAX_KEYWORD_LENGTH
    ))


def _narrow_keywords(keywords: list[str], label_en: str) -> list[str]:
    """Reject aliases broader than an outdoor-cooking facility's canonical meaning."""
    if "outdoor cooking" not in _normalize_for_match(label_en):
        return keywords
    return [keyword for keyword in keywords if "outdoor" in _normalize_for_match(keyword)]


def _is_spoken_language(label_vi: str, label_en: str) -> bool:
    return _normalize_for_match(label_vi).startswith("tieng ") or "language" in _normalize_for_match(label_en)


def _relevant_existing_entries(
    candidates: Collection[str], entries: Collection[AmenityCatalogEntry], scope: AmenityScope, *, allow_cross_scope: bool = True
) -> list[dict[str, str]]:
    candidate_terms = set().union(*(_match_terms(candidate) for candidate in candidates)) if candidates else set()
    ranked = [
        (len(candidate_terms & _match_terms(" ".join((entry.label, entry.label_en, *entry.match_keywords)))), entry)
        for entry in entries if _scope_is_eligible(entry.scope, scope, allow_cross_scope=allow_cross_scope)
    ]
    return [
        {"id": entry.id, "label_vi": entry.label, "label_en": entry.label_en}
        for score, entry in sorted(ranked, key=lambda item: (-item[0], item[1].id)) if score
    ][:20]


def _match_terms(value: str) -> set[str]:
    # Two-character tokens are KEPT (bug fix). Vietnamese is syllable-timed
    # and a great many of its meaningful syllables are exactly two letters
    # once diacritics are stripped -- "lê", "vị", "rẻ", "hồ", "bể". Dropping
    # them collapsed whole labels to a single token ("dép lê" -> {"dep"},
    # "gia vị" -> {"gia"}), and `_phrase_match_score`'s "every phrase token
    # is present" rule then fired on nothing more than that one token
    # appearing anywhere in the request: "view đẹp" resolved to slippers
    # (Dép lê) and "giá rẻ" to essential spices (Gia vị), each becoming a
    # hard, wrong search filter. Keeping the syllable restores the second
    # token that tells those pairs apart, and multi-syllable labels now go
    # through the strong subset rule instead of the weak single-token one.
    # One-character tokens stay dropped: they carry no such meaning.
    return {term for term in re.findall(r"[a-z0-9]+", _normalize_for_match(value)) if len(term) > 1}


def _keyword_duplicate(
    keywords: Collection[str], entries: Collection[AmenityCatalogEntry], scope: AmenityScope, *, allow_cross_scope: bool = False
) -> AmenityCatalogEntry | None:
    normalized_keywords = {_normalize_for_match(keyword) for keyword in keywords}
    matches = [
        entry for entry in entries
        if _scope_is_eligible(entry.scope, scope, allow_cross_scope=allow_cross_scope) and normalized_keywords & {
            _normalize_for_match(keyword) for keyword in entry.match_keywords
        }
    ]
    return matches[0] if len(matches) == 1 else None


def _catalog_match_score(raw: str, entry: AmenityCatalogEntry) -> float:
    normalized_raw = _normalize_for_match(raw)
    phrases = (entry.id.replace("_", " "), entry.label, entry.label_en, *entry.match_keywords)
    scores = [_phrase_match_score(normalized_raw, _normalize_for_match(phrase)) for phrase in phrases]
    return max(scores, default=0.0)


def _is_exact_label_or_id(raw: str, entry: AmenityCatalogEntry) -> bool:
    normalized_raw = _normalize_for_match(raw)
    return normalized_raw in {
        _normalize_for_match(entry.id.replace("_", " ")),
        _normalize_for_match(entry.label),
        _normalize_for_match(entry.label_en),
        *(_normalize_for_match(keyword) for keyword in entry.match_keywords),
    }


def _is_identity_match(raw: str, entry: AmenityCatalogEntry) -> bool:
    """Whether `raw` names this entry itself -- its id/label/label_en --
    as opposed to merely appearing in its `match_keywords` (see
    `_match_catalog_entry`'s identity-priority pass)."""
    normalized_raw = _normalize_for_match(raw)
    return normalized_raw in {
        _normalize_for_match(entry.id.replace("_", " ")),
        _normalize_for_match(entry.label),
        _normalize_for_match(entry.label_en),
    }


def _phrase_match_score(normalized_raw: str, normalized_phrase: str) -> float:
    if not normalized_phrase:
        return 0.0
    if normalized_raw == normalized_phrase:
        return 1.0
    raw_terms = _match_terms(normalized_raw)
    phrase_terms = _match_terms(normalized_phrase)
    if len(phrase_terms) > 1 and phrase_terms <= raw_terms:
        return 0.92
    if phrase_terms:
        overlap = len(raw_terms & phrase_terms) / len(phrase_terms)
        if overlap == 1:
            return 0.86
        if overlap >= 0.6:
            return 0.60 + (0.25 * overlap)
    return min(0.80, SequenceMatcher(None, normalized_raw, normalized_phrase).ratio())


def _existing_catalog_row(
    entry: AmenityCatalogEntry, source_id: str, source_label: str, source_scope: AmenityScope | None = None
) -> dict[str, object]:
    return {
        "id": entry.id,
        "_source_id": source_id,
        "_existing": True,
        "label_vi": entry.label,
        "label_en": entry.label_en,
        "scope": "both" if source_scope is not None and entry.scope != source_scope and entry.scope != "both" else entry.scope,
        "category": entry.category,
        "icon_key": entry.icon_key,
        "match_keywords": list(dict.fromkeys((*entry.match_keywords, source_label.lower()))),
        "is_approved": True,
    }


def _conflicting_alias_rows(
    selected: AmenityCatalogEntry, source_label: str, entries: Collection[AmenityCatalogEntry]
) -> list[dict[str, object]]:
    normalized_source = _normalize_for_match(source_label)
    rows: list[dict[str, object]] = []
    for entry in entries:
        if entry.id == selected.id or normalized_source in {
            _normalize_for_match(entry.id.replace("_", " ")),
            _normalize_for_match(entry.label),
            _normalize_for_match(entry.label_en),
        }:
            continue
        keywords = [keyword for keyword in entry.match_keywords if _normalize_for_match(keyword) != normalized_source]
        if len(keywords) == len(entry.match_keywords):
            continue
        rows.append({
            "id": entry.id,
            "label_vi": entry.label,
            "label_en": entry.label_en,
            "scope": entry.scope,
            "category": entry.category,
            "icon_key": entry.icon_key,
            "match_keywords": keywords,
            "is_approved": True,
        })
    return rows


def _bounded_label(value: object) -> str | None:
    value = value.strip() if isinstance(value, str) else ""
    return value if 0 < len(value) <= 80 else None


def _bounded_category(value: object) -> str:
    value = value.strip().lower() if isinstance(value, str) else ""
    return value if value in AMENITY_CATEGORIES else "general"


def _bounded_icon_key(value: object) -> str | None:
    value = value.strip() if isinstance(value, str) else ""
    return value if re.fullmatch(r"[a-z0-9_]{1,64}", value or "") else None


def _unique_canonical_id(label_en: str, used_ids: set[str]) -> str | None:
    base = re.sub(r"[^a-z0-9]+", "_", label_en.casefold()).strip("_")[:58]
    if not base:
        return None
    amenity_id = base
    suffix = 2
    while amenity_id in used_ids:
        amenity_id = f"{base[:60]}_{suffix}"
        suffix += 1
    used_ids.add(amenity_id)
    return amenity_id


def _normalize_for_match(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in normalized if not unicodedata.combining(char)).replace("đ", "d")


def _valid_amenity_ids(amenity_ids: Collection[str] | None) -> list[str]:
    return _valid_amenity_ids_unbounded(amenity_ids)[:_MAX_REQUESTED_IDS]


def _valid_amenity_ids_unbounded(amenity_ids: Collection[str] | None) -> list[str]:
    valid: list[str] = []
    for raw in amenity_ids or ():
        amenity_id = str(raw).strip().lower()
        if _AMENITY_ID_PATTERN.fullmatch(amenity_id) and amenity_id not in valid:
            valid.append(amenity_id)
    return valid


def _parse_catalog_entries(rows: Iterable[object]) -> list[AmenityCatalogEntry]:
    entries: list[AmenityCatalogEntry] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        amenity_id = row.get("id")
        label = row.get("label_vi")
        keywords = row.get("match_keywords")
        scope = row.get("scope")
        category = row.get("category")
        parent_id = row.get("parent_id")
        if not (isinstance(amenity_id, str) and _AMENITY_ID_PATTERN.fullmatch(amenity_id)
                and isinstance(label, str) and label.strip() and isinstance(keywords, list)
                and scope in {"hotel", "room", "both"} and isinstance(category, str) and category.strip()):
            continue
        parsed_keywords = tuple(keyword.strip().lower() for keyword in keywords if isinstance(keyword, str) and keyword.strip())
        if parsed_keywords:
            entries.append(AmenityCatalogEntry(
                id=amenity_id,
                label=label.strip(),
                match_keywords=parsed_keywords,
                label_en=str(row.get("label_en") or label).strip(),
                scope=scope,
                category=category.strip(),
                icon_key=row.get("icon_key") if isinstance(row.get("icon_key"), str) else None,
                source_id=row.get("_source_id") if isinstance(row.get("_source_id"), str) else None,
                parent_id=parent_id if isinstance(parent_id, str) and _AMENITY_ID_PATTERN.fullmatch(parent_id) else None,
            ))
    return entries
