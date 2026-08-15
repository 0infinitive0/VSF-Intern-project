"""`respond` — builds the frozen `PlannerChatResponse` field shape from
whatever the turn's nodes actually did. Every path through the graph flows
through this node before `END` (Phase 5 functional requirement: the graph
must return a response indistinguishable in *shape* from the legacy
plane), even a `max_iterations` bail-out or an `ask_slot` question.

Reply text priority:
1. `ask_slot`'s `next_question` (Phase 7) — a required slot is still
   missing, so nothing downstream of `ask_slot` ran this turn
   (`route_ask_slot` sends `"ask"` straight here). This must win over
   everything below: `messages`/`task_results` could otherwise carry a
   stale prior-turn answer forward on a turn that asked a fresh question.
2. The last worker's own reply (`booking_node`'s decline, or any future
   worker that sets one) — `task_results[-1]["reply"]`.
3. `qa_node`'s answer — the last AI message in `messages`, the only
   channel that subgraph shares with the parent.
4. A generic acknowledgement, for the pass-through stub workers
   (`hotel_node`/`itinerary_node`) that have nothing to say yet.

`stage` stays at its Phase-5 placeholder value — hotel_node/itinerary_node
don't produce real trip data until Phases 8-9, so deriving a richer stage now
would be guessing.

`hotel_options` (Phase 8): the most recent worker's own `hotel_options` list
when present — `hotel_node` sets it on every turn it runs, including an
empty list on a zero-result turn, so a stale prior turn's cards never leak
forward. `compound_min_price`/`compound_max_price`/`all_preferences`/
`active_preferences` stay Phase-5 placeholders — those are the legacy
plane's multi-turn accumulation bookkeeping, which Phase 8 deliberately
replaces with `travel_state` as the single source of truth for active
filters (`hotel_preferences.*`) rather than porting the accumulation.

`trip_plan` (review finding F1): built from `state["trip_data"]` -- the
`itinerary_node`/`hotel_node`-generated trip bundle, now its own state key
rather than nested (and lost) inside `travel_state`. `None` whenever no
trip has been built yet, exactly like `to_trip_plan_payload` already
behaves for the `/restore` and `/chat/{id}/plan` endpoints.

`intake`: built from `state["travel_state"]` (the same slot map `ask_slot`
reads to render "Đã cập nhật: ..."), shaped to the legacy plane's
`IntakeStatus` contract so the frontend checklist (intake-checklist-rows.ts)
keeps working unmodified -- it was hardcoded `None` from Phase 5 through the
graph_v2 streaming cutover, which left the intake checklist panel stuck on
"—" for every field even after `ask_slot`'s own reply text confirmed the
value landed.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from src.agents.graph.state import TravelGraphState
from src.domain.travel_state import Presence, TravelState
from src.models.schemas import IntakeStatus, to_hotel_options_payload, to_trip_plan_payload
from src.services.hotel_selection import budget_option_labels
from src.services.trip_planner import _get_destination_names

_ACK_VI = "Đã cập nhật thông tin chuyến đi."
_ACK_EN = "Trip information updated."


def _reply_from_task_results(state: TravelGraphState) -> str | None:
    task_results = state.get("task_results") or []
    for result in reversed(task_results):
        reply = result.get("reply")
        if reply:
            return str(reply)
    return None


def _hotel_options_from_task_results(state: TravelGraphState) -> list[dict[str, Any]]:
    task_results = state.get("task_results") or []
    if not task_results:
        return []
    hotel_search_result = task_results[-1].get("hotel_search_result")
    if not isinstance(hotel_search_result, dict):
        return []
    return [option.model_dump() for option in to_hotel_options_payload(hotel_search_result)]


def _slot_value(travel_state: TravelState, path: str) -> Any:
    slot = travel_state.get(path)
    return slot.value if slot.presence is Presence.SET else None


def _format_duration(start_date: str | None, end_date: str | None) -> str | None:
    """Nights between the two dates, in the legacy plane's "N ngày" shape
    (`trip_intake.py`'s `_duration_from_stay_dates`) — `travel_state` only
    stores `dates.start`/`dates.end`, no standalone duration slot."""
    if not start_date or not end_date:
        return None
    try:
        nights = (date.fromisoformat(end_date) - date.fromisoformat(start_date)).days
    except (TypeError, ValueError):
        return None
    return f"{nights} ngày" if nights > 0 else None


def _intake_status_from_travel_state(state: TravelGraphState) -> IntakeStatus:
    travel_state = TravelState.from_dict(state.get("travel_state"))

    destination = _slot_value(travel_state, "destination")
    people_count = _slot_value(travel_state, "people")
    people = f"{int(people_count)} người" if people_count is not None else None
    start_date = _slot_value(travel_state, "dates.start")
    end_date = _slot_value(travel_state, "dates.end")
    duration = _format_duration(start_date, end_date)

    # Same four gated keys the legacy plane's IntakeStatus.from_state used —
    # intake-checklist-rows.ts's MISSING_KEYS reads exactly these names.
    missing = [
        name
        for name, value in (
            ("destination", destination),
            ("people", people),
            ("start_date", start_date),
            ("duration", duration),
        )
        if value is None
    ]

    return IntakeStatus(
        destination=destination,
        duration=duration,
        start_date=start_date,
        end_date=end_date,
        people=people,
        preferences=list(_slot_value(travel_state, "preferences.themes") or []),
        companions=_slot_value(travel_state, "preferences.companions"),
        pace=_slot_value(travel_state, "preferences.pace"),
        day_rhythm=list(_slot_value(travel_state, "preferences.day_rhythm") or []),
        notes=_slot_value(travel_state, "preferences.notes") or "",
        available_destinations=[option.name for option in _get_destination_names() if option.name],
        budget_options=list(budget_option_labels()),
        missing=missing,
    )


def _reply_from_messages(state: TravelGraphState) -> str | None:
    """The newest AI message, but only if it answers *this* turn.

    `messages` is the one field `load_context` deliberately never resets —
    it is the whole conversation, persisted across turns by the
    checkpointer. Scanning backwards without stopping at the newest human
    turn would surface a stale answer from a previous turn's `qa_node` on
    every turn that runs no worker producing its own reply (every
    `hotel_node`/`itinerary_node` turn today, since both are pass-through
    stubs) — reproduced empirically during review. Stopping at the first
    `human` message bounds the scan to this turn's own exchange.
    """
    messages = state.get("messages") or []
    for message in reversed(messages):
        message_type = getattr(message, "type", None)
        if message_type == "human":
            return None
        if message_type == "ai":
            content = getattr(message, "content", None)
            if content:
                return str(content)
    return None


def respond(state: TravelGraphState) -> dict[str, Any]:
    reply = (
        state.get("next_question")
        or _reply_from_task_results(state)
        or _reply_from_messages(state)
        or (_ACK_EN if state.get("language") == "en" else _ACK_VI)
    )

    response = {
        "session_id": state.get("session_id", ""),
        "reply": reply,
        "suggestions": [],
        "stage": "intake",
        "hotel_options": _hotel_options_from_task_results(state),
        "trip_plan": to_trip_plan_payload(state.get("trip_data")),
        "intake": _intake_status_from_travel_state(state),
        "requires_stay_dates": False,
        "compound_min_price": None,
        "compound_max_price": None,
        "all_preferences": [],
        "active_preferences": [],
    }
    return {"response": response}
