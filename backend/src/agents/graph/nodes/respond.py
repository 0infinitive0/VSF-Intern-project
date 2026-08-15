"""`respond` — builds the frozen `PlannerChatResponse` field shape from
whatever the turn's nodes actually did. Every path through the graph flows
through this node before `END` (Phase 5 functional requirement: the graph
must return a response indistinguishable in *shape* from the legacy
plane), even a `max_iterations` bail-out, an `ask_slot` question, or an
`intake_qa` answer.

Reply text priority:
1. `_compose(intake_answer, next_question)` (Phase 15) — when `intake_qa`
   ran this turn, its answer is joined ahead of `ask_slot`'s pending
   question so the user gets both in one reply, in that order. When
   `intake_answer` is absent (every turn that didn't route through
   `intake_qa`), `_compose` returns `next_question` unchanged, so this step
   is byte-identical to the old bare `next_question` check on every other
   path — including the plain `"ask"` branch, where `intake_answer` is
   always `None`.
2. The last worker's own reply (`booking_node`'s decline, or any future
   worker that sets one) — `task_results[-1]["reply"]`.
3. `qa_node`'s answer — the last AI message in `messages`, the only
   channel that subgraph shares with the parent.
4. A generic acknowledgement, for the pass-through stub workers
   (`hotel_node`/`itinerary_node`) that have nothing to say yet.

`stage` (Phase 17): `_derive_stage` — `missing_slots` outranks everything
(intake is genuinely incomplete), `trip_data` outranks a pending hotel pick
(`session.py::derive_stage`'s legacy precedence), `hotel_options` is the
caller's own already-computed list so `stage` and `hotel_options` can never
disagree. `finalized`/`modified`/`error` are never emitted — no graph
producer exists for any of the three yet.

`hotel_options` (Phase 8): the most recent worker's own `hotel_options` list
when present — `hotel_node` sets it on every turn it runs, including an
empty list on a zero-result turn, so a stale prior turn's cards never leak
forward. `compound_min_price`/`compound_max_price` (Phase 17) come from
`travel_state`'s `budget.min`/`budget.max` slots via `_budget_from_travel_state`,
the same helper the intake-budget echo reuses. `active_preferences` (Phase 17)
reads `hotel_preferences.amenities`, mirroring `hotel_node`'s own
`{id, label}` shape for the same slot. `all_preferences` (Phase 17) is the
TTL-cached approved amenity catalog, fetched only on a `hotel_options` turn
so the terminal node of every other turn stays free of the Supabase
round-trip. `suggestions` (Phase 17) calls `generate_next_chat_suggestions`,
mapped through a `stage` → `last_action` table so a `hotel_options` turn
hits that function's hardcoded-list short-circuit; every other reachable
stage (`intake`, `planned`) skips the call entirely rather than reaching the
function's LLM-calling general branch — `intake` because its suggestions are
never rendered (`chat-panel.tsx`'s `lastStage !== 'intake'` gate), `planned`
because `trip_data` is sticky for the rest of the session (never reset by
`load_context`), so mapping it to the general branch would put an untimed
LLM call on every post-plan turn, not just the turn a trip was built on.

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
from src.services.amenity_catalog import all_approved_amenities
from src.services.hotel_selection import budget_option_labels
from src.services.suggestions import generate_next_chat_suggestions
from src.services.trip_planner import _get_destination_names

_ACK_VI = "Đã cập nhật thông tin chuyến đi."
_ACK_EN = "Trip information updated."


def _compose(intake_answer: str | None, next_question: str | None) -> str | None:
    """Phase 15: joins `intake_qa`'s answer ahead of `ask_slot`'s pending
    question with a blank line when both are present. Returns whichever one
    is present otherwise -- `intake_answer` is `None` on every turn that
    didn't route through `intake_qa`, so this is byte-identical to the old
    bare `next_question` value on every other path, including plain
    `"ask"` turns."""
    if intake_answer and next_question:
        return f"{intake_answer}\n\n{next_question}"
    return intake_answer or next_question


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


def _budget_from_travel_state(travel_state: TravelState) -> tuple[float | None, float | None, bool]:
    """(min_price, max_price, skipped) from the budget.* slots.

    Presence-aware, not `_slot_value`: an explicit "no preference" answer
    (e.g. "bao nhieu cung duoc") sets budget.target to Presence.NOT_APPLICABLE
    (travel_state.py's tri-state model) -- `_slot_value` collapses that to the
    same None a never-asked slot returns, which would make a real skip
    indistinguishable from "not answered yet" and leave the frontend's intake
    widget re-asking forever (intake-budget-slider.tsx). min_price/max_price
    only surface the explicit budget.min/budget.max range the widget's
    dual-thumb slider actually produces; a bare budget.target value or
    budget.trip_total (a different unit -- whole trip, not per night) is
    intentionally left out of this shape.
    """
    target_slot = travel_state.get("budget.target")
    skipped = target_slot.presence is Presence.NOT_APPLICABLE
    min_slot = travel_state.get("budget.min")
    max_slot = travel_state.get("budget.max")
    min_price = min_slot.value if min_slot.presence is Presence.SET else None
    max_price = max_slot.value if max_slot.presence is Presence.SET else None
    return min_price, max_price, skipped


def _derive_stage(state: TravelGraphState, hotel_options: list[dict[str, Any]]) -> str:
    """`missing_slots` is checked first because it is the only signal that
    intake is genuinely incomplete — `ask_slot` is its sole writer and
    `load_context` deliberately does not reset it. `trip_data` outranks
    `hotel_options` next, per `session.py::derive_stage`'s legacy
    precedence: a complete plan outranks a pending hotel pick.
    `hotel_options` is passed in already computed so the two response
    fields can never disagree."""
    if state.get("missing_slots"):
        return "intake"
    if state.get("trip_data"):
        return "planned"
    if hotel_options:
        return "hotel_options"
    return "intake"


# Only stages whose suggestions already have a hardcoded list in
# `generate_next_chat_suggestions` (no LLM call) are mapped here. `intake` is
# deliberately absent -- it is the most frequent stage in the app and its
# suggestions are never rendered (`chat-panel.tsx`'s `lastStage !== 'intake'`
# gate), so generating them would be a pure-waste LLM call on every intake
# turn. `planned` is deliberately absent too, for a stronger reason:
# `trip_data` is never reset by `load_context` (see state.py), so `planned`
# is sticky for the rest of the session once a trip exists -- mapping it to
# `generate_next_chat_suggestions`'s "general" branch would put an untimed
# LLM call on every turn after that point, including qa_node answers and
# scope_guard-blocked turns. No worker currently signals "a trip was just
# (re)built this turn"; add that signal before wiring an LLM call here.
_LAST_ACTION_BY_STAGE: dict[str, str] = {
    "hotel_options": "recommend_hotels",
}


def _suggestions_for_stage(stage: str, reply: str) -> list[dict[str, str]]:
    last_action = _LAST_ACTION_BY_STAGE.get(stage)
    if last_action is None:
        return []
    return [
        {"label": suggestion, "value": suggestion}
        for suggestion in generate_next_chat_suggestions(reply or "", last_action=last_action)
    ]


def _active_preferences_from_travel_state(travel_state: TravelState) -> list[dict[str, str]]:
    """Mirrors `hotel_node.py`'s own `active_preferences` shape (`{id,
    label}`, the raw amenity tag standing in for both) — the same
    `hotel_preferences.amenities` slot, read the same presence-aware way."""
    amenities_slot = travel_state.get("hotel_preferences.amenities")
    if amenities_slot.presence is not Presence.SET:
        return []
    return [{"id": str(tag), "label": str(tag)} for tag in amenities_slot.value]


def _all_preferences_for_stage(stage: str) -> list[dict[str, str]]:
    """Gated on `stage == "hotel_options"` — the only stage whose filter
    panel can render the catalog (`stage-hotels.tsx`) — so every other
    turn stays free of the catalog's Supabase round-trip.
    `all_approved_amenities` is TTL-cached, so even a run of consecutive
    `hotel_options` turns hits Supabase at most once per cache window."""
    if stage != "hotel_options":
        return []
    return [{"id": entry.id, "label": entry.label} for entry in all_approved_amenities()]


def _intake_status_from_travel_state(travel_state: TravelState) -> IntakeStatus:
    destination = _slot_value(travel_state, "destination")
    people_count = _slot_value(travel_state, "people")
    people = f"{int(people_count)} người" if people_count is not None else None
    start_date = _slot_value(travel_state, "dates.start")
    end_date = _slot_value(travel_state, "dates.end")
    duration = _format_duration(start_date, end_date)
    min_price, max_price, budget_skipped = _budget_from_travel_state(travel_state)

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
        min_price=min_price,
        max_price=max_price,
        budget_skipped=budget_skipped,
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
        _compose(state.get("intake_answer"), state.get("next_question"))
        or _reply_from_task_results(state)
        or _reply_from_messages(state)
        or (_ACK_EN if state.get("language") == "en" else _ACK_VI)
    )

    travel_state = TravelState.from_dict(state.get("travel_state"))
    hotel_options = _hotel_options_from_task_results(state)
    stage = _derive_stage(state, hotel_options)
    min_price, max_price, _skipped = _budget_from_travel_state(travel_state)

    response = {
        "session_id": state.get("session_id", ""),
        "reply": reply,
        "suggestions": _suggestions_for_stage(stage, reply),
        "stage": stage,
        "hotel_options": hotel_options,
        "trip_plan": to_trip_plan_payload(state.get("trip_data")),
        "intake": _intake_status_from_travel_state(travel_state),
        "requires_stay_dates": False,
        "compound_min_price": min_price,
        "compound_max_price": max_price,
        "all_preferences": _all_preferences_for_stage(stage),
        "active_preferences": _active_preferences_from_travel_state(travel_state),
    }
    return {"response": response}
