"""`itinerary_node` — Phase 9 stub.

Phase 9 fills this with the day-by-day itinerary build/rebuild
(`subgraphs/itinerary_flow.py`, itself driving a `rebuild_day` loop). For
Phase 5 it is a pass-through: it reports completion for its own delegation
without touching `travel_state`, so the supervisor loop and
`all_tasks_done` have a real worker to route through end to end.
"""

from __future__ import annotations

from typing import Any

from src.agents.graph_v2.state import TravelGraphState

_WORKER_NAME = "itinerary_node"


def itinerary_node(state: TravelGraphState) -> dict[str, Any]:
    pending = [worker for worker in (state.get("pending_tasks") or []) if worker != _WORKER_NAME]
    task_results = [*(state.get("task_results") or []), {"worker": _WORKER_NAME, "status": "stub_pass_through"}]
    return {"pending_tasks": pending, "task_results": task_results}
