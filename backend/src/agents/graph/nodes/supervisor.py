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

import json
import logging
from typing import Any, Literal

from pydantic import BaseModel

from src.agents.graph.contracts import CONTRACTS
from src.agents.graph.nodes.extract_patch import _last_human_message
from src.agents.graph.prompts import build_supervisor_prompt
from src.agents.graph.routing import WORKER_ORDER, can_list_nearby, is_impossible, needs_trip_first
from src.agents.graph.state import TravelGraphState, build_manifest
from src.i18n import t
from src.services.llm import get_fast_llm
from src.services.trip_finalize import is_trip_finalized

#: `extract_patch`'s label for a message that states nothing. Kept in sync
#: with `nodes/extract_patch.py`'s constant of the same name by the shared
#: intent vocabulary in `prompts.py`.
_READ_ONLY_INTENT = "general_question"

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
    # Only meaningful when next_worker == "itinerary_node" — selects which of
    # itinerary_node's four actions to run (see its module docstring's
    # `task_description` JSON contract). Ignored for every other worker.
    action: Literal["rebuild_days", "edit_item", "lock_days", "list_nearby"] | None = None
    # Only meaningful when action == "list_nearby" — the search radius (km)
    # the user explicitly stated. `itinerary_node` still validates and
    # re-derives it deterministically if this is missing or out of range
    # (same "don't trust the model on a number" stance as every other
    # LLM-parsed numeric field in this codebase, e.g.
    # `hotel_preferences.radius_km`'s own range check in travel_state.py).
    radius_km: float | None = None


def _task_description_for(worker: str, decision: SupervisorDecision | None, source: str) -> str:
    """Free-text audit description for every worker, except `itinerary_node`
    on the LLM path: that node's `_parse_task` only recognizes `edit_item`/
    `lock_days`/`list_nearby` from a JSON `{"action": ..., "user_request": ...}` string
    (its module docstring's contract) — a plain sentence silently falls back
    to `rebuild_days` every time, which is what made `edit_item`'s
    suggest-then-pick flow unreachable in production before this. The fast
    path (`impact_map`, no `decision`) still gets the old fixed string:
    it only ever fires for a first-ever build or a trip-wide patch, where
    `rebuild_days` (itinerary_node's own default with no action given) is
    already the right action."""
    if not decision:
        return f"auto-routed to {worker} via {source}"
    if worker == "itinerary_node" and decision.action:
        task: dict[str, Any] = {"action": decision.action, "user_request": decision.task_description}
        if decision.action == "list_nearby" and decision.radius_km is not None:
            task["radius_km"] = decision.radius_km
        return json.dumps(task)
    return decision.task_description


def _delegate(
    worker: str, source: str, state: TravelGraphState, decision: SupervisorDecision | None = None
) -> dict[str, Any]:
    return {
        "next_worker": worker,
        "task_description": _task_description_for(worker, decision, source),
        "routing_source": source,
        "routing_reasoning": decision.reasoning if decision else "",
        "supervisor_iterations": state.get("supervisor_iterations", 0) + 1,
    }


def _eligible_workers(state: TravelGraphState) -> list[str]:
    pending = state.get("pending_tasks") or []
    return [worker for worker in WORKER_ORDER if worker in pending and not is_impossible(worker, state)]


def _has_reported(state: TravelGraphState, worker: str) -> bool:
    """Did *worker* already leave a result this turn? `task_results` is
    turn-scoped (`load_context` clears it), so a hit means "ran, this turn"."""
    return any((entry or {}).get("worker") == worker for entry in (state.get("task_results") or []))


def _awaiting_hotel_choice(state: TravelGraphState) -> dict[str, Any]:
    """`hotel_node` already ran this turn and there is still no trip: it
    presented options and is waiting on the user's pick.

    Redirecting again would re-run the whole search — RPC, hydration,
    ranking — only to ask the identical question, and append a second
    `hotel_node` entry to `task_results` while doing it. The turn is
    finished; `respond` speaks the reply hotel_node already left.

    `itinerary_node` is dropped rather than left pending for the same reason
    `_redirect_to_hotel_node` drops it: it cannot act without a trip, and the
    patch that follows the pick impacts it again anyway.
    """
    return {
        "next_worker": "respond",
        "routing_source": "awaiting_hotel_choice",
        "routing_reasoning": "",
        "pending_tasks": [worker for worker in (state.get("pending_tasks") or []) if worker != "itinerary_node"],
    }


def _redirect_to_hotel_node(state: TravelGraphState) -> dict[str, Any]:
    """Hand the pending slot over, do not add to it.

    `all_tasks_done` is `not pending_tasks`, and `hotel_node` only ever
    removes *itself* from that list. Leaving `itinerary_node` pending would
    bring the turn straight back here with the trip still missing — search,
    redirect, search again, until the iteration cap. Replacing it is also
    the honest description of the turn: the pending work really is "pick a
    hotel", and `itinerary_node` will be impacted again by the patch that
    follows the pick.
    """
    pending = [worker for worker in (state.get("pending_tasks") or []) if worker != "itinerary_node"]
    if "hotel_node" not in pending:
        pending.append("hotel_node")
    return {**_delegate("hotel_node", "needs_trip_first", state), "pending_tasks": pending}


def _locked_turn_reply(state: TravelGraphState, blocked: list[str]) -> dict[str, Any]:
    """The turn wanted a worker that writes to a finalized trip. Refuse in
    words, the same way `scope_guard` refuses a jailbreak attempt, rather
    than silently dropping the work and falling through to `respond`'s
    generic acknowledgement (which would tell the user something changed
    when nothing did).

    Only the writing workers named in `blocked` are dropped from
    `pending_tasks` — `qa_node` never reaches this function with anything
    pending (its turns carry no `pending_tasks` entry at all, see
    `WORKFLOW_TO_WORKER`), so a read-only question in the same turn a write
    was attempted still gets answered, not silently absorbed here.
    """
    language = state.get("language") or "vi"
    reply = t(
        "Lịch trình này đã được hoàn tất và khoá lại nên mình không thể chỉnh sửa được nữa. "
        "Bạn vẫn có thể hỏi mình về chuyến đi, hoặc nhân bản thành một chuyến đi mới nếu muốn thay đổi.",
        language,
    )
    task_results = [
        *(state.get("task_results") or []),
        {"worker": "supervisor", "status": "locked", "reply": reply},
    ]
    return {
        "next_worker": "respond",
        "routing_source": "trip_finalized",
        "routing_reasoning": "",
        "task_results": task_results,
        "pending_tasks": [worker for worker in (state.get("pending_tasks") or []) if worker not in blocked],
    }


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

    # A finalized trip is locked: refuse whichever writer this turn wanted,
    # in words, before the fast/LLM paths below get a chance to run one.
    # Checked ahead of `_eligible_workers` (not via `_IMPOSSIBLE`) because
    # marking a worker impossible only removes it from the eligible set --
    # nothing then fills `task_results` with a reply, and `respond` would
    # fall through to its generic "Đã cập nhật thông tin chuyến đi" ack for a
    # turn that changed nothing (see that node's ERROR-logged safety net).
    pending_writers = [
        worker for worker in (state.get("pending_tasks") or []) if CONTRACTS.get(worker, CONTRACTS["qa_node"]).writes
    ]
    if pending_writers and is_trip_finalized(state.get("trip_data")):
        return _locked_turn_reply(state, pending_writers)

    workers = _eligible_workers(state)

    # An itinerary request with no trip yet is not a dead end, it is a
    # request for the step before it. Checked ahead of the LLM path because
    # no amount of reasoning turns an empty eligible set into a worker.
    if not workers and needs_trip_first(state):
        if _has_reported(state, "hotel_node"):
            return _awaiting_hotel_choice(state)
        return _redirect_to_hotel_node(state)

    # A read-only turn goes to the read-only worker, deterministically.
    #
    # With `workers` empty the turn falls through to the LLM branch below,
    # which is unconstrained precisely BECAUSE the queue is empty -- and an
    # unconstrained choice includes `itinerary_node`. Asking "ngày 3 tôi làm
    # gì?" therefore rebuilt the whole plan behind the user's back: the day-1
    # attraction silently changed from Bãi biển Mỹ Khê to Đức Maria Mẹ Sao
    # Biển, and nothing in the reply said the trip had been regenerated. The
    # extractor was blameless -- it returned `general_question` with an empty
    # patch, correctly -- so no amount of prompt work upstream could have
    # prevented it.
    #
    # `intent` is the extractor's own classification of the message, and
    # `general_question` is defined as changing nothing (`prompts.py`), so a
    # worker that writes can never be the right answer for one. Routing it by
    # LLM was asking a model to re-derive a decision already made, with data
    # loss as the failure mode.
    if not workers and state.get("intent") == _READ_ONLY_INTENT:
        # `list_nearby` is the ONE itinerary_node action that writes nothing
        # (pure search + `_ok()` passthrough -- no `_invoke_rebuild_day`, no
        # patch), so it is the one worker branch a read-only turn may take.
        # It is also the only path that can put places on the map at all:
        # `qa_node`'s tools reach `messages` and nothing else, so
        # `suggested_places` is structurally unreachable from there (see
        # qa_node.py's QAState docstring).
        #
        # The action is a CONSTANT here, never a model's pick. That is what
        # keeps the day-recap incident closed (see the note above): with no
        # choice offered, there is no route from a read-only turn to
        # `rebuild_days` for a model to take by mistake. `radius_km` is left
        # out on purpose -- `itinerary_node._resolve_radius_km` re-reads it
        # from the user's own words deterministically when it is absent.
        # `can_list_nearby` (routing.py), NOT the blanket `is_impossible`
        # this used to call: that guard's `requires_existing_trip` is about
        # the node's three EDIT actions and wrongly excluded the hotel
        # shortlist stage, where the cards are on screen, numbered, and
        # "quanh khách sạn số 1 có gì?" is exactly the question being asked.
        # A turn with neither trip nor shortlist still falls through to
        # `qa_node`, unchanged.
        if state.get("asks_nearby_places") and can_list_nearby(state):
            task = {"action": "list_nearby", "user_request": _last_human_message(state)}
            return {
                **_delegate("itinerary_node", "read_only_intent_nearby", state),
                "task_description": json.dumps(task),
            }
        return _delegate("qa_node", "read_only_intent", state)

    # Fast path: a first delegation, whatever its size -> no LLM needed.
    #
    # `WORKER_ORDER` already fixes the order, for a causal reason (the hotel
    # anchors the itinerary — see routing.py), and the model is constrained
    # to choose from that same ordered list. Of its three possible answers,
    # `workers[0]` matches the table, an off-list pick is rejected straight
    # back to the table, and the only genuinely different answer — a
    # later-in-order worker — is the wrong order. That last branch is not
    # hypothetical: it is the reported bug that `_IMPOSSIBLE`'s `trip_data`
    # check was added to patch, where the model picked `itinerary_node`
    # first and it bailed with nothing to show.
    #
    # `task_results` is the boundary, not the worker count: empty means
    # first delegation (the table is enough), non-empty means a worker has
    # already run and possibly failed, which is where reasoning earns its
    # call.
    if workers and not state.get("task_results"):
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
