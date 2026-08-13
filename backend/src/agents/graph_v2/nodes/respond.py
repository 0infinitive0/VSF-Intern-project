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

`stage`/`trip_plan`/`intake` stay at their Phase-5 placeholder values —
hotel_node/itinerary_node don't produce real trip data until Phases 8-9, so
deriving a richer stage now would be guessing.
"""

from __future__ import annotations

from typing import Any

from src.agents.graph_v2.state import TravelGraphState

_ACK_VI = "Đã cập nhật thông tin chuyến đi."
_ACK_EN = "Trip information updated."


def _reply_from_task_results(state: TravelGraphState) -> str | None:
    task_results = state.get("task_results") or []
    for result in reversed(task_results):
        reply = result.get("reply")
        if reply:
            return str(reply)
    return None


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
        "hotel_options": [],
        "trip_plan": None,
        "intake": None,
        "requires_stay_dates": False,
        "compound_min_price": None,
        "compound_max_price": None,
        "all_preferences": [],
        "active_preferences": [],
    }
    return {"response": response}
