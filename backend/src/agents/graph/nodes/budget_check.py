"""`budget_check` — deterministic trip-total budget validation, stubbed.

Referenced by this phase's own Edges section (`all_tasks_done` routes a
finished worker here before `respond`) but not listed among the nodes this
phase builds out — real budget/route validation is deterministic Python
per doc §36, and lands with Phase 14's trip-total budget constraint
(`budget.trip_total` in `domain/travel_state.py`). Registered here as a
pass-through so the graph's own edges compile and the topology test finds
no orphan target; Phase 14 replaces this body without touching the edge
shape.
"""

from __future__ import annotations

from typing import Any

from src.agents.graph.state import TravelGraphState


def budget_check(state: TravelGraphState) -> dict[str, Any]:  # noqa: ARG001
    return {}
