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
    travel_state: dict[str, Any] | None = None,
) -> Any:
    from src.agents.graph.state import TravelGraphState

    return TravelGraphState(
        session_id="test",
        language="vi",
        messages=[],
        travel_state=travel_state or {},
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
# The subgraph runs nested inside the turn, never on a thread of its own
# ---------------------------------------------------------------------------


class TestSubgraphRunsNested:
    """`_invoke_rebuild_day` must hand the subgraph no config at all.

    The ambient config of the running turn is what makes the call a *nested*
    subgraph run, and only a nested run carries `Command(resume=...)` into
    the shortlist `interrupt()` inside `fetch_and_schedule_node`. Supplying
    our own `thread_id` detaches it: the subgraph then catches its own
    `GraphInterrupt` and returns it as `__interrupt__` in the result dict,
    where `_invoke_rebuild_day` reads no `trip_data` and moves on — the user
    is never asked, and their pick is silently dropped.
    (`test_place_selection.py` proves the resume end to end.)
    """

    def test_invocation_passes_no_thread_id_of_its_own(self) -> None:
        from src.agents.graph.nodes.itinerary_node import (
            _REBUILD_DAY_SUBGRAPH,
            itinerary_node,
        )

        data = _make_trip_data(duration_days=2)
        configs_seen: list[dict] = []

        def recording_invoke(input_state, config=None, **kwargs):
            configs_seen.append(config or {})
            return {"trip_data": input_state.get("trip_data", {}), "rebuild_error": None}

        state = _state(data, "rebuild_days", [1, 2])
        with patch.object(_REBUILD_DAY_SUBGRAPH, "invoke", side_effect=recording_invoke):
            itinerary_node(state)

        assert configs_seen, "the subgraph was never invoked"
        for config in configs_seen:
            assert not (config.get("configurable") or {}).get("thread_id"), (
                f"subgraph was given its own thread_id ({config}) — "
                "that detaches it from the turn and breaks interrupt resume"
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

        def crash_on_day2(td, ts, dn, ld, suggest_ops=None):
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

        def record_invoke(td, ts, dn, ld, suggest_ops=None):
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


class TestDateSyncFromTravelState:
    """A "đổi ngày đi" edit patches `travel_state.dates.start`/`dates.end`
    correctly, but `trip_data`'s own itinerary row — what the frontend's
    trip header (`to_trip_plan_payload`) actually reads for the date
    range/day-count — is a separate snapshot taken when the trip was first
    built. Without a resync, the header stays stale even though the edit
    was applied."""

    def test_itinerary_node_resyncs_stale_dates_from_travel_state(self) -> None:
        from src.agents.graph.nodes.itinerary_node import itinerary_node

        data = _make_trip_data(duration_days=1)  # stale: 2026-09-15 → 2026-09-17

        with patch(
            "src.agents.graph.nodes.itinerary_node._invoke_rebuild_day",
            return_value=data,
        ):
            state = _state(
                data,
                "rebuild_days",
                [1],
                travel_state={
                    "dates.start": {"presence": "set", "value": "2026-07-01"},
                    "dates.end": {"presence": "set", "value": "2026-07-03"},
                },
            )
            result = itinerary_node(state)

        itinerary = result["trip_data"]["itineraries"][0]
        assert itinerary["start_date"] == "2026-07-01"
        assert itinerary["end_date"] == "2026-07-03"
        assert itinerary["duration_days"] == 2

    def test_itinerary_node_leaves_dates_alone_when_travel_state_has_none(self) -> None:
        """No `dates.start`/`dates.end` in `travel_state` (e.g. an
        unrelated edit) must not blank out the itinerary's own dates."""
        from src.agents.graph.nodes.itinerary_node import itinerary_node

        data = _make_trip_data(duration_days=1)

        with patch(
            "src.agents.graph.nodes.itinerary_node._invoke_rebuild_day",
            return_value=data,
        ):
            state = _state(data, "rebuild_days", [1])
            result = itinerary_node(state)

        itinerary = result["trip_data"]["itineraries"][0]
        assert itinerary["start_date"] == "2026-09-15"
        assert itinerary["end_date"] == "2026-09-17"


class TestChangeSummaryReply:
    """A finished `rebuild_days` op must say what changed per day, not just
    that a build finished — the day-rebuild counterpart to `edit_item`'s
    `adjustments` messages."""

    def test_single_day_rebuild_names_the_new_activities(self) -> None:
        from src.agents.graph.nodes.itinerary_node import itinerary_node

        data = _make_trip_data(duration_days=1)

        def rebuild_with_new_activities(td, ts, dn, ld, suggest_ops=None):
            new_data = copy.deepcopy(td)
            for item in new_data["itinerary_items"]:
                if item["day_number"] == dn:
                    item["activity"] = f"New activity {item['order_index']}"
            return new_data

        with patch(
            "src.agents.graph.nodes.itinerary_node._invoke_rebuild_day",
            side_effect=rebuild_with_new_activities,
        ):
            state = _state(data, "rebuild_days", [1])
            result = itinerary_node(state)

        reply = result["task_results"][-1]["reply"]
        assert "Ngày 1:" in reply
        assert "New activity 1" in reply
        # Accumulator resets once the final reply is built.
        assert result.get("rebuild_day_summaries") == []

    def test_unchanged_day_reports_no_change(self) -> None:
        from src.agents.graph.nodes.itinerary_node import itinerary_node

        data = _make_trip_data(duration_days=1)

        with patch(
            "src.agents.graph.nodes.itinerary_node._invoke_rebuild_day",
            return_value=data,
        ):
            state = _state(data, "rebuild_days", [1])
            result = itinerary_node(state)

        reply = result["task_results"][-1]["reply"]
        assert "giữ nguyên" in reply

    def test_multi_day_rebuild_across_turns_reports_every_day(self) -> None:
        """The summary for day 1 (built on turn 1) must survive into the
        final reply built on turn 2, the same way `rebuild_day_queue`/
        `rebuilt_days` survive the re-queue hop."""
        from src.agents.graph.nodes.itinerary_node import itinerary_node

        data = _make_trip_data(duration_days=2)

        def rebuild_with_new_activities(td, ts, dn, ld, suggest_ops=None):
            new_data = copy.deepcopy(td)
            for item in new_data["itinerary_items"]:
                if item["day_number"] == dn:
                    item["activity"] = f"Day {dn} new activity {item['order_index']}"
            return new_data

        with patch(
            "src.agents.graph.nodes.itinerary_node._invoke_rebuild_day",
            side_effect=rebuild_with_new_activities,
        ):
            state1 = _state(data, "rebuild_days", [1, 2])
            r1 = itinerary_node(state1)

            state2 = _state(
                r1["trip_data"],
                "rebuild_days",
                [1, 2],
                rebuild_day_queue=r1["rebuild_day_queue"],
                rebuilt_days=r1["rebuilt_days"],
            )
            state2["rebuild_day_summaries"] = r1.get("rebuild_day_summaries") or []
            r2 = itinerary_node(state2)

        reply = r2["task_results"][-1]["reply"]
        assert "Ngày 1:" in reply
        assert "Ngày 2:" in reply
        assert "Day 1 new activity 1" in reply
        assert "Day 2 new activity 1" in reply
