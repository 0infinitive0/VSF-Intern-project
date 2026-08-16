"""`rebuild_day` — compiled LangGraph subgraph for single-day itinerary rebuild.

Phase 9 (phase-09-itinerary-flow.md).

## Why a subgraph?

LangGraph re-executes a node **from the beginning** when an interrupted turn
resumes.  If the day-loop lived inside a single `itinerary_node` as a Python
``for``, resuming after a day-2 interrupt would re-run day-1's search —
producing different venues (``exclude_attraction_ids`` state changed) and
silently mutating content the user never touched.

A compiled subgraph gets its own checkpoint.  An interrupt on day 2 resumes
from within day 2's subgraph execution; day 1's checkpoint is already written
and is never re-executed.

## Checkpointer

Compiled explicitly with ``checkpointer=MemorySaver()``.  The parent graph
uses the app-lifespan Postgres checkpointer (Phase 4); this subgraph uses an
in-process MemorySaver so each day's checkpoint is independent without
requiring an extra Postgres connection.  The choice is stated here, not
inherited by accident — doc §rebuild_day says "Compile it with an explicit
``checkpointer=`` rather than relying on the default".

## State

``RebuildDayState`` carries:
- **Private keys** (scratch, not visible to parent): ``day_number``,
  ``day_theme``, ``rebuild_candidates`` (internal candidate lists).
- **Shared key** (read-write, synced to parent after the subgraph completes):
  ``trip_data`` — the whole trip bundle that ``_replace_day_in_json`` mutates
  in-place.

Phase 13 will add an ``interrupt()`` inside ``schedule_and_save_node`` for the
optional shortlist-pick flow.  That hook is noted below but not yet wired.
"""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.errors import GraphInterrupt
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt

from src.i18n import t
from src.services.trip_planner import rebuild_day_data, _current_trip_parameters, _get_destination_id, _apply_replace_or_add, EditOperation
from src.services.trip_edit_planner import ItemTarget, NewItemRequirements
from src.services.place_search import search_attraction_candidates
from src.services.hotel_selection import resolve_selection
from src.services.trip_scheduler import parse_coordinates

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Subgraph state
# ---------------------------------------------------------------------------


class RebuildDayState(TypedDict, total=False):
    """Private + shared state for the `rebuild_day` subgraph.

    The parent graph passes ``trip_data`` and reads it back after the subgraph
    completes.  ``day_number`` and ``day_theme`` are written by the parent
    *before* invoking the subgraph and consumed here.  ``rebuild_error`` lets
    the parent inspect failures without raising through the graph edge.
    """

    # --- shared with parent (read-write) ----------------------------------
    trip_data: dict[str, Any]  # full in-memory trip bundle

    # --- private (set by parent before invocation) ------------------------
    day_number: int
    day_theme: dict[str, Any]  # theme dict for this day (title, query, selection_mode, …)
    locked_days: list[int]  # defensive copy from parent

    # --- private scratch (produced inside the subgraph) -------------------
    suggest_operations: list[dict[str, Any]]
    rebuild_error: str | None  # non-None signals a hard failure to the parent


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


def fetch_and_schedule_node(state: RebuildDayState) -> dict[str, Any]:
    """Core node: fetch candidates and rebuild the target day.

    Calls ``rebuild_day_data`` (extracted from ``_build_trip_data``) which:
    1. Fetches candidates via ``_build_tiered_candidate_pools``.
    2. Schedules via ``build_itinerary``.
    3. Replaces the target day's items in-place via ``_replace_day_in_json``.
    4. Re-applies planning constraints for that day.

    No ``interrupt()`` yet — Phase 13 adds the shortlist-pick hook here.

    The node works on a deep copy of ``trip_data`` so a crash cannot corrupt
    the parent state.  The copy is promoted to the return dict only on success.
    """
    day_number: int = int(state.get("day_number") or 0)
    day_theme: dict[str, Any] = dict(state.get("day_theme") or {})
    locked_days: list[int] = list(state.get("locked_days") or [])
    suggest_operations: list[dict[str, Any]] = list(state.get("suggest_operations") or [])
    trip_data: dict[str, Any] = state.get("trip_data") or {}

    if not day_number:
        return {"rebuild_error": "rebuild_day: day_number not set in state"}

    working = deepcopy(trip_data)
    try:
        if suggest_operations:
            language = str(state.get("language") or "vi")
            destination, _, _, _ = _current_trip_parameters(working)
            destination_id = _get_destination_id(destination)
            hotel_coordinates = parse_coordinates((working.get("hotel") or {}).get("coordinates"))

            for op_dict in suggest_operations:
                op_target = op_dict.get("target") or {}
                op_reqs = op_dict.get("requirements") or {}
                query = op_reqs.get("semantic_query") or ""
                item_kind = op_reqs.get("item_kind") or ""
                item_id = op_target.get("item_id")

                if not query or not destination_id or not item_id or not item_kind:
                    continue

                # Search candidates, anchored at the hotel (Phase 8's rule:
                # never guess a center -- fall back to the trip-wide default
                # radius when no hotel coordinates are known yet).
                candidates = search_attraction_candidates(
                    query,
                    destination_id,
                    match_count=3,
                    root_latitude=hotel_coordinates[0] if hotel_coordinates else None,
                    root_longitude=hotel_coordinates[1] if hotel_coordinates else None,
                )
                if not candidates:
                    continue

                lines = [t("Mình tìm thấy một vài địa điểm phù hợp. Bạn chọn cái nào nhé?", language)]
                for idx, c in enumerate(candidates, 1):
                    line = f"{idx}. {c.name}"
                    if c.description:
                        line += f" ({c.description})"
                    lines.append(line)
                message_text = "\n".join(lines)

                payload = {
                    "type": "place_selection",
                    "message": message_text,
                    "options": [{"id": c.id, "name": c.name, "description": c.description} for c in candidates],
                }
                resume_text = str(interrupt(payload) or "")

                # `resolve_selection` matches by exact id, rank number, or
                # name substring against (data, candidate) tuples -- same
                # resolver the legacy `select_hotel` tool uses. `rank` must
                # match the 1-based numbering shown in `message_text` above,
                # or a bare "2" reply can never resolve via the rank path.
                resolved = resolve_selection(
                    resume_text,
                    [({"id": c.id, "name": c.name, "rank": idx}, c) for idx, c in enumerate(candidates, 1)],
                )
                if resolved is not None:
                    _data, selected_candidate = resolved
                    replace_op = EditOperation(
                        operation="replace_item",
                        target=ItemTarget(item_id=item_id, day_number=day_number),
                        requirements=NewItemRequirements(item_kind=item_kind, semantic_query=query),
                        preselected_candidate=selected_candidate,
                    )
                    _apply_replace_or_add(working, replace_op)
        else:
            rebuild_day_data(
                working,
                day_number,
                day_theme,
                locked_days=locked_days,
            )
    except GraphInterrupt:
        # `interrupt()` (above) raises this to pause the graph -- it MUST
        # propagate to the graph executor, never get swallowed as a regular
        # failure. `except Exception` below would otherwise catch it too,
        # silently turning every shortlist pause into a `rebuild_error`.
        raise
    except Exception as exc:
        logger.exception(
            "rebuild_day: failed to rebuild day %d: %s", day_number, exc
        )
        return {"rebuild_error": f"rebuild_day day {day_number}: {exc}"}

    return {
        "trip_data": working,
        "rebuild_error": None,
    }


# ---------------------------------------------------------------------------
# Subgraph compilation
# ---------------------------------------------------------------------------

# Fallback checkpointer for a STANDALONE invocation (tests drive the subgraph
# directly with their own `thread_id`). In production the subgraph always runs
# nested inside a turn, and a nested run takes the parent's checkpointer and
# namespace instead — nothing accumulates here.
_SUBGRAPH_CHECKPOINTER = MemorySaver()


def build_rebuild_day_subgraph(
    checkpointer: Any | None = None,
) -> CompiledStateGraph:
    """Compile and return the ``rebuild_day`` subgraph.

    ``checkpointer`` is accepted so callers can supply a test-scoped
    MemorySaver without sharing the module-level instance.  Production code
    uses the default module-level MemorySaver.

    The explicit ``checkpointer=`` kwarg to ``compile()`` satisfies the plan's
    requirement: "stated, not inherited by accident."
    """
    effective_checkpointer = checkpointer if checkpointer is not None else _SUBGRAPH_CHECKPOINTER

    builder: StateGraph = StateGraph(RebuildDayState)
    builder.add_node("fetch_and_schedule", fetch_and_schedule_node)

    builder.add_edge(START, "fetch_and_schedule")
    builder.add_edge("fetch_and_schedule", END)

    return builder.compile(checkpointer=effective_checkpointer)
