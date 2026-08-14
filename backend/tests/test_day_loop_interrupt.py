"""Tests for Phase 9: interrupt isolation and day-loop checkpoint guarantee.

Success criteria from phase-09-itinerary-flow.md §Success Criteria:
- Interrupt on day 2, then resume: day 1 unchanged, no day-1 search re-issued.
- A crash mid-loop resumes from the next unbuilt day, not from day 1.
- Each rebuild_day invocation gets an independent checkpoint thread_id.
"""
from __future__ import annotations

import copy
import json
import uuid
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from tests.test_rebuild_day import _make_trip_data, json_task


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _state(
    trip_data: dict[str, Any],
    action: str,
    day_numbers: list[int] | None = None,
    rebuild_day_queue: list[int] | None = None,
    rebuilt_days: list[int] | None = None,
) -> Any:
    from src.agents.graph.state import TravelGraphState

    return TravelGraphState(
        session_id="test",
        language="vi",
        messages=[],
        travel_state={},
        trip_data=trip_data,
        patch=[],
        intent="",
        proposed_travel_state={},
        applied_changes=[],
        rejected_changes=[],
        impacted_workflows=[],
        unresolved_resume_text=None,
        missing_slots=[],
        next_question=None,
        jailbreak_blocked=False,
        supervisor_iterations=0,
        pending_tasks=["itinerary_node"],
        next_worker=None,
        task_description=json_task(action, day_numbers),
        task_results=[],
        routing_source="",
        routing_reasoning="",
        rebuild_day_queue=list(rebuild_day_queue or []),
        rebuilt_days=list(rebuilt_days or []),
        response={},
    )


# ---------------------------------------------------------------------------
# Checkpoint isolation: unique thread_id per day
# ---------------------------------------------------------------------------


class TestCheckpointIsolation:
    """Each `_invoke_rebuild_day` call must use a distinct thread_id so
    interrupts on day N cannot share state with day M≠N.

    We verify this by intercepting the subgraph `invoke` call and checking
    that the `thread_id` in `config.configurable` differs across days.
    """

    def test_unique_thread_id_per_day(self) -> None:
        from src.agents.graph.nodes.itinerary_node import (
            _REBUILD_DAY_SUBGRAPH,
            itinerary_node,
        )

        data = _make_trip_data(duration_days=2)
        thread_ids_seen: list[str] = []

        original_invoke = _REBUILD_DAY_SUBGRAPH.invoke

        def recording_invoke(input_state, config=None, **kwargs):
            tid = (config or {}).get("configurable", {}).get("thread_id", "")
            thread_ids_seen.append(tid)
            # Return minimal success state
            return {"trip_data": input_state.get("trip_data", {}), "rebuild_error": None}

        # Process day 1
        state1 = _state(data, "rebuild_days", [1, 2])
        with patch.object(_REBUILD_DAY_SUBGRAPH, "invoke", side_effect=recording_invoke):
            r1 = itinerary_node(state1)

        # Process day 2 (still in queue after r1)
        queue = r1.get("rebuild_day_queue") or []
        td = r1.get("trip_data") or data
        if queue:
            state2 = _state(td, "rebuild_days", [1, 2], rebuild_day_queue=queue, rebuilt_days=r1.get("rebuilt_days") or [])
            with patch.object(_REBUILD_DAY_SUBGRAPH, "invoke", side_effect=recording_invoke):
                itinerary_node(state2)

        # Each invocation should have used a distinct thread_id
        assert len(thread_ids_seen) >= 1
        assert len(set(thread_ids_seen)) == len(thread_ids_seen), (
            f"Duplicate thread_ids found: {thread_ids_seen} — "
            "checkpoint isolation guarantee violated"
        )


# ---------------------------------------------------------------------------
# Crash mid-loop: resume from next unbuilt day
# ---------------------------------------------------------------------------


class TestCrashMidLoop:
    """If day 2 crashes, the node returns with rebuild_day_queue=[3] so the
    caller can route back and continue from day 3 without re-running day 1.
    """

    def test_crash_on_day2_keeps_day3_in_queue(self) -> None:
        from src.agents.graph.nodes.itinerary_node import itinerary_node

        data = _make_trip_data(duration_days=3)

        # Simulate: day 1 already done, day 2 is in queue, day 3 is after
        state = _state(
            data,
            "rebuild_days",
            [1, 2, 3],
            rebuild_day_queue=[2, 3],
            rebuilt_days=[1],
        )

        def crash_on_day2(td, dn, ld):
            if dn == 2:
                raise RuntimeError("Day 2 search failed (simulated)")
            return td

        with patch(
            "src.agents.graph.nodes.itinerary_node._invoke_rebuild_day",
            side_effect=crash_on_day2,
        ):
            result = itinerary_node(state)

        # Day 3 should still be in the queue
        remaining = result.get("rebuild_day_queue") or []
        assert 3 in remaining, (
            f"Day 3 dropped from queue after day-2 crash; queue={remaining}"
        )
        # Day 1 (already done) must NOT be in the queue
        assert 1 not in remaining

        # Status should indicate partial error, not a full failure
        task_results = result.get("task_results") or []
        statuses = [r.get("status") for r in task_results]
        assert "partial_error" in statuses, (
            f"Expected partial_error status; got {statuses}"
        )


# ---------------------------------------------------------------------------
# Day-1 is NOT re-searched after day-2 interrupt/resume
# ---------------------------------------------------------------------------


class TestInterruptIsolation:
    """Simulates the interrupt-isolation scenario:
    1. Turn 1 — process day 1, return with queue=[2, 3].
    2. Turn 2 (resume) — process day 2 from queue; day-1 rebuild must NOT fire again.

    We verify by counting how many times _invoke_rebuild_day was called with
    day_number=1.  After the resume, that count must remain at 1.
    """

    def test_day1_not_rebuilt_on_resume(self) -> None:
        from src.agents.graph.nodes.itinerary_node import itinerary_node

        data = _make_trip_data(duration_days=3)
        call_log: list[int] = []

        def record_invoke(td, dn, ld, suggest_ops=None):
            call_log.append(dn)
            return td

        with patch(
            "src.agents.graph.nodes.itinerary_node._invoke_rebuild_day",
            side_effect=record_invoke,
        ):
            # Turn 1: initial call for all days → processes day 1 only
            state1 = _state(data, "rebuild_days", [1, 2, 3])
            r1 = itinerary_node(state1)

        day1_count_after_turn1 = call_log.count(1)
        queue_after_turn1 = r1.get("rebuild_day_queue") or []

        assert day1_count_after_turn1 == 1, (
            f"Expected exactly 1 rebuild for day 1 in turn 1; got {day1_count_after_turn1}"
        )
        assert 2 in queue_after_turn1 or 3 in queue_after_turn1, (
            "Remaining days must be in queue for next turn"
        )

        # Turn 2 (resume): process next day from queue
        td = r1.get("trip_data") or data
        rebuilt = r1.get("rebuilt_days") or [1]
        state2 = _state(td, "rebuild_days", [1, 2, 3], rebuild_day_queue=queue_after_turn1, rebuilt_days=rebuilt)

        with patch(
            "src.agents.graph.nodes.itinerary_node._invoke_rebuild_day",
            side_effect=record_invoke,
        ):
            itinerary_node(state2)

        day1_count_total = call_log.count(1)
        assert day1_count_total == 1, (
            f"Day 1 was rebuilt {day1_count_total} times; expected exactly 1. "
            f"Call log: {call_log}"
        )


# ---------------------------------------------------------------------------
# Queue mechanics: re-queues self when days remain
# ---------------------------------------------------------------------------


class TestQueueMechanics:
    def test_itinerary_node_requeues_itself_when_days_remain(self) -> None:
        """When the rebuild_day_queue still has entries after processing one
        day, `itinerary_node` must add itself back to `pending_tasks` so the
        parent graph loops back through the supervisor."""
        from src.agents.graph.nodes.itinerary_node import itinerary_node

        data = _make_trip_data(duration_days=3)

        with patch(
            "src.agents.graph.nodes.itinerary_node._invoke_rebuild_day",
            return_value=data,
        ):
            state = _state(data, "rebuild_days", [1, 2, 3])
            result = itinerary_node(state)

        remaining_queue = result.get("rebuild_day_queue") or []
        pending = result.get("pending_tasks") or []

        if remaining_queue:
            assert "itinerary_node" in pending, (
                "itinerary_node must re-queue itself when rebuild_day_queue is non-empty"
            )

    def test_itinerary_node_does_not_requeue_when_done(self) -> None:
        """When the queue empties, `itinerary_node` must NOT add itself back
        to `pending_tasks` — it reports completion so the graph can proceed."""
        from src.agents.graph.nodes.itinerary_node import itinerary_node

        data = _make_trip_data(duration_days=1)

        with patch(
            "src.agents.graph.nodes.itinerary_node._invoke_rebuild_day",
            return_value=data,
        ):
            # Only 1 day, so after processing the queue empties
            state = _state(data, "rebuild_days", [1])
            result = itinerary_node(state)

        pending = result.get("pending_tasks") or []
        assert "itinerary_node" not in pending, (
            "itinerary_node must NOT re-queue itself when all days are done"
        )
