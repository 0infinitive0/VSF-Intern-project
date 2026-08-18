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
   always `None`. `_question_for_this_reply` sits in front of it and drops
   the question when the previous reply already asked that same slot and an
   answer is going out in its place, so two consecutive replies never end
   with the identical question.

Every reply is appended back to `messages` as a tagged `AIMessage` — the
transcript held only the user's half before this (`routes.py` adds the
`HumanMessage`, `qa_node`'s subgraph its own agent messages, nothing the
assistant actually sent). The tag carries `asked_slot`, which is how the
next turn knows what the last reply asked without matching reply text.
2. The last worker's own reply — `task_results[-1]["reply"]`. Every worker
   the supervisor delegates to owes one, declared as `emits_reply` on its
   `NodeContract` and checked at the node boundary.
3. `qa_node`'s answer — the last AI message in `messages`, the only
   channel that subgraph shares with the parent.
4. A generic acknowledgement — the safety net, and *only* the safety net.
   `respond` assembles a reply, it does not write one: reaching step 4
   means a node finished a turn silently, which is a bug, so this step
   logs at ERROR rather than quietly papering over it. It used to be the
   ordinary ending of every successful itinerary build, back when
   `hotel_node`/`itinerary_node` were pass-through stubs with nothing to
   say; both have real bodies now and the `emits_reply` contract keeps
   them honest.

The payload-shaping helpers below (`derive_stage`, `intake_status_from_travel_state`,
`hotel_options_from_task_results`, `budget_from_travel_state`) live in
`agents/graph/response_payload.py`, not here: `GET /chat/{id}/restore` has to
build the same fields for a past conversation, and the only alternatives were
an API module importing private names out of a graph node, or a second
implementation that drifts. It drifted.

`stage` (Phase 17): `derive_stage` — `missing_slots` outranks everything
(intake is genuinely incomplete), `trip_data` outranks a pending hotel pick
(`session.py::derive_stage`'s legacy precedence), `hotel_options` is the
caller's own already-computed list so `stage` and `hotel_options` can never
disagree. A reply carrying `sanitize_system_error`'s `SYSTEM ERROR:` prefix
outranks all of it and makes the turn `error`, which is what gives the
frontend its error styling. `finalized`/`modified` are gone from `ChatStage`
entirely: their only producer was the deleted `process_chat_turn` cascade.

`hotel_options` (Phase 8): the most recent worker's own `hotel_options` list
when present — `hotel_node` sets it on every turn it runs, including an
empty list on a zero-result turn, so a stale prior turn's cards never leak
forward. `compound_min_price`/`compound_max_price` (Phase 17) come from
`travel_state`'s `budget.min`/`budget.max` slots via `budget_from_travel_state`,
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
reads to render its next question), shaped to the legacy plane's
`IntakeStatus` contract so the frontend checklist (intake-checklist-rows.ts)
keeps working unmodified -- it was hardcoded `None` from Phase 5 through the
graph_v2 streaming cutover, which left the intake checklist panel stuck on
"—" for every field even after `ask_slot`'s own reply text confirmed the
value landed.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from langchain_core.messages import AIMessage

from src.agents.graph.response_payload import (
    budget_from_travel_state,
    derive_stage,
    hotel_options_from_task_results,
    intake_status_from_travel_state,
    suggested_places_from_task_results,
)
from src.agents.graph.state import TravelGraphState
from src.domain.travel_state import Presence, TravelState
from src.models.schemas import AmenityCatalogPayload, hotel_amenities_from_hotel_options, to_trip_plan_payload
from src.services.amenity_catalog import AmenityCatalogEntry, all_approved_amenities, resolve_hotel_amenity_ids
from src.services.suggestions import generate_next_chat_suggestions

logger = logging.getLogger(__name__)

_ACK_VI = "Đã cập nhật thông tin chuyến đi."
_ACK_EN = "Trip information updated."

# Marks the AI messages this node appends, so the reply it sent can be told
# apart from `qa_node`'s own subgraph messages, which share the same
# channel. `asked_slot` records which slot's question that reply actually
# carried — `None` when it carried none.
_EMITTED_BY_RESPOND = "respond"


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


def _previously_asked_slot(state: TravelGraphState) -> str | None:
    """The slot the PREVIOUS reply asked about, read back off the transcript.

    The newest `_EMITTED_BY_RESPOND` message is that reply — the tag is what
    makes this exact instead of a text match on wording that is free to
    change. Untagged AI messages (`qa_node`'s) are skipped: they never carry
    a slot question.
    """
    for message in reversed(state.get("messages") or []):
        if getattr(message, "type", None) != "ai":
            continue
        metadata = getattr(message, "additional_kwargs", None) or {}
        if metadata.get("emitted_by") != _EMITTED_BY_RESPOND:
            continue
        slot = metadata.get("asked_slot")
        return str(slot) if slot else None
    return None


def _question_for_this_reply(state: TravelGraphState) -> tuple[str | None, str | None]:
    """`(question text to send, the slot it asks about)`.

    The question is dropped when the previous reply already asked this same
    slot AND `intake_qa` produced an answer to send in its place — the
    "answer, then re-ask the identical question" pattern a user reads as the
    bot not listening. Dropping requires that replacement: a reply with
    neither an answer nor a question would be empty, and the intake would
    stall with nothing on screen to move it forward.

    Never drops on the plain `"ask"` branch, whatever the transcript says.
    That branch is where an answer failed validation or wasn't understood
    (`ask_slot._context_line`), and re-asking is the only thing that can
    unblock the turn.

    Returning both values from one place is what keeps the reply and the
    `asked_slot` tag recorded next to it from disagreeing — the tag is what
    the NEXT turn reads back.
    """
    question = state.get("next_question")
    if not question:
        return None, None
    pending = state.get("missing_slots") or []
    slot = str(pending[0]) if pending else None
    if state.get("intake_answer") and slot and slot == _previously_asked_slot(state):
        return None, None
    return question, slot


def _reply_from_task_results(state: TravelGraphState) -> str | None:
    task_results = state.get("task_results") or []
    for result in reversed(task_results):
        reply = result.get("reply")
        if reply:
            return str(reply)
    return None


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


def _catalog_preferences(ids: list[str], catalog: tuple[AmenityCatalogEntry, ...]) -> list[dict[str, str]]:
    by_id = {entry.id: entry for entry in catalog if entry.scope in {"hotel", "both"}}
    return [
        {"id": amenity_id, "label": by_id[amenity_id].label}
        for amenity_id in dict.fromkeys(ids)
        if amenity_id in by_id
    ]


def _active_preferences_from_travel_state(
    travel_state: TravelState, catalog: tuple[AmenityCatalogEntry, ...]
) -> list[dict[str, str]]:
    """Bind user hotel-amenity requests to approved canonical catalog IDs."""
    amenities_slot = travel_state.get("hotel_preferences.amenities")
    if amenities_slot.presence is not Presence.SET:
        return []
    return _catalog_preferences(list(resolve_hotel_amenity_ids(amenities_slot.value).ids), catalog)


def _available_preferences_from_hotel_options(
    hotel_options: list[dict[str, Any]], catalog: tuple[AmenityCatalogEntry, ...]
) -> list[dict[str, str]]:
    """Catalog-bound filters limited to the amenities shown on current cards."""
    amenity_ids = [
        amenity_id
        for hotel in hotel_options
        for amenity_id in hotel.get("display_amenities") or []
        if isinstance(amenity_id, str)
    ]
    return _catalog_preferences(amenity_ids, catalog)


def _payload_preferences(ids: list[str], catalog: list[AmenityCatalogPayload]) -> list[dict[str, str]]:
    by_id = {entry.id: entry for entry in catalog}
    return [
        {"id": amenity_id, "label": by_id[amenity_id].label_vi}
        for amenity_id in dict.fromkeys(ids)
        if amenity_id in by_id
    ]


def _active_hotel_preference_ids(state: TravelGraphState) -> list[str]:
    """Read canonical IDs emitted by hotel_node without re-querying the catalog."""
    for result in reversed(state.get("task_results") or []):
        search_result = result.get("hotel_search_result")
        if not isinstance(search_result, dict):
            continue
        preferences = search_result.get("active_preferences") or []
        return [
            preference["id"]
            for preference in preferences
            if isinstance(preference, dict) and isinstance(preference.get("id"), str)
        ]
    return []


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

    A reply this node itself sent is skipped outright, ahead of that guard:
    it is something already said, never a fresh answer for this turn, and a
    resume turn (`Command(resume=...)`, which adds no `HumanMessage` — see
    `routes.py::_run_turn_via_graph`) would otherwise hit the previous
    turn's reply before any human message could stop the scan, and echo it.
    """
    messages = state.get("messages") or []
    for message in reversed(messages):
        message_type = getattr(message, "type", None)
        if message_type == "human":
            return None
        if message_type == "ai":
            metadata = getattr(message, "additional_kwargs", None) or {}
            if metadata.get("emitted_by") == _EMITTED_BY_RESPOND:
                continue
            content = getattr(message, "content", None)
            if content:
                return str(content)
    return None


def select_reply(state: TravelGraphState) -> str | None:
    """This turn's reply, in priority order, or `None` if no node spoke."""
    question, _slot = _question_for_this_reply(state)
    return (
        _compose(state.get("intake_answer"), question)
        or _reply_from_task_results(state)
        or _reply_from_messages(state)
    )


def respond(state: TravelGraphState) -> dict[str, Any]:
    reply = select_reply(state)
    if reply is None:
        # The generic ack is the last safety net, not a route. Reaching it
        # means some node finished a turn without saying anything — the
        # `emits_reply` contract catches that at the node boundary in CI, so
        # a hit here is either a worker with no contract or production
        # running `contract_enforcement_mode=log`. Either way it is a bug
        # with a user on the other end of it, so it is logged loudly enough
        # to find rather than absorbed silently.
        logger.error(
            "respond fell through to the generic ack — no node produced a reply. "
            "routing_source=%s next_worker=%s task_results=%s has_trip_data=%s",
            state.get("routing_source"),
            state.get("next_worker"),
            state.get("task_results"),
            bool(state.get("trip_data")),
        )
        reply = _ACK_EN if state.get("language") == "en" else _ACK_VI

    travel_state = TravelState.from_dict(state.get("travel_state"))
    hotel_options = hotel_options_from_task_results(state)
    stage = derive_stage(state, hotel_options, reply)
    min_price, max_price, _skipped = budget_from_travel_state(travel_state)
    amenity_slot = travel_state.get("hotel_preferences.amenities")
    hotel_amenities = hotel_amenities_from_hotel_options(hotel_options) if stage == "hotel_options" else []
    if stage == "hotel_options":
        active_ids = _active_hotel_preference_ids(state)
        if not active_ids and amenity_slot.presence is Presence.SET:
            # A re-search/change-hotel turn can retain its cards while the
            # latest worker result omits active_preferences.  The travel state
            # is the session-wide source of the user's amenity request.
            session_catalog = all_approved_amenities()
            active_ids = [
                preference["id"]
                for preference in _active_preferences_from_travel_state(travel_state, session_catalog)
            ]
        # The filter choices are the user's accumulated amenity requests for
        # this session, not every facility on the cards.  Mapping through the
        # shared card catalog removes requests that no displayed hotel offers.
        all_preferences = _payload_preferences(active_ids, hotel_amenities)
        active_preferences = _payload_preferences(active_ids, hotel_amenities)
    else:
        catalog = all_approved_amenities() if amenity_slot.presence is Presence.SET else ()
        active_preferences = _active_preferences_from_travel_state(travel_state, catalog)
        all_preferences = []

    response = {
        "session_id": state.get("session_id", ""),
        "reply": reply,
        "suggestions": _suggestions_for_stage(stage, reply),
        "stage": stage,
        "hotel_options": hotel_options,
        "hotel_amenities": hotel_amenities,
        "trip_plan": to_trip_plan_payload(state.get("trip_data")),
        "intake": intake_status_from_travel_state(travel_state),
        "requires_stay_dates": False,
        "compound_min_price": min_price,
        "compound_max_price": max_price,
        "all_preferences": all_preferences,
        "active_preferences": active_preferences,
        "suggested_places": suggested_places_from_task_results(state),
    }
    # The reply goes back into `messages` so the transcript holds both sides
    # of the conversation, not just the user's half — until now nothing wrote
    # the assistant's turn back (`routes.py` only ever adds the `HumanMessage`,
    # and `qa_node`'s subgraph its own agent messages). `asked_slot` is what
    # the next turn reads to avoid asking the same question twice in a row.
    _question, asked_slot = _question_for_this_reply(state)
    sent = AIMessage(
        content=reply,
        additional_kwargs={
            "emitted_by": _EMITTED_BY_RESPOND,
            "asked_slot": asked_slot,
            # When this reply was sent. The persistence writer re-sends the
            # whole transcript on every turn (session_store.py's
            # `_graph_message_records`), so a message that doesn't carry its
            # own timestamp would be re-stamped "now" forever and lose the
            # chronology the history rail and `load()` order by.
            "at": datetime.now(UTC).isoformat(),
        },
    )
    return {"response": response, "messages": [sent]}
