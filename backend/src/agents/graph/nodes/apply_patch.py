"""`apply_patch` — commits `validate_patch`'s proposed `TravelState` and
seeds the supervisor's delegation queue.

`pending_tasks` is the queue `all_tasks_done`/the supervisor's fast path
read from: workers derived from this turn's `impacted_workflows`, in
`WORKER_ORDER`, deduplicated (`itinerary` and `itinerary_day` both map to
`itinerary_node`). It is seeded once here per turn; each worker node pops
itself off as it reports a result, so a completed worker is never
re-delegated even though `impacted_workflows` itself does not shrink.

Phase 10: after committing, the node emits an audit record for every applied
and rejected change to ``sessions.context_data["state_audit"]``.  The emit
is best-effort (never raises) — a DB outage must not fail a chat turn.
"""

from __future__ import annotations

from typing import Any

from src.agents.graph.routing import WORKER_ORDER, WORKFLOW_TO_WORKER
from src.agents.graph.state import TravelGraphState


def _pending_tasks_from_impact(impacted: list[str], *, force_hotel: bool) -> list[str]:
    workers = {WORKFLOW_TO_WORKER[workflow] for workflow in impacted if workflow in WORKFLOW_TO_WORKER}
    if force_hotel:
        # A hotel pick (`selected_hotel_id`, review finding F2) isn't an
        # ALLOWED_PATHS change, so `impacted_workflows` never carries it --
        # without this, `hotel_node` would never be delegated to and a
        # picked hotel would never turn into `trip_data`.
        workers.add("hotel_node")
    return [worker for worker in WORKER_ORDER if worker in workers]


def apply_patch(state: TravelGraphState) -> dict[str, Any]:
    proposed = state.get("proposed_travel_state")
    committed = proposed if proposed is not None else (state.get("travel_state") or {})
    pending_tasks = _pending_tasks_from_impact(
        state.get("impacted_workflows") or [], force_hotel=bool(state.get("selected_hotel_id"))
    )

    # --- Phase 10: best-effort audit emit ---------------------------------
    # Capture the before-state BEFORE we commit proposed_travel_state.
    # travel_state is the slot dict written by the previous apply_patch (or
    # the initial load_context baseline), so it represents the value BEFORE
    # this turn's patch was applied.
    session_id: str = state.get("session_id") or ""
    applied_changes: list[dict[str, Any]] = list(state.get("applied_changes") or [])
    rejected_changes: list[dict[str, Any]] = list(state.get("rejected_changes") or [])
    travel_state_before: dict[str, Any] = dict(state.get("travel_state") or {})

    if session_id and (applied_changes or rejected_changes):
        try:
            from src.services.state_audit import emit_patch_audit  # lazy import — service layer

            emit_patch_audit(
                session_id,
                applied_changes,
                rejected_changes,
                travel_state_before=travel_state_before,
                source="validate_patch",
            )
        except Exception:
            import logging

            logging.getLogger(__name__).exception(
                "apply_patch: unexpected error in audit emit for session %s", session_id
            )
    # ----------------------------------------------------------------------

    return {
        "travel_state": committed,
        "pending_tasks": pending_tasks,
    }
