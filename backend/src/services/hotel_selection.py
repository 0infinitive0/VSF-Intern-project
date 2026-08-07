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
                "review_score,review_count,address,area_name,lowest_price,currency,image_url,images,city"
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
            # Canonical rows supply stable hotel metadata, while the RPC is the
            # authority for the requested stay's price and room selection.
            hydrated.append({**canonical, **result})
    return hydrated


def select_hotel_candidates(
    destination: str,
    destination_id: str,
    people: str,
    hotel_query: str | None = None,
    match_count: int = 5,
    min_price: float | None = None,
    max_price: float | None = None,
    exclude_hotel_ids: Collection[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    root_latitude: float | None = None,
    root_longitude: float | None = None,
    max_radius_km: float | None = None,
) -> List[Tuple[Dict[str, Any], PlaceCandidate]]:
    """Search and return verified hotel options along with PlaceCandidate objects.

    Each returned tuple contains:
    1. hotel_data (Dict): Structured hotel details (id, name, rating, coordinates, matched rooms, covered meals).
    2. candidate (PlaceCandidate): Geo-located candidate object used by the itinerary scheduler.

    `min_price`/`max_price`, when given, are enforced directly by the search RPC (see
    scripts/migrations/20260730_add_price_filter_to_match_hotels_with_rooms.sql) — no
    app-side price filtering is needed here; `search_hotels_with_rooms` already returns
    the best `match_count` results that are also in range.
    """
    query = hotel_query or f"Hotel in {destination} for {people} people"
    kwargs: Dict[str, Any] = {
        "query": query,
        "match_count": match_count,
        "filter_destination_id": destination_id,
        "min_price": min_price,
        "max_price": max_price,
    }
    if start_date is not None or end_date is not None:
        kwargs["start_date"] = start_date
        kwargs["end_date"] = end_date
    if exclude_hotel_ids:
        kwargs["exclude_hotel_ids"] = list(exclude_hotel_ids)
    if root_latitude is not None or root_longitude is not None or max_radius_km is not None:
        kwargs["root_latitude"] = root_latitude
        kwargs["root_longitude"] = root_longitude
        kwargs["max_radius_km"] = max_radius_km

    search_results = search_hotels_with_rooms(**kwargs) or []

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
            "average_nightly_price": hotel.get("average_nightly_price"),
            "total_stay_price": hotel.get("total_stay_price"),
            "stay_night_count": hotel.get("stay_night_count"),
            "priced_room_name": hotel.get("priced_room_name"),
            "currency": hotel.get("currency"),
            "image_url": hotel.get("image_url"),
            "images": hotel.get("images") or [],
            "city": hotel.get("city"),
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
    price = data.get("average_nightly_price", data.get("lowest_price"))
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


def _match_reasons(
    data: Dict[str, Any],
    candidate: PlaceCandidate,
    target_price: float | None,
    amenity_prefs: Iterable[str],
    sea_view_hotel_ids: Collection[str],
) -> list[dict[str, float | str]]:
    """Return raw ranking evidence for the UI; display text remains frontend-owned."""
    reasons: list[dict[str, float | str]] = []
    price = data.get("average_nightly_price", data.get("lowest_price"))
    if _budget_bonus(data, target_price) > 0 and price is not None and target_price:
        reasons.append({"code": "budget_fit", "value": round(float(price) / target_price, 4)})
    if (review_score := data.get("review_score")) is not None and float(review_score) >= 8.0:
        reasons.append({"code": "high_rating", "value": float(review_score)})
    if (star_rating := data.get("star_rating")) is not None and float(star_rating) >= 4.0:
        reasons.append({"code": "star_rating", "value": float(star_rating)})
    matched_amenities = [
        tag
        for tag in amenity_prefs
        if hotel_matches_amenity_tag(data, tag, sea_view_hotel_ids)
    ]
    if matched_amenities:
        reasons.append({"code": "amenity_match", "value": ",".join(matched_amenities)})
    similarity = float(data.get("similarity") or candidate.similarity or 0.0)
    if similarity >= 0.75:
        reasons.append({"code": "strong_similarity", "value": round(similarity, 4)})
    area_name = str(data.get("area_name") or "").strip()
    normalized_area = _normalize_for_match(area_name)
    if area_name and any(term in normalized_area for term in ("downtown", "central", "trung tam", "city center")):
        reasons.append({"code": "near_center", "value": area_name})
    return reasons


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
        float(data.get("average_nightly_price", data.get("lowest_price")))
        for data, _ in options
        if data.get("average_nightly_price", data.get("lowest_price")) is not None
    ]
    min_price, max_price = (min(prices), max(prices)) if prices else (None, None)

    def _price_score(data: Dict[str, Any]) -> float:
        price = data.get("average_nightly_price", data.get("lowest_price"))
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
        final_score = _final_score(data, _candidate)
        data["rank"] = index
        data["recommendation_score"] = final_score
        data["match_score"] = round(min(1.0, final_score), 4)
        data["match_reasons"] = _match_reasons(
            data, _candidate, target_price, amenity_prefs, sea_view_hotel_ids
        )
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
    
    # 1. Exact ID match (used by frontend API)
    for data, candidate in options:
        if str(data.get("id")) == stripped:
            return data, candidate

    # 2. Number/rank match (used by LLM)
    # Check if the string is just a digit, or extract the digit if the string contains exactly one digit
    import re
    digits = re.findall(r'\d+', stripped)
    if len(digits) == 1:
        rank = int(digits[0])
        for data, candidate in options:
            if data.get("rank") == rank:
                return data, candidate

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
        "images": hotel.get("images") or [],
        "city": hotel.get("city"),
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
# The actual (min, max) bounds shown in each tier's label — "budget" has no floor
# ("dưới 800k"), "luxury" has no ceiling ("trên 2.5tr"); only "mid_range" is a
# closed range. Kept separate from _BUDGET_TIER_TARGET_VND because the target is a
# single point used for the ranking-bonus closeness score, while these bounds are
# used as the search's hard min/max price filter.
_BUDGET_TIER_RANGE_VND: dict[str, tuple[float | None, float | None]] = {
    "budget": (None, _BUDGET_TIER_MAX_VND),
    "mid_range": (_BUDGET_TIER_MAX_VND, _MID_RANGE_TIER_MAX_VND),
    "luxury": (_MID_RANGE_TIER_MAX_VND, None),
}

_QUALITATIVE_BUDGET_PHRASES: dict[str, tuple[str, ...]] = {
    "luxury": ("sang trong", "cao cap", "luxury", "5 sao", "xin xo", "sang chanh"),
    # "re" on its own covers "rẻ thôi"/"càng rẻ càng tốt"; a bare-word match is safe
    # because _normalize_for_match strips tones, and no other budget phrase contains it.
    "budget": ("tiet kiem", "gia re", "re", "binh dan", "gia thap", "vua tui tien"),
    "mid_range": ("tam trung", "vua phai", "trung binh"),
}

# "Anything goes" — a real answer meaning "don't filter by price", not a parse failure.
# Without these the reply falls through to None and the question is asked again, which
# reads as the bot ignoring them.
_NO_BUDGET_PREFERENCE_PHRASES: tuple[str, ...] = (
    "bao nhieu cung duoc",
    "sao cung duoc",
    "gi cung duoc",
    "the nao cung duoc",
    "khong quan tam",
    "tuy ban",
    "tuy ai",
    "khong co yeu cau",
)

_MILLION_UNIT = r"(?:trieu|tr\b)"


def _is_no_budget_preference(text: str) -> bool:
    normalized = _normalize_for_match(text)
    return any(phrase in normalized for phrase in _NO_BUDGET_PREFERENCE_PHRASES)


def _tier_budget(tier: str) -> tuple[float | None, float | None, float | None]:
    """(min_price, max_price, target_price) for a named budget tier — the first two
    drive the search's hard filter, the third drives rank_hotel_candidates' soft
    closeness bonus."""
    min_price, max_price = _BUDGET_TIER_RANGE_VND[tier]
    return min_price, max_price, _BUDGET_TIER_TARGET_VND[tier]


def _parse_free_text_price(text: str) -> float | None:
    """Best-effort Vietnamese money parser: "4 triệu" -> 4_000_000, "500 nghìn"/"500k"
    -> 500_000, "1tr5"/"1 triệu rưỡi" -> 1_500_000, a range like "2-3 triệu" -> its
    midpoint, or a plain 4+ digit number used as-is. Returns None if nothing matches
    (a short number like "2" from "2 người" is deliberately not treated as a price)."""
    normalized = _normalize_for_match(text)

    # A range ("2-3 triệu", "từ 1 đến 2 triệu") means the whole span, so aim at its
    # middle. Taking the last number instead — what a plain search does — silently
    # pins the user to the top of the range they gave.
    range_match = re.search(
        rf"(\d+(?:[.,]\d+)?)\s*(?:-|den|toi|đen)\s*(\d+(?:[.,]\d+)?)\s*{_MILLION_UNIT}",
        normalized,
    )
    if range_match:
        low = float(range_match.group(1).replace(",", "."))
        high = float(range_match.group(2).replace(",", "."))
        return (low + high) / 2 * 1_000_000

    # "1tr5" / "1 triệu rưỡi" / "1tr500" — the trailing part is a fraction of a
    # million, not a separate number. Checked before the plain million pattern,
    # which would otherwise stop at "1" and drop the half.
    # Bare "tr" here, no trailing \b: in "1tr5" the unit is followed by a digit, so
    # there is no word boundary to match. Requiring one drops exactly the no-space
    # form this pattern exists for. Safe because what follows must be "ruoi" or
    # digits, which "trong"/"trung" never are.
    half_match = re.search(r"(\d+)\s*(?:trieu|tr)\s*(?:ruoi|(\d{1,3}))", normalized)
    if half_match:
        whole = float(half_match.group(1))
        fraction_digits = half_match.group(2)
        fraction = float(f"0.{fraction_digits}") if fraction_digits else 0.5
        return (whole + fraction) * 1_000_000

    # No leading \b before "tr"/"k": a digit is itself a word character, so a
    # no-space form like "4tr"/"500k" has no boundary between the digit and the
    # unit letter — only the trailing \b (rejecting "trong", "trung", ...) is needed.
    million_match = re.search(rf"(\d+(?:[.,]\d+)?)\s*{_MILLION_UNIT}", normalized)
    if million_match:
        return float(million_match.group(1).replace(",", ".")) * 1_000_000
    thousand_match = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:nghin|ngan|k\b)", normalized)
    if thousand_match:
        return float(thousand_match.group(1).replace(",", ".")) * 1_000
    plain_match = re.search(r"\b(\d{4,})\b", normalized.replace(",", "").replace(".", ""))
    if plain_match:
        return float(plain_match.group(1))
    return None


def _parse_free_text_budget(reply: str) -> tuple[float | None, float | None, float | None] | None:
    """free_text_parser for the budget GuidedQuestion — used only when the reply
    doesn't match a numbered option, e.g. the user typed "4 triệu" instead of picking
    from the suggested tiers, or a qualitative phrase like "khách sạn sang trọng".

    Returns (min_price, max_price, target_price): a qualitative phrase resolves to
    its tier's real (min, max) bounds via _tier_budget; an explicit number has no
    natural range, so it becomes an open-floor ceiling (None, price, price).

    The tier phrase is checked FIRST: it is a stronger signal than a bare number,
    and the bare-number branch of _parse_free_text_price otherwise lets a date
    year like "2026" win over "tầm trung" in a combined message."""
    normalized = _normalize_for_match(reply)
    for tier, phrases in _QUALITATIVE_BUDGET_PHRASES.items():
        if any(phrase in normalized for phrase in phrases):
            return _tier_budget(tier)
    price = _parse_free_text_price(reply)
    if price is not None:
        return None, price, price
    return None


# The unit-bearing price shapes _parse_free_text_price accepts, WITHOUT its
# bare-4+digit fallback (a date year like "01/09/2026" must not count).
_BUDGET_SIGNAL_UNIT = re.compile(
    rf"(\d+(?:[.,]\d+)?)\s*(?:-|den|toi|đen)\s*(\d+(?:[.,]\d+)?)\s*{_MILLION_UNIT}"
    rf"|(\d+)\s*(?:trieu|tr)\s*(?:ruoi|\d{{1,3}})"
    rf"|(\d+(?:[.,]\d+)?)\s*{_MILLION_UNIT}"
    rf"|(\d+(?:[.,]\d+)?)\s*(?:nghin|ngan|k\b)"
)


def _has_budget_signal(text: str) -> bool:
    """True when the text plausibly answers the guided budget question — a skip
    phrase, a qualitative tier phrase, or an explicit money amount WITH a unit
    ("4 triệu", "500k", "2-3 triệu"). Used to gate the same-turn carry-through:
    the intake turn only attempts budget resolution when the message actually
    carries a budget signal, so a facts-only message (dates included) still
    defers the budget question to its own turn."""
    if _is_no_budget_preference(text):
        return True
    normalized = _normalize_for_match(text)
    if any(
        phrase in normalized
        for phrases in _QUALITATIVE_BUDGET_PHRASES.values()
        for phrase in phrases
    ):
        return True
    return _BUDGET_SIGNAL_UNIT.search(normalized) is not None


_BUDGET_QUESTION = GuidedQuestion(
    prompt=(
        "Bạn muốn mức giá khách sạn khoảng nào? Trả lời bằng số gợi ý bên dưới, hoặc "
        'cứ nói thẳng mức giá bạn muốn (vd "4 triệu"):'
    ),
    options=(
        GuidedOption(
            f"Tiết kiệm (dưới {_BUDGET_TIER_MAX_VND:,.0f} VND/đêm)",
            _tier_budget("budget"),
        ),
        GuidedOption(
            f"Tầm trung ({_BUDGET_TIER_MAX_VND:,.0f} - {_MID_RANGE_TIER_MAX_VND:,.0f} VND/đêm)",
            _tier_budget("mid_range"),
        ),
        GuidedOption(
            f"Cao cấp (trên {_MID_RANGE_TIER_MAX_VND:,.0f} VND/đêm)",
            _tier_budget("luxury"),
        ),
        GuidedOption("Bỏ qua, không cần lọc theo giá", None),
    ),
    free_text_parser=_parse_free_text_budget,
    required=True,
)

HotelPreferenceStage = Literal["pending_budget", "done"]


def budget_option_labels() -> tuple[str, ...]:
    """The exact option-label strings from `_BUDGET_QUESTION`, exposed for the
    frontend's budget/accommodation selector. The source of truth is the guided
    question constant — callers must read through this helper, never reach into
    the private constant or re-derive the tier thresholds."""
    return tuple(option.label for option in _BUDGET_QUESTION.options)


@dataclass(frozen=True)
class HotelPreferenceState:
    """Deterministic, in-memory (not persisted) sequencer over the guided budget
    question above — mirrors TripIntakeState's is_complete/next_question/
    with_message/tool_arguments shape, scoped to hotel preferences only."""

    stage: HotelPreferenceStage = "pending_budget"
    target_price: float | None = None
    min_price: float | None = None
    max_price: float | None = None

    @property
    def is_complete(self) -> bool:
        return self.stage == "done"

    def next_question(self, language: str = "vi") -> str | None:
        if self.stage == "pending_budget":
            return format_guided_question(_BUDGET_QUESTION, language=language)
        return None

    def suggestion_options(self) -> tuple[str, ...]:
        """Labels of the menu currently on offer, for a UI to render as tappable
        chips. Empty when no menu is pending — a caller must never infer chips by
        scanning reply text for numbered lines, because the model's own prose is
        full of numbered lists that are not menus."""
        if self.stage == "pending_budget":
            return tuple(option.label for option in _BUDGET_QUESTION.options)
        return ()

    def with_message(self, message: str) -> "HotelPreferenceState":
        if self.stage == "pending_budget":
            # "bao nhiêu cũng được" is an answer — accept it and move on with no price
            # filter. Left to the parser it returns None, indistinguishable from
            # gibberish, and the same question gets asked again.
            if _is_no_budget_preference(message):
                # Clear all three: "no preference" must leave the search unfiltered,
                # so min/max have to go too, not just the ranking target.
                return replace(
                    self, stage="done", target_price=None, min_price=None, max_price=None
                )
            resolved, values = resolve_guided_reply(_BUDGET_QUESTION, message)
            if not resolved:
                return self
            min_price = max_price = target_price = None
            if values:
                min_price, max_price, target_price = values[0]
            return replace(
                self,
                stage="done",
                target_price=target_price,
                min_price=min_price,
                max_price=max_price,
            )
        return self

    def tool_arguments(self) -> dict[str, str]:
        if not self.is_complete:
            raise ValueError("Budget preference is not resolved yet.")
        return {
            "target_price": str(self.target_price) if self.target_price is not None else "",
            "min_price": str(self.min_price) if self.min_price is not None else "",
            "max_price": str(self.max_price) if self.max_price is not None else "",
        }

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe representation for TripState. No tuple fields here, unlike
        TripIntakeState — a plain field-for-field dict is enough."""
        return {
            "stage": self.stage,
            "target_price": self.target_price,
            "min_price": self.min_price,
            "max_price": self.max_price,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HotelPreferenceState:
        return cls(
            stage=data.get("stage", "pending_budget"),
            target_price=data.get("target_price"),
            min_price=data.get("min_price"),
            max_price=data.get("max_price"),
        )


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
