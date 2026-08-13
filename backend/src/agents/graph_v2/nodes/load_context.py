"""`load_context` — the graph's first node, `START`'s only downstream edge.

The LangGraph checkpointer (Phase 4) already restores every field a prior
turn wrote, keyed by `thread_id` (the session id); this node's job is not
to fetch anything from Supabase or the session store, only to reset the
fields that are scoped to *this* turn, and default the ones that don't
exist yet the very first time a thread is ever invoked (a brand-new thread
has no checkpoint, so a node reading `state["travel_state"]` directly would
`KeyError` — every field below is read with `.get(...)` for exactly that
reason).

`missing_slots` is deliberately NOT reset here (Phase 7): `ask_slot` is its
only writer, so by the time `ask_slot` runs this turn, it still holds
whatever slot was pending at the END of the previous turn — the one signal
`ask_slot` needs to tell "this exact question is being re-asked because the
last reply didn't answer it" apart from "this is the first time asking it",
without which every re-ask would be indistinguishable from a first ask (see
`nodes/ask_slot.py`'s docstring).
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
        "unresolved_resume_text": None,
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
