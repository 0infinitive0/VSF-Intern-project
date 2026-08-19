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

`trip_data` and `selected_hotel_id` are ALSO deliberately not reset here,
for the same reason (review findings F1/F2):
- `trip_data` is the generated trip bundle, carried forward turn to turn
  like `messages` — resetting it here would erase the itinerary on every
  turn. `itinerary_node`/`hotel_node` are its only writers.
- `selected_hotel_id` is set by `POST /hotels/select` as part of this
  turn's `invoke()` input, which is merged into state BEFORE this node
  runs — resetting it here would wipe it before `hotel_node` ever sees it.
  `hotel_node` is the sole consumer and clears it itself on every return.

`pending_clarify_day` (Phase 16) is not reset here either, for the same
reason as `missing_slots`: `extract_patch` is its sole writer, and it has
to still hold the day a clarify question was about when `extract_patch`
reads it back on the very next call, as the fallback anchor for a bare
follow-up reply that names no day itself. `extract_patch` always overwrites
it with the day the CURRENT message named (or clears it), so an unrelated
later turn can't renew it -- except on the handful of paths that skip
`extract_patch` entirely (a blocked turn, a hotel pick, an interrupt
resume), where it can outlive more than the one turn it's meant for. See
`extract_patch.py`'s module docstring.
"""

from __future__ import annotations

from typing import Any

from src.agents.graph.state import TravelGraphState


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
        "extraction_failed": False,
        "patch_reason": "",
        "asks_nearby_places": False,
        "intake_answer": None,
        "jailbreak_blocked": False,
        "supervisor_iterations": 0,
        "day_rebuild_hops": 0,
        "pending_tasks": [],
        "next_worker": None,
        "task_description": "",
        "task_results": [],
        "routing_source": "",
        "routing_reasoning": "",
        "response": {},
    }
