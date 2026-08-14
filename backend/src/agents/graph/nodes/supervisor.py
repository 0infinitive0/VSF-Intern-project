"""`supervisor` — delegation only, never completion counting.

Doc §36 draws the line: validation lives in `understand_request`,
patch/impact logic in `apply_change`, completion checks/availability/
booking/route/budget validation all remain deterministic Python. So
"are all tasks done?" is `all_tasks_done` on a conditional edge
(`routing.py`), never a model call — asking a model a question code
already answers is the anti-pattern this whole plan removes.

Three paths, in order:
1. Fast path — exactly one possible worker and no prior failure this turn:
   delegate straight from `IMPACT_MAP`-derived `pending_tasks`, zero LLM
   calls. ~90% of turns hit this.
2. LLM path — multi-workflow turns or recovery after a worker failure:
   structured output over a closed 4-worker label set.
3. Fallback — any LLM exception (including an impossible proposal):
   `IMPACT_MAP`-derived `workers[0]`, or `respond` if none remain.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic import BaseModel

from src.agents.graph.routing import WORKER_ORDER, is_impossible
from src.agents.graph.prompts import build_supervisor_prompt
from src.agents.graph.state import TravelGraphState, build_manifest
from src.services.llm import get_fast_llm

logger = logging.getLogger(__name__)

MAX_SUPERVISOR_ITERATIONS = 5
# The day-rebuild loop (Phase 9) routes back through this node once per day
# by design (`itinerary_node` re-queues itself while `rebuild_day_queue` is
# non-empty). Sharing `MAX_SUPERVISOR_ITERATIONS` with that loop silently
# truncated any itinerary past ~5 days -- review finding F3. This bound
# exists only to stop a genuine runaway loop, not to cap trip length, so
# it's generous relative to any real trip.
MAX_DAY_REBUILD_HOPS = 100


class SupervisorDecision(BaseModel):
    next_worker: Literal["hotel_node", "itinerary_node", "booking_node", "qa_node"]
    task_description: str
    reasoning: str  # audit only — never shown to the user


def _delegate(
    worker: str, source: str, state: TravelGraphState, decision: SupervisorDecision | None = None
) -> dict[str, Any]:
    return {
        "next_worker": worker,
        "task_description": decision.task_description if decision else f"auto-routed to {worker} via {source}",
        "routing_source": source,
        "routing_reasoning": decision.reasoning if decision else "",
        "supervisor_iterations": state.get("supervisor_iterations", 0) + 1,
    }


def _eligible_workers(state: TravelGraphState) -> list[str]:
    pending = state.get("pending_tasks") or []
    return [worker for worker in WORKER_ORDER if worker in pending and not is_impossible(worker, state)]


def supervisor(state: TravelGraphState) -> dict[str, Any]:
    """Delegation only. Completion is decided by `all_tasks_done` on the edge."""
    # A non-empty `rebuild_day_queue` means `itinerary_node` already started
    # draining a multi-day build and is just continuing -- this is a
    # mechanical queue-pop the node itself controls, not the supervisor
    # choosing among workers, so it gets its own bounded counter instead of
    # spending the general delegation budget (review finding F3).
    if state.get("rebuild_day_queue") and "itinerary_node" in (state.get("pending_tasks") or []):
        if state.get("day_rebuild_hops", 0) >= MAX_DAY_REBUILD_HOPS:
            logger.error("Day-rebuild loop exceeded %d hops; bailing to respond", MAX_DAY_REBUILD_HOPS)
            # Say so, honestly, instead of falling through to `respond`'s
            # generic "updated" ack while days are still missing -- exactly
            # the "success message, wrong data" failure this bailout used to
            # cause silently (review finding F3).
            rebuilt = state.get("rebuilt_days") or []
            remaining = state.get("rebuild_day_queue") or []
            partial_reply = (
                f"Đã xây dựng {len(rebuilt)} ngày ({sorted(rebuilt)}); "
                f"còn {len(remaining)} ngày ({sorted(remaining)}) chưa hoàn tất do vượt giới hạn xử lý. "
                "Hãy thử lại để tiếp tục."
            )
            task_results = [
                *(state.get("task_results") or []),
                {"worker": "itinerary_node", "status": "partial_error", "reply": partial_reply},
            ]
            return {
                "next_worker": "respond",
                "routing_source": "max_iterations",
                "routing_reasoning": "",
                "task_results": task_results,
            }
        return {
            "next_worker": "itinerary_node",
            "task_description": state.get("task_description") or "",
            "routing_source": "day_loop_continuation",
            "routing_reasoning": "",
            "day_rebuild_hops": state.get("day_rebuild_hops", 0) + 1,
        }

    if state.get("supervisor_iterations", 0) >= MAX_SUPERVISOR_ITERATIONS:
        return {"next_worker": "respond", "routing_source": "max_iterations", "routing_reasoning": ""}

    workers = _eligible_workers(state)

    # Fast path: exactly one possible worker and no prior failure -> no LLM needed.
    if len(workers) == 1 and not state.get("task_results"):
        return _delegate(workers[0], "impact_map", state)

    try:
        llm = get_fast_llm(temperature=0)
        manifest = build_manifest(state)
        decision = llm.with_structured_output(SupervisorDecision).invoke(build_supervisor_prompt(manifest))
        if not isinstance(decision, SupervisorDecision):
            raise TypeError(f"structured output returned {type(decision).__name__}, not SupervisorDecision")
        if is_impossible(decision.next_worker, state):
            raise ValueError(f"impossible worker: {decision.next_worker}")
        # Structured output guarantees a valid *label*, not a valid *choice*
        # for THIS turn: when pending_tasks is non-empty, the model must
        # pick from it — a worker that already reported (or was never
        # impacted) pops nothing off the queue, so `all_tasks_done` never
        # trips and the loop burns its iteration cap without ever running
        # the genuinely pending worker. When `workers` is empty (a pure
        # question turn), no such constraint exists and qa_node stays
        # reachable — found during code review, reproduced empirically.
        if workers and decision.next_worker not in workers:
            raise ValueError(f"{decision.next_worker} is not in this turn's pending_tasks: {workers}")
        return _delegate(decision.next_worker, "supervisor", state, decision)
    except Exception:
        logger.exception("Supervisor LLM routing failed; falling back to IMPACT_MAP")
        return _delegate(workers[0] if workers else "respond", "impact_map_fallback", state)
