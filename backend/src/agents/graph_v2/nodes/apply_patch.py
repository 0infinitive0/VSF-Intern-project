"""`apply_patch` — commits `validate_patch`'s proposed `TravelState` and
seeds the supervisor's delegation queue.

`pending_tasks` is the queue `all_tasks_done`/the supervisor's fast path
read from: workers derived from this turn's `impacted_workflows`, in
`WORKER_ORDER`, deduplicated (`itinerary` and `itinerary_day` both map to
`itinerary_node`). It is seeded once here per turn; each worker node pops
itself off as it reports a result, so a completed worker is never
re-delegated even though `impacted_workflows` itself does not shrink.
"""

from __future__ import annotations

from typing import Any

from src.agents.graph_v2.routing import WORKER_ORDER, WORKFLOW_TO_WORKER
from src.agents.graph_v2.state import TravelGraphState


def _pending_tasks_from_impact(impacted: list[str]) -> list[str]:
    workers = {WORKFLOW_TO_WORKER[workflow] for workflow in impacted if workflow in WORKFLOW_TO_WORKER}
    return [worker for worker in WORKER_ORDER if worker in workers]


def apply_patch(state: TravelGraphState) -> dict[str, Any]:
    proposed = state.get("proposed_travel_state")
    committed = proposed if proposed is not None else (state.get("travel_state") or {})
    pending_tasks = _pending_tasks_from_impact(state.get("impacted_workflows") or [])

    return {
        "travel_state": committed,
        "pending_tasks": pending_tasks,
    }
