"""`load_context` — the graph's first node, `START`'s only downstream edge.

The LangGraph checkpointer (Phase 4) already restores every field a prior
turn wrote, keyed by `thread_id` (the session id); this node's job is not
to fetch anything from Supabase or the session store, only to reset the
fields that are scoped to *this* turn, and default the ones that don't
exist yet the very first time a thread is ever invoked (a brand-new thread
has no checkpoint, so a node reading `state["travel_state"]` directly would
`KeyError` — every field below is read with `.get(...)` for exactly that
reason).
"""

from __future__ import annotations

from typing import Any

from src.agents.graph_v2.state import TravelGraphState


def load_context(state: TravelGraphState) -> dict[str, Any]:
    return {
        "travel_state": state.get("travel_state") or {},
        "patch": [],
        "intent": "",
        "proposed_travel_state": {},
        "applied_changes": [],
        "rejected_changes": [],
        "impacted_workflows": [],
        "missing_slots": [],
        "next_question": None,
        "jailbreak_blocked": False,
        "supervisor_iterations": 0,
        "pending_tasks": [],
        "next_worker": None,
        "task_description": "",
        "task_results": [],
        "routing_source": "",
        "routing_reasoning": "",
        "response": {},
    }
