"""`ask_slot` — fills the missing-slot gate with Phase 7's slot registry.

Runs AFTER `apply_patch`, never before: the patch pipeline
(`extract_patch -> validate_patch -> apply_patch`) always commits whatever
this turn's message legitimately changed FIRST, regardless of which slot was
pending. `next_question` then only asks about whatever is STILL missing —
this is the structural fix for the deadlock class (a pending question can no
longer block an unrelated fact from landing) and for the picker-gating bug
(`dates.start`/`dates.end` sort ahead of `budget.target` in
`SLOT_REGISTRY`, so the date question never waits on budget again — the
frontend's own date-widget order comes from `next-intake-field.ts`'s
missing-key mapping, not from a `requires_stay_dates` field; `routes.py`
has no such symbol, only `request.stay_dates` on the input model, a
different thing entirely).

Renders here, not in `domain/slot_registry.py`: rendering needs
`format_guided_question`/`t()` (services layer, e.g. the budget menu already
built for `HotelPreferenceState`), and a domain-layer render callable would
break Phase 3's purity test. `SlotSpec.prompt_key` says WHICH question;
`_render_question` says HOW.
"""

from __future__ import annotations

from typing import Any

from src.agents.graph.routing import is_intake_question
from src.agents.graph.state import TravelGraphState
from src.domain.slot_registry import SlotSpec, next_question, pending_question_slots
from src.domain.travel_state import TravelState
from src.i18n import t
from src.services.trip_intake import DestinationOption
from src.services.trip_planner import _get_destination_names


def _render_destination(language: str) -> str:
    destination_names = _get_destination_names()
    choices = ", ".join(
        option.name if isinstance(option, DestinationOption) else str(option) for option in destination_names
    )
    if choices:
        return t("Bạn muốn đi đâu? Hiện mình có dữ liệu cho: {choices}.", language, choices=choices)
    return t("Bạn muốn đi đâu?", language)


def _render_budget(language: str) -> str:
    # Free text, not a numbered menu: the only interpreter in this plane is
    # extract_patch's LLM, and its prompt understands budget.min/max/target
    # as plain VND amounts, not menu-option indices. A numbered menu here
    # would render options the graph has no parser for -- a bare "2" reply
    # would land as `people=2` (the LLM's only other bare-integer path),
    # never as picking a tier. See HotelPreferenceState's guided menu, which
    # stays the legacy plane's own mechanism and is not reusable here.
    return t(
        'Bạn muốn mức giá khách sạn khoảng nào? Có thể nói một mức cụ thể (vd "4 triệu/đêm"), '
        'một khoảng (vd "2-3 triệu/đêm"), hoặc "không cần lọc theo giá" nếu bạn không có yêu cầu.',
        language,
    )


def _render_question(spec: SlotSpec, pending: tuple[str, ...], language: str) -> str:
    if spec.prompt_key == "destination":
        return _render_destination(language)
    if spec.prompt_key == "people":
        return t("Tuyệt vời. Chuyến đi này có bao nhiêu người tham gia?", language)
    if spec.prompt_key == "dates_start":
        # Both dates in one breath when both are still missing -- the same
        # thing the frontend's date-range widget has always asked
        # ("intakeDatesQuestion"), which until now contradicted a backend
        # asking for the start date alone. Answering only one date is a
        # legitimate reply: the other slot simply stays pending and this
        # narrows to the end-date question on the next turn.
        if "dates.end" in pending:
            return t("Bạn dự định đi và về ngày nào?", language)
        return t("Bạn dự định bắt đầu chuyến đi vào ngày nào?", language)
    if spec.prompt_key == "dates_end":
        return t("Bạn dự định kết thúc chuyến đi vào ngày nào?", language)
    if spec.prompt_key == "budget":
        return _render_budget(language)
    raise AssertionError(f"ask_slot: no renderer registered for prompt_key {spec.prompt_key!r}")


def _context_line(state: TravelGraphState, spec: SlotSpec, language: str) -> str | None:
    """The line prefixed above the re-asked question — never a bare, silent
    repeat of a question the user actually answered. Two cases, in priority
    order:
    1. Something else landed this turn (`applied_changes` non-empty) — the
       user's message was understood, just for a different slot, so this is
       never a "didn't catch that" re-ask. No acknowledgement text is shown;
       the next question follows on its own.
    2. `spec` was ALSO the pending slot at the end of the previous turn
       (`state["missing_slots"]`, which `load_context` deliberately does not
       reset — see its docstring) and nothing landed this turn to explain
       why it is still pending: either an answer attempt failed validation
       (`rejected_changes`) or nothing about the reply was recognized at
       all. Either way this is a genuine RE-ask, so it gets a "didn't catch
       that" framing distinct from the question's own first-time text.
       A slot's first-ever ask (not in the previous turn's `missing_slots`)
       never gets this framing — there is nothing to have "not caught" yet.

    Exception (Phase 15): a turn `is_intake_question` is never a re-ask,
    however `missing_slots` looks — the user asked something, not failed to
    answer, so case 2 is skipped entirely and this returns `None`,
    `intake_qa`'s answer taking that context line's place in `respond`.
    """
    if state.get("applied_changes"):
        return None

    rejected = state.get("rejected_changes") or []
    for rejection in rejected:
        if rejection.get("path") == spec.name:
            reason = rejection.get("reason", "")
            # Clean up the prefix "path: " if it exists
            prefix = f"{spec.name}: "
            if reason.startswith(prefix):
                reason = reason[len(prefix):]
            return t("Dữ liệu chưa hợp lệ: {reason}", language, reason=reason)

    # Phase 15: a genuine question routes to `intake_qa` right after this
    # node runs (`route_ask_slot`/`is_intake_question`) -- it is not a
    # failed attempt to answer the pending slot, so it must never get
    # blamed for "not catching" an answer nobody tried to give.
    if is_intake_question(state):
        return None

    previously_pending = state.get("missing_slots") or []
    if spec.name in previously_pending:
        return t("Mình chưa hiểu rõ ý bạn ở câu trả lời trước.", language)
    return None


def ask_slot(state: TravelGraphState) -> dict[str, Any]:
    travel_state = TravelState.from_dict(state.get("travel_state"))
    spec = next_question(travel_state)
    if spec is None:
        return {"missing_slots": [], "next_question": None}

    language = state.get("language") or "vi"
    # Every slot this one question covers, not just `spec` -- the dates
    # question asks about both ends at once, and `missing_slots` is the
    # record of what was actually put to the user.
    pending = pending_question_slots(travel_state)
    question = _render_question(spec, pending, language)
    context = _context_line(state, spec, language)
    full_text = f"{context}\n\n{question}" if context else question

    return {"missing_slots": list(pending), "next_question": full_text}
