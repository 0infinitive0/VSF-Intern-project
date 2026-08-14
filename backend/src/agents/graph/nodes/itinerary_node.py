"""`itinerary_node` — Phase 9 worker.

Replaces the Phase 5 stub.  This node:

1. Reads the action from ``task_description`` (set by the supervisor).
2. For day-rebuild actions (``build_itinerary``, ``rebuild_days``):
   - Determines the set of affected days.
   - Subtracts ``locked_days`` (read from ``planning_constraints``).
   - Stores the result in ``rebuild_day_queue``.
   - Pops the first queued day, invokes the ``rebuild_day`` subgraph for
     that day, then returns updated state.
   - The parent graph's conditional edge (`all_tasks_done`) re-routes back
     to this node while ``rebuild_day_queue`` is non-empty — **this is the
     "loop as conditional edge, not Python for"** that the plan requires
     (§Architecture).
3. For item-level edits (``edit_item``):
   - Calls ``plan_trip_edit`` (the existing 9-operation planner).
   - Applies the resulting ``TripEditPlan`` via ``apply_trip_edit_plan``.
4. For ``lock_days``:
   - Writes the requested days into ``planning_constraints.locked_days``.

### Interrupt isolation

Each ``rebuild_day`` invocation is a *compiled subgraph* with its own
MemorySaver checkpoint.  If the subgraph suspends mid-execution (Phase 13 will
add a shortlist-pick suspension hook there), the resume restarts from inside the
subgraph for *that day only* — days already processed are not re-run.

### `task_description` format

The supervisor sets ``task_description`` to a JSON string:
```json
{
  "action": "build_itinerary" | "rebuild_days" | "edit_item" | "lock_days",
  "day_numbers": [1, 2],        // for rebuild_days; absent → all days
  "user_request": "...",        // for edit_item
  "days_to_lock": [1]           // for lock_days
}
```
If ``task_description`` is a plain string (legacy supervisor calls that haven't
been updated yet), the node falls back to ``build_itinerary`` for all days.
"""

from __future__ import annotations

import json
import logging
import uuid
from copy import deepcopy
from typing import Any

from src.agents.graph.state import TravelGraphState
from src.agents.graph.subgraphs.rebuild_day import build_rebuild_day_subgraph
from src.domain.travel_state import Presence, TravelState
from src.services.trip_planner import (
    _get_locked_days,
    _itinerary_record,
    apply_trip_edit_plan,
)
from src.services.trip_edit_planner import TripEditPlanError, plan_trip_edit

logger = logging.getLogger(__name__)

_WORKER_NAME = "itinerary_node"

# One compiled subgraph instance shared across turns — stateless from the
# parent's perspective because each invocation uses a distinct thread_id.
_REBUILD_DAY_SUBGRAPH = build_rebuild_day_subgraph()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_task(task_description: str) -> dict[str, Any]:
    """Parse the supervisor-supplied task description into a plain dict.

    Supports both JSON (preferred) and legacy plain-string fallback.
    """
    if not task_description:
        return {"action": "build_itinerary"}
    try:
        parsed = json.loads(task_description)
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, ValueError):
        pass
    # Legacy/plain string fallback — treat as a rebuild request.
    return {"action": "build_itinerary", "user_request": task_description}


def _affected_days(trip_data: dict[str, Any], day_numbers: list[int] | None) -> list[int]:
    """Return the ordered list of days that need rebuilding.

    If *day_numbers* is ``None`` or empty, all days in the trip are returned.
    """
    if day_numbers:
        return sorted(set(day_numbers))
    itinerary_rows = trip_data.get("itineraries") or [{}]
    itinerary = itinerary_rows[0] if isinstance(itinerary_rows, list) else itinerary_rows
    total = int(itinerary.get("duration_days") or 0)
    return list(range(1, total + 1)) if total else []


def _theme_for_day(trip_data: dict[str, Any], day_number: int) -> dict[str, Any]:
    """Return the stored theme for *day_number*, or a minimal fallback."""
    itinerary_rows = trip_data.get("itineraries") or [{}]
    itinerary = itinerary_rows[0] if isinstance(itinerary_rows, list) else itinerary_rows
    for theme in itinerary.get("day_themes") or []:
        if int(theme.get("day_number") or 0) == day_number:
            return dict(theme)
    return {"day_number": day_number, "title": f"Ngày {day_number}", "query": ""}


def _set_locked_days(trip_data: dict[str, Any], days_to_lock: list[int]) -> None:
    """Write ``locked_days`` into ``planning_constraints`` in-place. Union
    merge — additive, matching the ``lock_days`` action's "lock these too"
    semantics (there is no matching "unlock" action)."""
    itinerary_rows = trip_data.get("itineraries") or [{}]
    itinerary = itinerary_rows[0] if isinstance(itinerary_rows, list) and itinerary_rows else {}
    if not isinstance(itinerary, dict):
        return
    constraints = dict(itinerary.get("planning_constraints") or {})
    existing = list(constraints.get("locked_days") or [])
    merged = sorted(set(existing) | {int(d) for d in days_to_lock})
    constraints["locked_days"] = merged
    itinerary["planning_constraints"] = constraints


def _sync_locked_days_from_travel_state(trip_data: dict[str, Any], locked_days: Any) -> None:
    """Replace ``planning_constraints.locked_days`` with the patch-validated
    `TravelState` ``locked_days`` slot (review finding F4) -- an authoritative
    REPLACE, not `_set_locked_days`'s union-merge: the slot already reflects
    both `append` and `remove`, so unioning it back in would make a `remove`
    (unlocking a day) silently do nothing."""
    itinerary_rows = trip_data.get("itineraries") or [{}]
    itinerary = itinerary_rows[0] if isinstance(itinerary_rows, list) and itinerary_rows else {}
    if not isinstance(itinerary, dict):
        return
    constraints = dict(itinerary.get("planning_constraints") or {})
    constraints["locked_days"] = sorted({int(d) for d in (locked_days or [])})
    itinerary["planning_constraints"] = constraints


def _invoke_rebuild_day(
    trip_data: dict[str, Any],
    day_number: int,
    locked_days: list[int],
    suggest_ops: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Call the ``rebuild_day`` subgraph for one day.

    Returns the updated ``trip_data`` dict or raises on unrecoverable error.
    Each call uses a unique ``thread_id`` so subgraph checkpoints are
    isolated — resuming from an interrupt on day N never re-runs day M≠N.
    """
    thread_id = f"rebuild-day-{day_number}-{uuid.uuid4()}"
    theme = _theme_for_day(trip_data, day_number)
    result = _REBUILD_DAY_SUBGRAPH.invoke(
        {
            "trip_data": trip_data,
            "day_number": day_number,
            "day_theme": theme,
            "locked_days": locked_days,
        }
        | ({"suggest_operations": suggest_ops} if suggest_ops else {}),
        config={"configurable": {"thread_id": thread_id}},
    )
    error = result.get("rebuild_error")
    if error:
        raise RuntimeError(error)
    return result.get("trip_data") or trip_data


# ---------------------------------------------------------------------------
# Node function
# ---------------------------------------------------------------------------


def itinerary_node(state: TravelGraphState) -> dict[str, Any]:
    """Worker node for itinerary operations (Phase 9).

    See module docstring for the full action vocabulary and loop mechanics.
    """
    language = state.get("language") or "vi"
    task_description = state.get("task_description") or ""
    task = _parse_task(task_description)
    action = str(task.get("action") or "build_itinerary")

    # ── grab working state ──────────────────────────────────────────────────
    # `trip_data` is its own top-level state key, NOT nested inside
    # `travel_state` (review finding F1): `travel_state` round-trips through
    # `TravelState.from_dict()`/`.to_dict()` every turn, which silently drops
    # any key outside `ALLOWED_PATHS` -- `trip_data` isn't one, so nesting it
    # there destroyed the built itinerary after exactly one more turn.
    trip_data: dict[str, Any] = dict(state.get("trip_data") or {})

    # `locked_days` set via the ordinary patch pipeline (`{"path":
    # "locked_days", "operation": "append", ...}`) is authoritative over
    # whatever `trip_data`'s own `planning_constraints.locked_days` holds --
    # review finding F4: before this sync, patching that slot validated and
    # stored the change but had ZERO effect on which days actually got
    # locked, because `_get_locked_days`/`rebuild_day_data` only ever read
    # `trip_data`'s embedded copy. This is a full replace (not the `lock_days`
    # action's incremental union-merge below), since the TravelState slot
    # already reflects append AND remove.
    travel_state = TravelState.from_dict(state.get("travel_state") or {})
    locked_days_slot = travel_state.get("locked_days")
    if trip_data and locked_days_slot.presence is Presence.SET:
        _sync_locked_days_from_travel_state(trip_data, locked_days_slot.value)

    rebuild_day_queue: list[int] = list(state.get("rebuild_day_queue") or [])
    rebuilt_days: list[int] = list(state.get("rebuilt_days") or [])
    pending_tasks: list[str] = [w for w in (state.get("pending_tasks") or []) if w != _WORKER_NAME]
    task_results: list[dict[str, Any]] = list(state.get("task_results") or [])

    def _ok(reply: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        entry: dict[str, Any] = {"worker": _WORKER_NAME, "status": "ok", "reply": reply}
        if extra:
            entry.update(extra)
        return {
            "pending_tasks": pending_tasks,
            "task_results": [*task_results, entry],
            "rebuild_day_queue": rebuild_day_queue,
            "rebuilt_days": rebuilt_days,
            "pending_suggest_operations": state.get("pending_suggest_operations") or [],
            "trip_data": trip_data,
        }

    def _err(reply: str) -> dict[str, Any]:
        entry: dict[str, Any] = {"worker": _WORKER_NAME, "status": "error", "reply": reply}
        return {
            "pending_tasks": pending_tasks,
            "task_results": [*task_results, entry],
            "rebuild_day_queue": rebuild_day_queue,
            "rebuilt_days": rebuilt_days,
        }

    # ── lock_days ────────────────────────────────────────────────────────────
    if action == "lock_days":
        days_to_lock = [int(d) for d in (task.get("days_to_lock") or [])]
        if not days_to_lock:
            return _err("lock_days: days_to_lock is empty")
        if not trip_data:
            return _err("lock_days: không có lịch trình nào để khoá ngày.")
        _set_locked_days(trip_data, days_to_lock)
        return _ok(f"Đã khoá ngày: {days_to_lock}.")

    # ── edit_item ────────────────────────────────────────────────────────────
    if action == "edit_item":
        user_request = str(task.get("user_request") or "")
        if not user_request:
            return _err("edit_item: user_request is empty")
        if not trip_data:
            return _err("edit_item: không có lịch trình nào để chỉnh sửa.")
        working = deepcopy(trip_data)
        try:
            from dataclasses import replace
            edit_plan = plan_trip_edit(user_request, working)
            suggest_ops = [op for op in edit_plan.operations if op.operation == "suggest"]
            other_ops = [op for op in edit_plan.operations if op.operation != "suggest"]
            
            if suggest_ops:
                edit_plan = replace(edit_plan, operations=other_ops)
            
            messages = apply_trip_edit_plan(working, edit_plan)
        except Exception as exc:
            logger.exception("itinerary_node: edit_item failed")
            return _err(f"Chỉnh sửa thất bại: {exc}")
            
        trip_data = working
        
        if suggest_ops:
            pending_suggest_ops = list(state.get("pending_suggest_operations") or [])
            from dataclasses import asdict
            for op in suggest_ops:
                pending_suggest_ops.append(asdict(op))
                if op.target and op.target.day_number:
                    rebuild_day_queue.append(int(op.target.day_number))
                else:
                    # fallback to day 1 if we somehow don't know the day
                    rebuild_day_queue.append(1)
            
            # De-duplicate rebuild queue, preserving order (newest first)
            new_queue = []
            for d in rebuild_day_queue:
                if d not in new_queue:
                    new_queue.append(d)
            
            return {
                "pending_tasks": [*pending_tasks, _WORKER_NAME],  # re-queue self to process the rebuild_day_queue
                "task_results": [*task_results, {"worker": _WORKER_NAME, "status": "ok", "reply": "; ".join(messages) or "Đã ghi nhận yêu cầu chỉnh sửa, đang tìm kiếm gợi ý..."}],
                "rebuild_day_queue": new_queue,
                "rebuilt_days": rebuilt_days,
                "pending_suggest_operations": pending_suggest_ops,
                "trip_data": trip_data,
            }
            
        return _ok("; ".join(messages) or "Đã chỉnh sửa lịch trình.")

    # ── build_itinerary / rebuild_days ────────────────────────────────────────
    # Both actions share the same day-queue logic; build_itinerary → all days.
    if action not in ("build_itinerary", "rebuild_days"):
        return _err(f"itinerary_node: unknown action '{action}'")

    # On the FIRST invocation for this turn, populate rebuild_day_queue.
    if not rebuild_day_queue:
        if not trip_data:
            return _err("itinerary_node: không có lịch trình nào để xây dựng. Hãy chọn khách sạn trước.")
        locked: frozenset[int] = _get_locked_days(trip_data)
        requested_days = task.get("day_numbers")
        all_days = _affected_days(trip_data, requested_days if isinstance(requested_days, list) else None)
        rebuild_day_queue = [d for d in all_days if d not in locked]
        if not rebuild_day_queue:
            locked_list = sorted(locked)
            return _ok(
                f"Tất cả các ngày yêu cầu đều bị khoá {locked_list}; không có ngày nào cần xây dựng lại.",
            )

    # Pop the first day from the queue and invoke the subgraph for it.
    day_number = rebuild_day_queue[0]
    remaining_queue = rebuild_day_queue[1:]
    locked_days_list = sorted(_get_locked_days(trip_data))

    pending_suggest_ops = list(state.get("pending_suggest_operations") or [])
    current_day_suggest_ops = [op for op in pending_suggest_ops if str(op.get("target", {}).get("day_number")) == str(day_number) or (not op.get("target", {}).get("day_number") and day_number == 1)]
    remaining_suggest_ops = [op for op in pending_suggest_ops if op not in current_day_suggest_ops]

    try:
        trip_data = _invoke_rebuild_day(trip_data, day_number, locked_days_list, suggest_ops=current_day_suggest_ops)
    except Exception as exc:
        logger.exception("itinerary_node: rebuild_day failed for day %d", day_number)
        # Keep remaining queue so caller can decide whether to continue.
        rebuild_day_queue = remaining_queue
        rebuilt_days = [*rebuilt_days, day_number]
        return {
            "pending_tasks": pending_tasks,
            "task_results": [
                *task_results,
                {"worker": _WORKER_NAME, "status": "partial_error", "reply": f"Ngày {day_number} thất bại: {exc}"},
            ],
            "rebuild_day_queue": rebuild_day_queue,
            "rebuilt_days": rebuilt_days,
        }

    rebuilt_days = [*rebuilt_days, day_number]
    rebuild_day_queue = remaining_queue

    # If more days remain, return with a non-empty queue — the `all_tasks_done`
    # conditional edge will route back to supervisor which routes back here.
    if rebuild_day_queue:
        return {
            "pending_tasks": [*pending_tasks, _WORKER_NAME],  # re-queue self
            "task_results": task_results,
            "rebuild_day_queue": rebuild_day_queue,
            "rebuilt_days": rebuilt_days,
            "pending_suggest_operations": remaining_suggest_ops,
            "trip_data": trip_data,
        }

    # All days done — report completion.
    return {
        "pending_tasks": pending_tasks,
        "task_results": task_results,
        "rebuild_day_queue": [],
        "rebuilt_days": rebuilt_days,
        "pending_suggest_operations": remaining_suggest_ops,
        "trip_data": trip_data,
    }
