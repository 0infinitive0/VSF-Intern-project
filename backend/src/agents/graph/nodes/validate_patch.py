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
from src.domain.travel_state import TravelState, apply_patch, detect_impact


def validate_patch(state: TravelGraphState) -> dict[str, Any]:
    travel_state = TravelState.from_dict(state.get("travel_state"))
    patch = list(state.get("patch") or [])

    result = apply_patch(travel_state, patch)
    impacted = sorted(detect_impact(result.applied))

    return {
        "proposed_travel_state": result.state.to_dict(),
        "applied_changes": [asdict(change) for change in result.applied],
        "rejected_changes": [asdict(rejection) for rejection in result.rejected],
        "impacted_workflows": impacted,
    }
