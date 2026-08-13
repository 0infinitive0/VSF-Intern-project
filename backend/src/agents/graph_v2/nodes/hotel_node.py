"""`hotel_node` — Phase 8 stub.

Phase 8 fills this with hard filters, radius, and center resolution
(`subgraphs/hotel_flow.py`, an interrupt-bearing subgraph). For Phase 5 it
is a pass-through: it reports completion for its own delegation without
touching `travel_state`, so the supervisor loop and `all_tasks_done` have a
real worker to route through end to end.
"""

from __future__ import annotations

from typing import Any

from src.agents.graph_v2.state import TravelGraphState

_WORKER_NAME = "hotel_node"


def hotel_node(state: TravelGraphState) -> dict[str, Any]:
    pending = [worker for worker in (state.get("pending_tasks") or []) if worker != _WORKER_NAME]
    task_results = [*(state.get("task_results") or []), {"worker": _WORKER_NAME, "status": "stub_pass_through"}]
    return {"pending_tasks": pending, "task_results": task_results}
