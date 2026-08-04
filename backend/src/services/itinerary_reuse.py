"""Pure contracts and deterministic safety checks for itinerary reuse.

This module deliberately has no Supabase or Ollama imports.  Retrieval is only
allowed to propose a template; callers must hydrate and repair the candidate
with the trip scheduler before presenting it to a traveller.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any, Literal

EMBEDDING_DIMENSION = 1024
MINIMUM_ITEMS_PER_DAY = 7
VALID_ITEM_KINDS = frozenset(
    {"breakfast", "attraction", "lunch", "rest", "coffee", "dinner", "evening"}
)
HUMAN_LABELS = {
    "breakfast": "bữa sáng",
    "attraction": "tham quan",
    "lunch": "bữa trưa",
    "rest": "nghỉ ngơi",
    "coffee": "nghỉ tại quán cà phê",
    "dinner": "bữa tối",
    "evening": "hoạt động nhẹ buổi tối",
}


def _canonical_text(value: object) -> str:
    """Normalize human text for stable summaries without changing its meaning."""

    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", str(value or "")).strip())


def _normalized_terms(values: Iterable[object]) -> tuple[str, ...]:
    terms = {_canonical_text(value).casefold() for value in values if _canonical_text(value)}
    return tuple(sorted(terms))


def _string_list(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Iterable):
        return tuple(str(item) for item in value)
    return ()


def _human_labels(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(HUMAN_LABELS.get(value, value) for value in values)


def _canonical_constraints(value: Mapping[str, Any] | None) -> str:
    if not value:
        return "none"
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class ItineraryReuseQuery:
    """Stable, explicit input for Tier 1 itinerary retrieval."""

    destination_id: str
    destination_name: str
    duration_days: int
    number_of_adults: int = 1
    number_of_children: int = 0
    preferences: tuple[str, ...] = ()
    child_focused: bool = False
    hotel_id: str | None = None
    planning_constraints: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReuseFingerprint:
    summary: str
    content_hash: str


@dataclass(frozen=True)
class ItineraryTemplate:
    """A database candidate, represented without any database client details."""

    id: str
    destination_id: str
    hotel_id: str | None
    duration_days: int
    number_of_adults: int = 1
    number_of_children: int = 0
    preferences: tuple[str, ...] = ()
    day_themes: tuple[Mapping[str, Any], ...] = ()
    items: tuple[Mapping[str, Any], ...] = ()
    status: str = "Finalized"
    similarity: float = 0.0
    parent_itinerary_id: str | None = None
    reuse_root_id: str | None = None
    reuse_count: int = 0
    summary: str | None = None
    planning_constraints: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReuseDecision:
    action: Literal["reuse", "miss"]
    reason: str
    template_id: str | None = None
    day_themes: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)


def build_reuse_fingerprint(query: ItineraryReuseQuery) -> ReuseFingerprint:
    """Return reproducible retrieval text and a content hash for one request."""

    summary = " | ".join(
        (
            f"destination_id={_canonical_text(query.destination_id)}",
            f"destination={_canonical_text(query.destination_name).casefold()}",
            f"duration_days={int(query.duration_days)}",
            f"adults={int(query.number_of_adults)}",
            f"children={int(query.number_of_children)}",
            f"child_focused={str(bool(query.child_focused)).lower()}",
            f"preferences={','.join(_normalized_terms(query.preferences)) or 'none'}",
            f"planning_constraints={_canonical_constraints(query.planning_constraints)}",
        )
    )
    return ReuseFingerprint(summary=summary, content_hash=sha256(summary.encode("utf-8")).hexdigest())


def build_itinerary_summary(
    query: ItineraryReuseQuery,
    *,
    day_themes: Sequence[Mapping[str, Any]],
    hotel: Mapping[str, Any],
    items: Sequence[Mapping[str, Any]],
    budget: object = None,
) -> str:
    """Create deterministic, human-readable text persisted for embedding."""

    destination = _canonical_text(query.destination_name) or "điểm đến chưa xác định"
    traveler_parts = [f"{int(query.number_of_adults)} người lớn"]
    if query.number_of_children:
        traveler_parts.append(f"{int(query.number_of_children)} trẻ em")
    parts = [
        f"Chuyến đi {int(query.duration_days)} ngày tại {destination} "
        f"dành cho {' và '.join(traveler_parts)}."
    ]

    preferences = _normalized_terms(query.preferences)
    if preferences:
        parts.append(f"Sở thích: {', '.join(preferences)}.")
    if query.child_focused:
        parts.append("Chuyến đi ưu tiên trải nghiệm phù hợp với trẻ em.")
    cutoff_by_day = query.planning_constraints.get("latest_outing_start_by_day") or {}
    if isinstance(cutoff_by_day, Mapping) and cutoff_by_day:
        cutoff_text = ", ".join(
            f"ngày {day}: {cutoff}"
            for day, cutoff in sorted(
                cutoff_by_day.items(), key=lambda value: int(value[0])
            )
        )
        parts.append(f"Giờ bắt đầu điểm đi chơi muộn nhất: {cutoff_text}.")

    meals = _normalized_terms(_string_list(hotel.get("covered_meals")))
    star = _canonical_text(hotel.get("star_rating"))
    if star:
        meal_text = ", ".join(_human_labels(meals)) if meals else "không có"
        parts.append(f"Khách sạn: {star} sao; bao gồm bữa ăn: {meal_text}.")
    elif meals:
        parts.append(f"Khách sạn bao gồm bữa ăn: {', '.join(_human_labels(meals))}.")

    themes: list[str] = []
    for theme in sorted(day_themes, key=lambda value: int(value.get("day_number") or 0)):
        day = int(theme.get("day_number") or 0)
        title = _canonical_text(theme.get("title"))
        theme_query = _canonical_text(theme.get("query"))
        if day and (title or theme_query):
            description = f"{title} — {theme_query}" if title and theme_query else title or theme_query
            themes.append(f"Ngày {day}: {description}.")
    parts.extend(themes)

    kinds = _normalized_terms(item.get("item_kind") or item.get("kind") for item in items)
    categories = _normalized_terms(item.get("category") for item in items)
    if kinds:
        parts.append(f"Hoạt động trong lịch trình: {', '.join(_human_labels(kinds))}.")
    if categories:
        parts.append(f"Nhóm địa điểm: {', '.join(categories)}.")
    if budget not in (None, "", 0, 0.0):
        parts.append(f"Ngân sách: {_canonical_text(budget)}.")
    return " ".join(parts)


def validate_template_bundle(template: ItineraryTemplate) -> tuple[bool, tuple[str, ...]]:
    """Validate only immutable bundle completeness before runtime hydration.

    Venue existence, coordinates, hours and policy conformance are intentionally
    checked after loading current records in the planner.
    """

    reasons: list[str] = []
    if not template.id:
        reasons.append("missing_template_id")
    if not template.destination_id:
        reasons.append("missing_destination")
    if not template.hotel_id:
        reasons.append("missing_hotel")
    if template.duration_days < 1:
        reasons.append("invalid_duration")
    if len(template.day_themes) != template.duration_days:
        reasons.append("incomplete_day_themes")

    items_by_day: dict[int, list[Mapping[str, Any]]] = {}
    for item in template.items:
        try:
            day = int(item.get("day_number") or 0)
        except (TypeError, ValueError):
            day = 0
        items_by_day.setdefault(day, []).append(item)
        if not item.get("reference_id") or not item.get("reference_type"):
            reasons.append("missing_item_reference")
        kind = str(item.get("item_kind") or item.get("kind") or "")
        if kind not in VALID_ITEM_KINDS:
            reasons.append("invalid_item_kind")

    for day in range(1, template.duration_days + 1):
        if len(items_by_day.get(day, [])) < MINIMUM_ITEMS_PER_DAY:
            reasons.append(f"incomplete_day_{day}")
    if 0 in items_by_day:
        reasons.append("invalid_day_number")

    return not reasons, tuple(dict.fromkeys(reasons))


def classify_reuse_candidate(
    template: ItineraryTemplate,
    query: ItineraryReuseQuery,
    *,
    threshold: float,
) -> ReuseDecision:
    """Return a conservative Tier 1 decision without performing side effects."""

    if template.destination_id != query.destination_id:
        return ReuseDecision("miss", "destination_mismatch")
    if not query.hotel_id or template.hotel_id != query.hotel_id:
        return ReuseDecision("miss", "hotel_mismatch")
    if template.duration_days != query.duration_days:
        return ReuseDecision("miss", "duration_mismatch")
    if _canonical_constraints(template.planning_constraints) != _canonical_constraints(
        query.planning_constraints
    ):
        return ReuseDecision("miss", "planning_constraints_mismatch")
    if template.status != "Finalized":
        return ReuseDecision("miss", "not_finalized")
    if template.similarity < threshold:
        return ReuseDecision("miss", "below_threshold")
    valid, reasons = validate_template_bundle(template)
    if not valid:
        return ReuseDecision("miss", reasons[0])
    return ReuseDecision("reuse", "qualified", template.id, template.day_themes)
