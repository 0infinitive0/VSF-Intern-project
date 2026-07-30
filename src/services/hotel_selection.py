"""Hotel Selection Service.

Handles searching, filtering, meal amenity detection, and selecting verified
hotel candidates for itinerary planning.
"""

from __future__ import annotations

import logging
import os
import re
import unicodedata
from dataclasses import dataclass, replace
from typing import Any, Collection, Dict, Iterable, List, Literal, Tuple

from supabase import Client, create_client

from src.config import get_settings
from src.services.guided_question import (
    GuidedOption,
    GuidedQuestion,
    format_guided_question,
    resolve_guided_reply,
)
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
            "amenities": hotel.get("amenities") or [],
        }
        options.append((hotel_data, candidate))

    return options


_BUDGET_MATCH_BONUS = 0.05
_AMENITY_MATCH_BONUS = 0.03


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(value, high))


def _composite_score(data: Dict[str, Any], candidate: PlaceCandidate, price_score: float) -> float:
    similarity_score = _clamp(float(data.get("similarity") or candidate.similarity or 0.0))
    rating_score = _clamp(float(data.get("star_rating") or 0.0) / 5.0)
    review_score_norm = _clamp(float(data.get("review_score") or 0.0) / 10.0)
    return (
        0.55 * similarity_score
        + 0.20 * rating_score
        + 0.15 * review_score_norm
        + 0.10 * price_score
    )


def _budget_bonus(data: Dict[str, Any], target_price: float | None) -> float:
    """Continuous closeness bonus, not a binary tier match — a hotel priced right at
    target_price gets the full bonus, decaying linearly to 0 the further away it is.
    Never negative: missing price or no target both contribute exactly 0.0."""
    price = data.get("lowest_price")
    if target_price is None or price is None or target_price <= 0:
        return 0.0
    diff_ratio = abs(float(price) - target_price) / target_price
    return _BUDGET_MATCH_BONUS * max(0.0, 1.0 - diff_ratio)


def _amenity_bonus(
    data: Dict[str, Any],
    amenity_prefs: Iterable[str],
    sea_view_hotel_ids: Collection[str],
) -> float:
    matched = sum(
        1 for tag in amenity_prefs if hotel_matches_amenity_tag(data, tag, sea_view_hotel_ids)
    )
    return _AMENITY_MATCH_BONUS * matched


def rank_hotel_candidates(
    options: List[Tuple[Dict[str, Any], PlaceCandidate]],
    *,
    target_price: float | None = None,
    amenity_prefs: Iterable[str] = (),
    sea_view_hotel_ids: Collection[str] = frozenset(),
) -> List[Tuple[Dict[str, Any], PlaceCandidate]]:
    """Sort search results by a weighted blend of similarity, rating, review score, price,
    and (optionally) how well each hotel matches the user's stated budget/amenity preferences.

    Similarity stays dominant (0.55) since it reflects how well the hotel matches what the
    user asked for; rating/review/price only refine the order among otherwise-similar hits.
    Preference bonuses (budget closeness, matched amenity tags) are additive and small
    (max 0.20 combined) so they can reorder near-ties without ever outweighing a much
    better semantic match. When target_price/amenity_prefs/sea_view_hotel_ids are all
    left at their defaults, every bonus is exactly 0.0 and results are identical to
    calling this function with no preferences at all — soft-boost only, never a penalty.
    """
    if not options:
        return []

    amenity_prefs = tuple(amenity_prefs)

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

    def _final_score(data: Dict[str, Any], candidate: PlaceCandidate) -> float:
        base = _composite_score(data, candidate, _price_score(data))
        return (
            base
            + _budget_bonus(data, target_price)
            + _amenity_bonus(data, amenity_prefs, sea_view_hotel_ids)
        )

    ranked = sorted(
        options,
        key=lambda option: _final_score(option[0], option[1]),
        reverse=True,
    )
    for index, (data, _candidate) in enumerate(ranked, start=1):
        data["rank"] = index
        data["recommendation_score"] = _final_score(data, _candidate)
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
        "amenities": hotel.get("amenities") or [],
    }
    return hotel_data, candidate


# ---------------------------------------------------------------------------
# Guided budget preference intake (shown before the hotel list) and the
# sea-view lookup + amenity matching used to soft-boost ranking above (still
# usable via rank_hotel_candidates(amenity_prefs=...), just no longer asked
# for through a dedicated guided question here).
# ---------------------------------------------------------------------------

# Mirrors hotel_pipeline.py::compute_price_tier's thresholds (ETL-side, unused by
# the live app) — duplicated rather than imported, since importing the Airflow DAG
# package into the live chat app would be an awkward dependency direction.
_BUDGET_TIER_MAX_VND = 800_000
_MID_RANGE_TIER_MAX_VND = 2_500_000
_BUDGET_TIER_TARGET_VND: dict[str, float] = {
    "budget": 500_000,
    "mid_range": 1_500_000,
    "luxury": 3_500_000,
}

_QUALITATIVE_BUDGET_PHRASES: dict[str, tuple[str, ...]] = {
    "luxury": ("sang trong", "cao cap", "luxury", "5 sao"),
    "budget": ("tiet kiem", "gia re"),
    "mid_range": ("tam trung", "vua phai", "trung binh"),
}


def _parse_free_text_price(text: str) -> float | None:
    """Best-effort Vietnamese money parser: "4 triệu" -> 4_000_000, "500 nghìn"/"500k"
    -> 500_000, or a plain 4+ digit number used as-is. Returns None if nothing matches
    (a short number like "2" from "2 người" is deliberately not treated as a price)."""
    normalized = _normalize_for_match(text)
    # No leading \b before "tr"/"k": a digit is itself a word character, so a
    # no-space form like "4tr"/"500k" has no boundary between the digit and the
    # unit letter — only the trailing \b (rejecting "trong", "trung", ...) is needed.
    million_match = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:trieu|tr\b)", normalized)
    if million_match:
        return float(million_match.group(1).replace(",", ".")) * 1_000_000
    thousand_match = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:nghin|ngan|k\b)", normalized)
    if thousand_match:
        return float(thousand_match.group(1).replace(",", ".")) * 1_000
    plain_match = re.search(r"\b(\d{4,})\b", normalized.replace(",", "").replace(".", ""))
    if plain_match:
        return float(plain_match.group(1))
    return None


def _parse_free_text_budget(reply: str) -> float | None:
    """free_text_parser for the budget GuidedQuestion — used only when the reply
    doesn't match a numbered option, e.g. the user typed "4 triệu" instead of picking
    from the suggested tiers, or a qualitative phrase like "khách sạn sang trọng"."""
    price = _parse_free_text_price(reply)
    if price is not None:
        return price
    normalized = _normalize_for_match(reply)
    for tier, phrases in _QUALITATIVE_BUDGET_PHRASES.items():
        if any(phrase in normalized for phrase in phrases):
            return _BUDGET_TIER_TARGET_VND[tier]
    return None


_BUDGET_QUESTION = GuidedQuestion(
    prompt=(
        "Bạn muốn mức giá khách sạn khoảng nào? Trả lời bằng số gợi ý bên dưới, hoặc "
        'cứ nói thẳng mức giá bạn muốn (vd "4 triệu"):'
    ),
    options=(
        GuidedOption(
            f"Tiết kiệm (dưới {_BUDGET_TIER_MAX_VND:,.0f} VND/đêm)",
            _BUDGET_TIER_TARGET_VND["budget"],
        ),
        GuidedOption(
            f"Tầm trung ({_BUDGET_TIER_MAX_VND:,.0f} - {_MID_RANGE_TIER_MAX_VND:,.0f} VND/đêm)",
            _BUDGET_TIER_TARGET_VND["mid_range"],
        ),
        GuidedOption(
            f"Cao cấp (trên {_MID_RANGE_TIER_MAX_VND:,.0f} VND/đêm)",
            _BUDGET_TIER_TARGET_VND["luxury"],
        ),
        GuidedOption("Bỏ qua, không cần lọc theo giá", None),
    ),
    free_text_parser=_parse_free_text_budget,
    required=True,
)

HotelPreferenceStage = Literal["pending_budget", "done"]


@dataclass(frozen=True)
class HotelPreferenceState:
    """Deterministic, in-memory (not persisted) sequencer over the guided budget
    question above — mirrors TripIntakeState's is_complete/next_question/
    with_message/tool_arguments shape, scoped to hotel preferences only."""

    stage: HotelPreferenceStage = "pending_budget"
    target_price: float | None = None

    @property
    def is_complete(self) -> bool:
        return self.stage == "done"

    def next_question(self) -> str | None:
        if self.stage == "pending_budget":
            return format_guided_question(_BUDGET_QUESTION)
        return None

    def with_message(self, message: str) -> "HotelPreferenceState":
        if self.stage == "pending_budget":
            resolved, values = resolve_guided_reply(_BUDGET_QUESTION, message)
            if not resolved:
                return self
            return replace(
                self,
                stage="done",
                target_price=values[0] if values else None,
            )
        return self

    def tool_arguments(self) -> dict[str, str]:
        if not self.is_complete:
            raise ValueError("Budget preference is not resolved yet.")
        return {
            "target_price": str(self.target_price) if self.target_price is not None else "",
        }


_AMENITY_KEYWORD_TAGS: dict[str, tuple[str, ...]] = {
    # Must require the negation phrase — a hotel whose only relevant amenity is
    # "Khu vực hút thuốc" (a smoking area exists) must NOT match non_smoking.
    "non_smoking": ("khong hut thuoc", "non smoking", "non-smoking", "no smoking"),
    "pool": ("ho boi", "be boi", "swimming pool", "pool"),
    "family": ("gia dinh", "tre em", "kids club", "family room"),
}


def hotel_matches_amenity_tag(
    data: Dict[str, Any],
    tag: str,
    sea_view_hotel_ids: Collection[str] = frozenset(),
) -> bool:
    """Pure predicate: does this hotel satisfy the given preference tag? Missing
    data, an unrecognized tag, or simply no match all resolve to False — never
    raises, and never penalizes (callers only ever add a bonus for True)."""
    if tag == "sea_view":
        hotel_id = data.get("id")
        return hotel_id is not None and str(hotel_id) in sea_view_hotel_ids
    if tag == "breakfast":
        return "breakfast" in (data.get("covered_meals") or [])
    keywords = _AMENITY_KEYWORD_TAGS.get(tag)
    if not keywords:
        return False
    amenities_text = " ".join(str(item) for item in (data.get("amenities") or []))
    normalized = _normalize_for_match(amenities_text)
    return any(keyword in normalized for keyword in keywords)


def lookup_sea_view_hotel_ids(hotel_ids: List[str]) -> frozenset[str]:
    """Batch-check the `rooms` table for sea-view rooms among the given hotel ids.

    The compact hotel search RPC (match_hotels_with_rooms) never returns room-level
    `view`, so sea-view can't be read off an existing search result — this is a
    separate, explicit lookup, only worth calling when a caller actually requested
    the sea_view tag. Fails open (empty set) on any error, consistent with
    _hydrate_hotel_records's own error handling."""
    if not hotel_ids:
        return frozenset()
    try:
        supabase = _get_supabase_client()
        response = (
            supabase.table("rooms")
            .select("hotel_id,view")
            .in_("hotel_id", [str(hotel_id) for hotel_id in hotel_ids])
            .execute()
        )
    except Exception as exc:
        logger.error("Failed to look up sea-view rooms: %s", exc)
        return frozenset()

    matched: set[str] = set()
    for row in response.data or []:
        view = row.get("view")
        hotel_id = row.get("hotel_id")
        if not view or not hotel_id:
            continue
        if "bien" in _normalize_for_match(str(view)):
            matched.add(str(hotel_id))
    return frozenset(matched)
