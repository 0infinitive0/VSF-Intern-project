"""`intake_qa` — a read-only escape valve with two entry points.

Mid-intake (Phase 15, `ask_slot`'s "ask" branch): while a required slot is
still missing, `route_ask_slot` used to send every turn straight to
`respond`, so a genuine question ("Đà Nẵng tháng 7 mưa không?") got the
pending-slot question re-asked with a "didn't catch that" prefix instead of
an answer. This entry runs when `routing.is_intake_question` is true (the
extractor concluded the message was a real, parseable question) and
produces an answer that `respond` composes ahead of `next_question`
(`respond._compose`), never in place of it. `ask_slot` itself also consults
`is_intake_question` to suppress that same "didn't catch that" framing on
this branch — see its docstring.

Post-intake (Phase 16, `route_ask_slot`'s other branch): once no slot is
missing, `routing.is_incomplete_edit` sends a turn here too when the
message named an edit target (`update_itinerary`/`update_trip`) but no
value to set it to, so the turn asks for that one value instead of
committing nothing and leaving the supervisor to guess. `clarify=True`
(passed by this node, decided by the caller — see below) switches the
prompt's job from "answer, don't ask" to "ask for the one missing value";
everything else about the node is identical between the two entries.
`routing.route_intake_qa` is what tells a declined/failed answer apart on
each entry, not this node.

`is_intake_question`'s underlying signal (`intent == "general_question"`)
is the extractor's catch-all for "changes nothing" — it also catches
greetings, acknowledgements, and short replies the pending-slot anchor
failed to rescue, not only real questions (see `extract_patch.py`'s
`_pending_slots` docstring for a measured example). The prompt is told to
tell those apart itself and reply with the literal sentinel
`prompts.INTAKE_QA_NO_ANSWER_SENTINEL` when the message isn't actually a
question, which this node maps back to `None` — containment for that
over-inclusion, not a fix to the classifier itself.

Strictly read-only: this node must never write `travel_state`, `patch`, or
`applied_changes` — it runs after `apply_patch`, so a write here would
bypass `validate_patch` entirely. It also never asks a slot question itself;
`ask_slot` stays the sole owner of `next_question`, and the prompt is told
that question in advance so it doesn't duplicate it (see
`prompts.build_intake_qa_prompt`).

`qa_node` (the ReAct agent worker) is not reused here — it shares only the
`messages` channel with the parent graph, so it cannot read `travel_state`
and cannot know which slot is pending (see its own docstring). Its tools
are also wrong for intake: nothing has been searched yet.

One `get_fast_llm` call, no tools, no retry — on any exception the node
returns `{"intake_answer": None}` and the turn degrades to today's
behavior (the pending question alone).
"""

from __future__ import annotations

import logging
from typing import Any

from src.agents.graph.nodes.extract_patch import _known_facts_summary, _last_human_message
from src.agents.graph.prompts import INTAKE_QA_NO_ANSWER_SENTINEL, build_intake_qa_prompt
from src.agents.graph.state import TravelGraphState
from src.domain.travel_state import TravelState
from src.services.llm import get_fast_llm, response_text

logger = logging.getLogger(__name__)


def intake_qa(state: TravelGraphState) -> dict[str, Any]:
    message = _last_human_message(state)
    travel_state = TravelState.from_dict(state.get("travel_state"))
    language = state.get("language") or "vi"

    prompt = build_intake_qa_prompt(
        message=message,
        known_facts=_known_facts_summary(travel_state),
        next_question=state.get("next_question") or "",
        language=language,
        # Read from state, not recomputed: this is exactly `route_ask_slot`'s
        # own `missing_slots` check, so the router and the prompt can never
        # disagree about which entry point this turn came through.
        clarify=not state.get("missing_slots"),
    )

    try:
        llm = get_fast_llm(temperature=0.2, streaming=True)
        response = llm.invoke(prompt)
        answer = response_text(response).strip()
    except Exception:
        logger.warning("intake_qa failed for message %r", message, exc_info=True)
        return {"intake_answer": None}

    if not answer or answer.strip().upper() == INTAKE_QA_NO_ANSWER_SENTINEL:
        return {"intake_answer": None}
    return {"intake_answer": answer}
