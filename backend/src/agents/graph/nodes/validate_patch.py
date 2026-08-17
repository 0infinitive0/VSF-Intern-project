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

from dataclasses import asdict
from typing import Any

from src.agents.graph.state import TravelGraphState
from src.domain.travel_state import Presence, TravelState, apply_patch, detect_impact

# A "khoảng X" / "tầm X" answer only ever sets budget.target (a single
# preferred price, prompts.py's per-field contract) -- it never touches
# budget.min/budget.max on its own, so without this those slots stay
# UNKNOWN and the frontend's dual-thumb slider (intake-budget-slider.tsx,
# response_payload.budget_from_travel_state) has nothing to draw, and the
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


def validate_patch(state: TravelGraphState) -> dict[str, Any]:
    travel_state = TravelState.from_dict(state.get("travel_state"))
    patch = list(state.get("patch") or [])
    patch += _derive_budget_range_from_target(patch, travel_state)

    result = apply_patch(travel_state, patch)
    impacted = sorted(detect_impact(result.applied))

    return {
        "proposed_travel_state": result.state.to_dict(),
        "applied_changes": [asdict(change) for change in result.applied],
        "rejected_changes": [asdict(rejection) for rejection in result.rejected],
        "impacted_workflows": impacted,
    }
