"""`validate_patch` — runs the Phase 3 patch layer's validators.

Computes what applying `state["patch"]` *would* produce without committing
it: the result lands in `proposed_travel_state`, and `apply_patch` is the
only node that writes `travel_state`. Keeping validation and commit as two
nodes is what lets Phase 7 insert an `interrupt` between them (asking the
user to resolve a rejected change) without either node's contract changing.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from src.agents.graph_v2.state import TravelGraphState
from src.domain.travel_state import TravelState, apply_patch, detect_impact


def validate_patch(state: TravelGraphState) -> dict[str, Any]:
    travel_state = TravelState.from_dict(state.get("travel_state"))
    patch = state.get("patch") or []

    result = apply_patch(travel_state, patch)
    impacted = sorted(detect_impact(result.applied))

    return {
        "proposed_travel_state": result.state.to_dict(),
        "applied_changes": [asdict(change) for change in result.applied],
        "rejected_changes": [asdict(rejection) for rejection in result.rejected],
        "impacted_workflows": impacted,
    }
