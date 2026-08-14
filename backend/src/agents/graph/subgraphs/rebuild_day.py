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
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt

from src.services.trip_planner import rebuild_day_data, _current_trip_parameters, _get_destination_id, _apply_replace_or_add, EditOperation
from src.services.place_search import search_attraction_candidates
from src.services.hotel_selection import resolve_selection

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
            from dataclasses import dataclass
            
            @dataclass(frozen=True)
            class MockRequirements:
                item_kind: str
                semantic_query: str
                
            @dataclass(frozen=True)
            class MockTarget:
                item_id: str
                
            for op_dict in suggest_operations:
                op_target = op_dict.get("target") or {}
                op_reqs = op_dict.get("requirements") or {}
                query = op_reqs.get("semantic_query") or ""
                
                # Extract destination
                destination, _, _, _ = _current_trip_parameters(working)
                destination_id = _get_destination_id(destination)
                
                if not query or not destination_id:
                    continue
                    
                # Search candidates
                candidates = search_attraction_candidates(
                    destination=destination,
                    destination_id=destination_id,
                    query=query,
                    near=None,  # Fallback to no center for now if not provided
                    limit=3,
                )
                
                if not candidates:
                    continue
                    
                # Format options text
                from src.i18n import t
                language = str(state.get("language") or "vi")
                lines = [t("Mình tìm thấy một vài địa điểm phù hợp. Bạn chọn cái nào nhé?", language)]
                for idx, c in enumerate(candidates, 1):
                    lines.append(f"{idx}. {c.venue_name} ({c.description})")
                message_text = "\n".join(lines)
                    
                # Prepare payload
                payload = {
                    "type": "place_selection",
                    "message": message_text,
                    "options": [
                        {
                            "id": c.venue_id,
                            "name": c.venue_name,
                            "description": c.description,
                        }
                        for c in candidates
                    ],
                }
                
                # Interrupt and get user choice
                resume_text = str(interrupt(payload) or "")
                
                # Resolve selection
                resolution = resolve_selection(resume_text, candidates, "vi")
                
                if resolution.resolved and resolution.selection:
                    # Apply replace_item
                    from src.services.trip_edit_planner import EditOperation
                    replace_op = EditOperation(
                        operation="replace_item",
                        target=MockTarget(item_id=op_target.get("item_id")),
                        requirements=MockRequirements(item_kind=op_reqs.get("item_kind"), semantic_query=query),
                        replacement_candidate=resolution.selection,
                    )
                    _apply_replace_or_add(working, replace_op)
                    
        else:
            rebuild_day_data(
                working,
                day_number,
                day_theme,
                locked_days=locked_days,
            )
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

# One shared MemorySaver instance for the subgraph — each call to `invoke`
# uses a distinct `thread_id` so checkpoints are isolated per day per turn.
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
