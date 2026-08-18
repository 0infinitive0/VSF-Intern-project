"""`itinerary_node` — the itinerary **editor**.

This node edits a trip that already exists; it cannot create one. Every
action it has operates on `trip_data`, and `trip_data` is created by
`hotel_node` when the user picks a hotel (`build_selected_hotel_trip`, which
builds the hotel and the whole itinerary in one pass). That ordering is
causal, not stylistic: the itinerary is scheduled around the hotel's
location, so it cannot be laid out before we know where the user is staying.
`routing.requires_existing_trip` is the guard that states this, and the
supervisor's `needs_trip_first` redirect is what happens when a user asks for
an itinerary before there is a trip to edit.

This node:

1. Reads the action from ``task_description`` (set by the supervisor).
2. For day-rebuild actions (``rebuild_days``):
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
5. For ``list_nearby`` (read-only):
   - Searches for notable places around the hotel via
     ``search_attraction_candidates`` and replies with the list.
   - Never touches ``trip_data`` — unlike the other three actions, this is a
     lookup, not an edit.

### Interrupt isolation

Each ``rebuild_day`` invocation is a *compiled subgraph* run nested inside the
current turn, so it gets its own checkpoint namespace under the parent task.
When the subgraph suspends mid-execution (the shortlist pick in
``fetch_and_schedule_node``), the interrupt propagates to the parent and the
resume restarts from inside the subgraph for *that day only* — days already
checkpointed complete are not re-run.  Handing the subgraph a ``thread_id`` of
our own would break that chain; ``_invoke_rebuild_day`` says why.

### `task_description` format

The supervisor sets ``task_description`` to a JSON string:
```json
{
  "action": "rebuild_days" | "edit_item" | "lock_days" | "list_nearby",
  "day_numbers": [1, 2],        // for rebuild_days; absent → all days
  "user_request": "...",        // for edit_item / list_nearby
  "days_to_lock": [1],          // for lock_days
  "radius_km": 3                // optional, for list_nearby — see _resolve_radius_km
}
```
``build_itinerary`` is accepted as a **historical alias** for ``rebuild_days``,
not a fourth action: a checkpointer thread written before the rename can still
carry it in a stored ``task_description``. It never built anything from
scratch — every path through it bails when ``trip_data`` is empty.

If ``task_description`` is a plain string (legacy supervisor calls that haven't
been updated yet), the node falls back to ``rebuild_days`` for all days.
"""

from __future__ import annotations

import json
import logging
import re
from copy import deepcopy
from typing import Any

from langgraph.errors import GraphInterrupt

from src.agents.graph.state import TravelGraphState
from src.agents.graph.subgraphs.rebuild_day import build_rebuild_day_subgraph
from src.domain.travel_state import Presence, TravelState, trip_duration_days
from src.i18n import t
from src.services.place_search import search_attraction_candidates
from src.services.supabase_search import DEFAULT_NEARBY_SEARCH_RADIUS_KM
from src.services.trip_formatter import format_trip_summary_reply
from src.services.trip_planner import (
    _get_locked_days,
    _itinerary_record,
    apply_trip_edit_plan,
)
from src.services.trip_edit_planner import TripEditPlanError, plan_trip_edit
from src.services.trip_scheduler import parse_coordinates

logger = logging.getLogger(__name__)

_WORKER_NAME = "itinerary_node"

# "trong bán kính 3km", "within 3 km", "3.5km" -- the first bare "<number>
# km" in the request. Deterministic, not LLM-parsed: same reasoning as
# `extract_patch`'s day-scope rewrite -- a number the model copies into a
# structured field is trusted less than one a regex pulls from the user's
# own text.
_RADIUS_PATTERN = re.compile(r"(\d+(?:[.,]\d+)?)\s*km", re.IGNORECASE)

_NEARBY_MATCH_COUNT = 8

# One compiled subgraph instance shared across turns. It carries no state of
# its own: every invocation runs nested inside the calling turn, so the
# checkpoint namespace (and the checkpointer itself) comes from the parent —
# see `_invoke_rebuild_day`.
_REBUILD_DAY_SUBGRAPH = build_rebuild_day_subgraph()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_task(task_description: str) -> dict[str, Any]:
    """Parse the supervisor-supplied task description into a plain dict.

    Supports both JSON (preferred) and legacy plain-string fallback. The
    default is ``rebuild_days`` (all days) because that is what this node
    actually does; ``build_itinerary`` remains an accepted alias for it, not
    a distinct capability — see the module docstring.
    """
    if not task_description:
        return {"action": "rebuild_days"}
    try:
        parsed = json.loads(task_description)
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, ValueError):
        pass
    # Legacy/plain string fallback — treat as a rebuild request.
    return {"action": "rebuild_days", "user_request": task_description}


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


def _theme_for_day(trip_data: dict[str, Any], travel_state: TravelState, day_number: int) -> dict[str, Any]:
    """Return the theme to rebuild *day_number* with.

    `daily_preferences.<day>.theme` (set via the ordinary patch pipeline —
    `extract_patch`'s day-scope rewrite, Phase 16's clarify branch) takes
    priority over whatever `trip_data` has stored: without this, a user's
    "change day 1's theme" edit validates, stores, and correctly triggers
    this exact rebuild, then gets silently ignored, because `trip_data`'s
    own `day_themes` record is a separate copy this node never synced it
    into (the same class of bug `_sync_locked_days_from_travel_state`
    already fixes for `locked_days` — this is that fix's counterpart for
    day themes).

    `selection_mode: "user_specified"` is the second half of that: it is
    the flag `normalize_day_themes` (`trip_scheduler.py`) already checks to
    preserve a theme's `title`/`query` verbatim instead of re-deriving them
    from trip-level `preferences.themes` — the same mechanism
    `trip_edit_planner.py`'s `replan_day` operation already relies on for a
    user-specified day theme. Without this flag, even a correctly-read
    theme would still be overwritten by a preference-rotation pick.
    """
    slot = travel_state.get(f"daily_preferences.{day_number}.theme")
    if slot.presence is Presence.SET and slot.value:
        value = str(slot.value).strip()
        if value:
            return {"day_number": day_number, "title": value, "query": value, "selection_mode": "user_specified"}

    itinerary_rows = trip_data.get("itineraries") or [{}]
    itinerary = itinerary_rows[0] if isinstance(itinerary_rows, list) else itinerary_rows
    for theme in itinerary.get("day_themes") or []:
        if int(theme.get("day_number") or 0) == day_number:
            return dict(theme)
    return {"day_number": day_number, "title": f"Ngày {day_number}", "query": ""}


def _day_activities(trip_data: dict[str, Any], day_number: int) -> list[str]:
    """Ordered activity names scheduled for one day, read from `itinerary_items`."""
    items = [
        item
        for item in (trip_data.get("itinerary_items") or [])
        if isinstance(item, dict) and int(item.get("day_number") or 0) == day_number
    ]
    items.sort(key=lambda item: (str(item.get("start_time") or ""), int(item.get("order_index") or 0)))
    return [str(item.get("activity") or "").strip() for item in items if item.get("activity")]


def _describe_day_change(day_number: int, before: list[str], after: list[str], language: str) -> str:
    """One-line "what changed" summary for a rebuilt day.

    `rebuild_days` regenerates the whole day rather than editing individual
    items, so there is no per-operation adjustment list the way `edit_item`
    has (`apply_trip_edit_plan`'s ``adjustments``). This is that feature's
    day-rebuild counterpart: a before/after activity-name comparison, cheap
    to compute because both snapshots are in hand within the same node
    invocation that calls ``_invoke_rebuild_day``.
    """
    if before == after:
        return t("Ngày {day}: giữ nguyên lịch trình cũ.", language, day=day_number)
    if not after:
        return t("Ngày {day}: đã xoá toàn bộ hoạt động.", language, day=day_number)
    return t("Ngày {day}: {activities}.", language, day=day_number, activities=", ".join(after))


_RADIUS_KM_RANGE = (0, 50)  # exclusive-min, matches `hotel_preferences.radius_km` (travel_state.py)


def _extract_radius_km(user_request: str) -> float:
    """First bare "<number> km" in *user_request*, or the shared nearby-search
    default (`DEFAULT_NEARBY_SEARCH_RADIUS_KM`) when none is stated."""
    match = _RADIUS_PATTERN.search(user_request)
    if not match:
        return DEFAULT_NEARBY_SEARCH_RADIUS_KM
    try:
        return float(match.group(1).replace(",", "."))
    except ValueError:
        return DEFAULT_NEARBY_SEARCH_RADIUS_KM


def _resolve_radius_km(task: dict[str, Any], user_request: str) -> float:
    """The radius to search within, in priority order:

    1. `task["radius_km"]` — the supervisor LLM's read of the user's own
       words, when it is an actual number inside the sane range.
    2. `_extract_radius_km(user_request)` — a deterministic regex re-read of
       the same text, used when the LLM left it unset or (same "don't trust
       the model on a number" stance as every other LLM-parsed numeric field
       in this codebase) returned something out of range.
    3. `DEFAULT_NEARBY_SEARCH_RADIUS_KM` — no distance stated anywhere.
    """
    llm_radius = task.get("radius_km")
    if isinstance(llm_radius, (int, float)) and not isinstance(llm_radius, bool):
        low, high = _RADIUS_KM_RANGE
        if low < llm_radius <= high:
            return float(llm_radius)
    return _extract_radius_km(user_request)


def _format_radius(radius_km: float) -> str:
    return str(int(radius_km)) if radius_km == int(radius_km) else str(radius_km)


def _format_nearby_reply(candidates: list[Any], radius_km: float, language: str) -> str:
    if not candidates:
        return t(
            "Mình chưa tìm thấy địa điểm nổi bật nào trong bán kính {radius} km quanh khách sạn.",
            language,
            radius=_format_radius(radius_km),
        )
    lines = [
        t(
            "Trong bán kính {radius} km quanh khách sạn, có những địa điểm nổi bật sau:",
            language,
            radius=_format_radius(radius_km),
        )
    ]
    for idx, candidate in enumerate(candidates, 1):
        line = f"{idx}. {candidate.name}"
        if candidate.category:
            line += f" ({candidate.category})"
        if candidate.description:
            line += f" — {candidate.description}"
        lines.append(line)
    return "\n".join(lines)


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


def _sync_dates_from_travel_state(trip_data: dict[str, Any], travel_state: TravelState) -> None:
    """Replace the itinerary's own `start_date`/`end_date`/`duration_days`
    with `TravelState`'s `dates.start`/`dates.end` (the same class of bug
    `_sync_locked_days_from_travel_state` already fixes for `locked_days`):
    a "đổi ngày đi" edit validates and patches `travel_state` correctly, but
    `trip_data`'s own copy — what `to_trip_plan_payload` actually reads for
    the header's date range/day-count — is a separate snapshot taken when
    the trip was first built, and nothing else re-syncs it afterward."""
    if travel_state.get("dates.start").presence is not Presence.SET or travel_state.get("dates.end").presence is not Presence.SET:
        return
    itinerary_rows = trip_data.get("itineraries") or [{}]
    itinerary = itinerary_rows[0] if isinstance(itinerary_rows, list) and itinerary_rows else {}
    if not isinstance(itinerary, dict):
        return
    duration_days = trip_duration_days(travel_state)
    if duration_days is None:
        return
    itinerary["start_date"] = travel_state.get("dates.start").value
    itinerary["end_date"] = travel_state.get("dates.end").value
    itinerary["duration_days"] = duration_days


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
    travel_state: TravelState,
    day_number: int,
    locked_days: list[int],
    suggest_ops: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Call the ``rebuild_day`` subgraph for one day.

    Returns the updated ``trip_data`` dict or raises on unrecoverable error.

    Invoked with **no config of its own**, on purpose: the ambient config of
    the running turn makes this a nested subgraph run, which is what carries
    `Command(resume=...)` from `_run_turn_via_graph` into the place-selection
    pause inside `fetch_and_schedule_node`. Handing it a `thread_id` of our
    own detaches it from the turn — the subgraph then
    catches its own `GraphInterrupt` and returns it as `__interrupt__` in the
    result dict, so the question never reaches the user and their pick is
    silently dropped.

    Day isolation is unaffected: this node rebuilds ONE day per invocation,
    and on resume LangGraph replays only the day whose subgraph was
    suspended — days already checkpointed complete are not re-executed.
    """
    theme = _theme_for_day(trip_data, travel_state, day_number)
    result = _REBUILD_DAY_SUBGRAPH.invoke(
        {
            "trip_data": trip_data,
            "day_number": day_number,
            "day_theme": theme,
            "locked_days": locked_days,
        }
        | ({"suggest_operations": suggest_ops} if suggest_ops else {}),
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
    action = str(task.get("action") or "rebuild_days")

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
    if trip_data:
        _sync_dates_from_travel_state(trip_data, travel_state)

    rebuild_day_queue: list[int] = list(state.get("rebuild_day_queue") or [])
    rebuilt_days: list[int] = list(state.get("rebuilt_days") or [])
    rebuild_day_summaries: list[str] = list(state.get("rebuild_day_summaries") or [])
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
        """A failure the user can act on — the text goes to them verbatim."""
        entry: dict[str, Any] = {"worker": _WORKER_NAME, "status": "error", "reply": reply}
        return {
            "pending_tasks": pending_tasks,
            "task_results": [*task_results, entry],
            "rebuild_day_queue": rebuild_day_queue,
            "rebuilt_days": rebuilt_days,
        }

    def _malformed_task(detail: str) -> dict[str, Any]:
        """A task the supervisor built wrong — nothing the user can do about
        it, and naming our internals at them ("lock_days: days_to_lock is
        empty") only makes a bad turn confusing as well. The detail goes to
        the log, where whoever can fix it will look."""
        logger.error("%s: malformed task — %s", _WORKER_NAME, detail)
        return _err(t("Mình chưa hiểu yêu cầu này, bạn nói rõ hơn giúp mình nhé.", language))

    # ── lock_days ────────────────────────────────────────────────────────────
    if action == "lock_days":
        days_to_lock = [int(d) for d in (task.get("days_to_lock") or [])]
        if not days_to_lock:
            return _malformed_task("lock_days received an empty days_to_lock")
        if not trip_data:
            return _err(t("Chưa có lịch trình nào để khoá ngày.", language))
        _set_locked_days(trip_data, days_to_lock)
        return _ok(f"Đã khoá ngày: {days_to_lock}.")

    # ── list_nearby (read-only) ─────────────────────────────────────────────
    if action == "list_nearby":
        if not trip_data:
            return _err(
                t(
                    "Mình cần bạn chọn khách sạn trước — mình sẽ tìm địa điểm quanh vị trí đó.",
                    language,
                )
            )
        hotel = trip_data.get("hotel") or {}
        coordinates = parse_coordinates(hotel.get("coordinates"))
        destination_id = hotel.get("destination_id")
        if not coordinates or not destination_id:
            return _err(t("Mình chưa có vị trí khách sạn để tìm địa điểm gần đó.", language))
        user_request = str(task.get("user_request") or "địa điểm nổi bật")
        radius_km = _resolve_radius_km(task, user_request)
        candidates = search_attraction_candidates(
            user_request,
            destination_id,
            match_count=_NEARBY_MATCH_COUNT,
            root_latitude=coordinates[0],
            root_longitude=coordinates[1],
            max_radius_km=radius_km,
        )
        return _ok(_format_nearby_reply(candidates, radius_km, language))

    # ── edit_item ────────────────────────────────────────────────────────────
    if action == "edit_item":
        user_request = str(task.get("user_request") or "")
        if not user_request:
            return _malformed_task("edit_item received an empty user_request")
        if not trip_data:
            return _err(t("Chưa có lịch trình nào để chỉnh sửa.", language))
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

    # ── rebuild_days (alias: build_itinerary) ─────────────────────────────────
    # One name, one behaviour: rebuild the affected days of an EXISTING trip.
    # `build_itinerary` is kept as an accepted alias because a checkpointer
    # thread written before the rename can still carry it in a stored
    # `task_description`.
    if action not in ("rebuild_days", "build_itinerary"):
        return _malformed_task(f"unknown action {action!r}")

    # On the FIRST invocation for this turn, populate rebuild_day_queue.
    if not rebuild_day_queue:
        if not trip_data:
            # Reached only if the supervisor's `needs_trip_first` redirect
            # was bypassed — say what to do next, not what went wrong.
            return _err(
                t(
                    "Mình cần bạn chọn khách sạn trước — lịch trình sẽ được xếp quanh vị trí đó.",
                    language,
                )
            )
        locked: frozenset[int] = _get_locked_days(trip_data)
        requested_days = task.get("day_numbers")
        all_days = _affected_days(trip_data, requested_days if isinstance(requested_days, list) else None)
        rebuild_day_queue = [d for d in all_days if d not in locked]
        if not rebuild_day_queue:
            locked_list = sorted(locked)
            return _ok(
                f"Tất cả các ngày yêu cầu đều bị khoá {locked_list}; không có ngày nào cần xây dựng lại.",
            )
        # A fresh rebuild op starting -- discard any summary left over from a
        # prior, unrelated rebuild (already `[]` on the normal completion
        # path; this also covers a queue that was abandoned mid-loop).
        rebuild_day_summaries = []

    # Pop the first day from the queue and invoke the subgraph for it.
    day_number = rebuild_day_queue[0]
    remaining_queue = rebuild_day_queue[1:]
    locked_days_list = sorted(_get_locked_days(trip_data))
    before_activities = _day_activities(trip_data, day_number)

    pending_suggest_ops = list(state.get("pending_suggest_operations") or [])
    current_day_suggest_ops = [op for op in pending_suggest_ops if str(op.get("target", {}).get("day_number")) == str(day_number) or (not op.get("target", {}).get("day_number") and day_number == 1)]
    remaining_suggest_ops = [op for op in pending_suggest_ops if op not in current_day_suggest_ops]

    try:
        trip_data = _invoke_rebuild_day(
            trip_data, travel_state, day_number, locked_days_list, suggest_ops=current_day_suggest_ops
        )
    except GraphInterrupt:
        # The shortlist pause inside the subgraph -- control flow, not a
        # failure. Now that the subgraph runs nested in this turn, that pause
        # propagates out through here, and `except Exception` below would
        # catch it: the question the user was about to be asked would reach
        # them as "Ngày N thất bại" instead.
        raise
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
            "rebuild_day_summaries": rebuild_day_summaries,
        }

    rebuilt_days = [*rebuilt_days, day_number]
    rebuild_day_queue = remaining_queue
    after_activities = _day_activities(trip_data, day_number)
    rebuild_day_summaries = [
        *rebuild_day_summaries,
        _describe_day_change(day_number, before_activities, after_activities, language),
    ]

    # If more days remain, return with a non-empty queue — the `all_tasks_done`
    # conditional edge will route back to supervisor which routes back here.
    if rebuild_day_queue:
        return {
            "pending_tasks": [*pending_tasks, _WORKER_NAME],  # re-queue self
            "task_results": task_results,
            "rebuild_day_queue": rebuild_day_queue,
            "rebuilt_days": rebuilt_days,
            "rebuild_day_summaries": rebuild_day_summaries,
            "pending_suggest_operations": remaining_suggest_ops,
            "trip_data": trip_data,
        }

    # All days done — report completion *out loud*. This is the path every
    # successful build ends on, and until the `emits_reply` contract it
    # returned `task_results` untouched: `respond` found nothing to say and
    # fell through to the generic acknowledgement, so a finished five-day
    # itinerary was announced as "Đã cập nhật thông tin chuyến đi.".
    #
    # A short confirmation, not the whole itinerary as text: the UI already
    # renders the plan from `trip_plan` (day timeline, per-day route, hotel
    # card), so dumping it again as chat text made the user read the same
    # thing twice. It still names the hotel and the day count, so it stays a
    # specific reply — a silent worker cannot hide behind it. Deterministic,
    # read from the trip actually built, so no number can be invented.
    #
    # Prefixed with one "Ngày N: ..." line per day this op actually rebuilt
    # (`rebuild_day_summaries`) so the user sees what changed, not just that
    # something did — the day-rebuild counterpart to `edit_item`'s
    # `adjustments` messages.
    change_lines = "\n".join(rebuild_day_summaries)
    completion = format_trip_summary_reply(trip_data, language)
    reply = f"{change_lines}\n{completion}" if change_lines else completion
    return {
        "pending_tasks": pending_tasks,
        "task_results": [
            *task_results,
            {
                "worker": _WORKER_NAME,
                "status": "ok",
                "reply": reply,
            },
        ],
        "rebuild_day_queue": [],
        "rebuilt_days": rebuilt_days,
        "rebuild_day_summaries": [],
        "pending_suggest_operations": remaining_suggest_ops,
        "trip_data": trip_data,
    }
