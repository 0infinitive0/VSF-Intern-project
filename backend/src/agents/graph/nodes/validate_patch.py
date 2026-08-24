"""`validate_patch` — runs the Phase 3 patch layer's validators.

Computes what applying `state["patch"]` *would* produce without committing
it: the result lands in `proposed_travel_state`, and `apply_patch` (the
node, `nodes/apply_patch.py`) is the only one that writes `travel_state`.

A date-shaped patch value used to be able to come back genuinely ambiguous
(day/month order, e.g. "1-2"), which needed an `interrupt()` here to ask the
user which reading they meant. `domain.travel_state._resolve_numeric_date`
no longer produces that ambiguity -- it always prefers the DD-MM
(Vietnamese) reading -- so `apply_patch` never raises it and this node never
pauses. `interrupt()`/`Command(resume=...)` is still real graph
infrastructure (see `agents/graph/nodes/hotel_node.py` for a live user of
it), just not needed here anymore.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from src.agents.graph.state import TravelGraphState
from src.domain.travel_state import Presence, TravelState, apply_patch, detect_impact, trip_duration_days
from src.services.amenity_catalog import all_approved_amenities, resolve_hotel_amenity_ids

logger = logging.getLogger(__name__)


def _bind_amenity_patch(
    changes: list[dict[str, Any]], travel_state: TravelState
) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]]]:
    """Resolve raw amenity phrases once, before they enter TravelState."""
    catalog = {entry.id: entry for entry in all_approved_amenities()}
    bound: list[dict[str, Any]] = []
    unresolved: list[str] = []
    ambiguities: list[dict[str, Any]] = []

    for change in changes:
        if change.get("path") != "hotel_preferences.amenities":
            bound.append(change)
            continue
        operation = change.get("operation")
        raw_value = change.get("value")
        # Be defensive even when callers bypass extract_patch: list-valued
        # append/remove means one operation per item, never one stringified
        # Python list that disappears as an unresolved phrase.
        raw_items = raw_value if isinstance(raw_value, list) else [raw_value]
        bound_items: list[dict[str, Any]] = []
        for raw_item in raw_items:
            if isinstance(raw_item, dict) and "id" in raw_item:
                bound_items.append(raw_item)
                continue
            phrase = (
                str(raw_item.get("phrase") or "").strip()
                if isinstance(raw_item, dict)
                else str(raw_item or "").strip()
            )
            polarity = (
                str(raw_item.get("polarity") or "require")
                if isinstance(raw_item, dict)
                else "require"
            )
            if not phrase:
                continue
            resolution = resolve_hotel_amenity_ids([phrase])
            for ambiguity in resolution.ambiguities:
                ambiguities.append({
                    "phrase": ambiguity.phrase,
                    "candidates": [
                        {"id": candidate.id, "label": candidate.label}
                        for candidate in ambiguity.candidates
                    ],
                })
            if not resolution.ids:
                if not resolution.ambiguities and phrase not in unresolved:
                    unresolved.append(phrase)
                continue
            for amenity_id in resolution.ids:
                entry = catalog.get(amenity_id)
                if entry is None:
                    continue
                bound_items.append({
                    "id": amenity_id,
                    "label": entry.label,
                    "polarity": polarity,
                    "source_phrase": phrase,
                    "confidence": 1.0,
                })

        if operation == "set":
            if bound_items:
                bound.append({**change, "value": bound_items})
            elif raw_value == []:
                bound.append({**change, "value": []})
        else:
            existing = travel_state.get("hotel_preferences.amenities").value or []
            existing_by_id = {
                str(item.get("id")): item for item in existing if isinstance(item, dict) and item.get("id")
            }
            for item in bound_items:
                amenity_id = str(item["id"])
                current = existing_by_id.get(amenity_id)
                if operation == "remove" and current is None:
                    # A negative statement against an empty slot is a durable
                    # exclusion, not an invalid removal from nothing.
                    bound.append({"path": change["path"], "operation": "append", "value": {**item, "polarity": "exclude"}})
                    continue
                if operation == "append" and current is not None and current.get("polarity") != item.get("polarity"):
                    bound.append({"path": change["path"], "operation": "remove", "value": current})
                bound.append({**change, "value": item})
    return bound, unresolved, ambiguities

# A "khoảng X" / "tầm X" answer only ever sets budget.target (a single
# preferred price, prompts.py's per-field contract) -- it never touches
# budget.min/budget.max on its own, so without this those slots stay
# UNKNOWN and the frontend's dual-thumb slider has nothing to draw, and the
# hotel search RPC (hotel_selection.py's min_price/max_price, enforced
# server-side) applies no price filter at all for a chat-only budget
# answer. Deriving a band around the target fixes both. The floor keeps
# very low targets from producing a degenerate near-zero band; the
# percentage keeps high targets from being filtered too tightly.
_BUDGET_TARGET_TOLERANCE_FLOOR_VND = 100_000
_BUDGET_TARGET_TOLERANCE_RATIO = 0.2


def _derive_budget_range_from_target(
    patch: list[dict[str, Any]], travel_state: TravelState
) -> list[dict[str, Any]]:
    """budget.min/budget.max patches to append when this turn set a bare
    budget.target and nothing -- this patch or a prior turn -- has already
    given min/max an explicit value. Never overrides an explicit range: a
    user who separately said "2-3 triệu/đêm" keeps exactly that band."""
    target_value: Any = None
    touches_range = False
    for change in patch:
        path = change.get("path")
        if path == "budget.target" and change.get("operation") == "set":
            target_value = change.get("value")
        elif path in ("budget.min", "budget.max"):
            touches_range = True
    if touches_range or not isinstance(target_value, (int, float)):
        return []
    if (
        travel_state.get("budget.min").presence is Presence.SET
        or travel_state.get("budget.max").presence is Presence.SET
    ):
        return []

    target = float(target_value)
    tolerance = max(_BUDGET_TARGET_TOLERANCE_FLOOR_VND, _BUDGET_TARGET_TOLERANCE_RATIO * target)
    return [
        {"path": "budget.min", "operation": "set", "value": max(0.0, target - tolerance)},
        {"path": "budget.max", "operation": "set", "value": target + tolerance},
    ]


def _derive_budget_range_from_trip_total(
    patch: list[dict[str, Any]], travel_state: TravelState, prospective_state: TravelState
) -> list[dict[str, Any]]:
    """budget.min/budget.max patches to append when a whole-trip
    `budget.trip_total` is known -- set this turn or a prior one -- and no
    per-night budget (`min`/`max`/`target`) has an explicit value yet.

    `hotel_node` filters its search on `budget.min`/`budget.max` only
    (`budget.target` feeds ranking, not the RPC's price filter -- see
    `nodes/hotel_node.py`); a `trip_total`-only turn otherwise leaves that
    filter empty and `budget_check` doesn't get a chance to correct it until
    AFTER a first, unconstrained search already ran. Deriving the band up
    front, the same way `_derive_budget_range_from_target` turns a bare
    target into one, means the very first hotel search is already scoped.

    Read off `travel_state` (not just this turn's `patch`) so the
    conversion still fires on a later turn that supplies the missing dates
    for a `trip_total` stated earlier, without the user having to repeat the
    figure. `prospective_state` is `patch` already applied to `travel_state`
    (computed by the caller) so a `dates.start`/`dates.end` pair given in
    THIS same message counts immediately too. Skipped entirely, not
    deferred, when nights still can't be determined -- there is nothing to
    divide by yet, and the next turn that supplies dates will retry this
    same derivation off the still-SET `trip_total`.

    Never overrides an explicit range, exactly like the target-derivation:
    a user who separately said "2-3 triệu/đêm" (this turn or a prior one)
    keeps exactly that band instead of having it silently replaced once
    dates land.
    """
    touches_range = any(change.get("path") in ("budget.min", "budget.max", "budget.target") for change in patch)
    if touches_range:
        return []
    if (
        travel_state.get("budget.min").presence is Presence.SET
        or travel_state.get("budget.max").presence is Presence.SET
        or travel_state.get("budget.target").presence is Presence.SET
    ):
        return []

    trip_total_value: Any = None
    for change in patch:
        if change.get("path") == "budget.trip_total" and change.get("operation") == "set":
            trip_total_value = change.get("value")
    if not isinstance(trip_total_value, (int, float)):
        trip_total_slot = travel_state.get("budget.trip_total")
        if trip_total_slot.presence is Presence.SET:
            trip_total_value = trip_total_slot.value
    if not isinstance(trip_total_value, (int, float)):
        return []

    nights = trip_duration_days(prospective_state)
    if not nights:
        return []

    per_night = float(trip_total_value) / nights
    tolerance = max(_BUDGET_TARGET_TOLERANCE_FLOOR_VND, _BUDGET_TARGET_TOLERANCE_RATIO * per_night)
    return [
        {"path": "budget.min", "operation": "set", "value": max(0.0, per_night - tolerance)},
        {"path": "budget.max", "operation": "set", "value": per_night + tolerance},
    ]


def validate_patch(state: TravelGraphState) -> dict[str, Any]:
    travel_state = TravelState.from_dict(state.get("travel_state"))
    patch = list(state.get("patch") or [])
    patch, unresolved_amenities, ambiguous_amenities = _bind_amenity_patch(patch, travel_state)
    patch += _derive_budget_range_from_target(patch, travel_state)

    # A trip_total -> per-night conversion needs this turn's own dates (if
    # any) already resolved, which the single apply_patch call below would
    # normally be the one to do -- so this runs it once, provisionally, to
    # read `prospective_state`'s dates, then appends the derived range and
    # applies the complete, final patch. Bounded to exactly one extra pass,
    # same convention as `budget_check`'s own re-plan step.
    prospective = apply_patch(travel_state, patch).state
    patch += _derive_budget_range_from_trip_total(patch, travel_state, prospective)

    result = apply_patch(travel_state, patch)
    for rejection in result.rejected:
        logger.warning(
            "travel_state_patch_rejected",
            extra={
                "patch_path": rejection.path,
                "patch_operation": rejection.operation,
                "patch_reason": rejection.reason,
            },
        )
    impacted = sorted(detect_impact(result.applied))

    return {
        "proposed_travel_state": result.state.to_dict(),
        "applied_changes": [asdict(change) for change in result.applied],
        # Appended to whatever `extract_patch` already rejected this turn --
        # grounding rejections (an unsupported destination) and validation
        # rejections (a malformed date) are different failures the user may
        # hit in the same message, and overwriting here used to discard the
        # first. `load_context` clears the channel per turn, so this only
        # ever accumulates within one turn.
        "rejected_changes": [
            *(state.get("rejected_changes") or []),
            *(asdict(rejection) for rejection in result.rejected),
        ],
        "unresolved_amenities": unresolved_amenities,
        "ambiguous_amenities": ambiguous_amenities,
        "impacted_workflows": impacted,
    }
