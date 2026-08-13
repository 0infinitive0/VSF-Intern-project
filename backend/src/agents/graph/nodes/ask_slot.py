"""`ask_slot` — fills the missing-slot gate with Phase 7's slot registry.

Runs AFTER `apply_patch`, never before: the patch pipeline
(`extract_patch -> validate_patch -> apply_patch`) always commits whatever
this turn's message legitimately changed FIRST, regardless of which slot was
pending. `next_question` then only asks about whatever is STILL missing —
this is the structural fix for the deadlock class (a pending question can no
longer block an unrelated fact from landing) and for the picker-gating bug
(`dates.start`/`dates.end` sort ahead of `budget.target` in
`SLOT_REGISTRY`, so the date question — and the frontend's date picker,
`api/routes.py`'s `requires_stay_dates` — never waits on budget again).

Renders here, not in `domain/slot_registry.py`: rendering needs
`format_guided_question`/`t()` (services layer, e.g. the budget menu already
built for `HotelPreferenceState`), and a domain-layer render callable would
break Phase 3's purity test. `SlotSpec.prompt_key` says WHICH question;
`_render_question` says HOW.
"""

from __future__ import annotations

from typing import Any

from src.agents.graph.state import TravelGraphState
from src.domain.slot_registry import SlotSpec, next_question
from src.domain.travel_state import TravelState
from src.i18n import t
from src.services.trip_intake import DestinationOption
from src.services.trip_planner import _get_destination_names

# Labels for the "Đã cập nhật: ..." context line — a light acknowledgement,
# not user-facing prose that needs to read perfectly, but still through a
# real per-language table rather than a mechanical path.replace() (the
# earlier version rendered "dates start" for English, which reads as
# broken, not translated).
_CHANGE_LABELS: dict[str, dict[str, str]] = {
    "vi": {
        "destination": "điểm đến",
        "people": "số người",
        "dates.start": "ngày bắt đầu",
        "dates.end": "ngày kết thúc",
        "budget.target": "ngân sách",
        "budget.min": "ngân sách tối thiểu",
        "budget.max": "ngân sách tối đa",
        "budget.trip_total": "tổng ngân sách",
    },
    "en": {
        "destination": "destination",
        "people": "number of people",
        "dates.start": "start date",
        "dates.end": "end date",
        "budget.target": "budget",
        "budget.min": "minimum budget",
        "budget.max": "maximum budget",
        "budget.trip_total": "total trip budget",
    },
}


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


def _render_question(spec: SlotSpec, language: str) -> str:
    if spec.prompt_key == "destination":
        return _render_destination(language)
    if spec.prompt_key == "people":
        return t("Tuyệt vời. Chuyến đi này có bao nhiêu người tham gia?", language)
    if spec.prompt_key == "dates_start":
        return t("Bạn dự định bắt đầu chuyến đi vào ngày nào?", language)
    if spec.prompt_key == "dates_end":
        return t("Bạn dự định kết thúc chuyến đi vào ngày nào?", language)
    if spec.prompt_key == "budget":
        return _render_budget(language)
    raise AssertionError(f"ask_slot: no renderer registered for prompt_key {spec.prompt_key!r}")


def _describe_change(path: str, language: str) -> str:
    labels = _CHANGE_LABELS.get(language, _CHANGE_LABELS["vi"])
    return labels.get(path, path)


def _updated_line(applied_changes: list[dict[str, Any]], language: str) -> str | None:
    """Non-empty exactly when this turn applied a change while a DIFFERENT
    slot is still pending — the "interrupted and returns with context" case
    (a date change lands, budget's question comes back, not repeated
    verbatim). `next_question` is only ever still-UNKNOWN for a slot
    `applied_changes` did NOT just fill, so any non-empty `applied_changes`
    here is always this case, never the slot re-asking itself — EXCEPT an
    `unset` on some other slot, which is also a real, worth-acknowledging
    change (the fact was cleared), so this stays correct for that case too."""
    if not applied_changes:
        return None
    labels: list[str] = []
    seen: set[str] = set()
    for change in applied_changes:
        label = _describe_change(str(change.get("path") or ""), language)
        if label and label not in seen:
            seen.add(label)
            labels.append(label)
    if not labels:
        return None
    joined = ", ".join(labels)
    return t("Đã cập nhật: {joined}.", language, joined=joined)


def _context_line(state: TravelGraphState, spec: SlotSpec, language: str) -> str | None:
    """The line prefixed above the re-asked question — never a bare, silent
    repeat. Two cases, in priority order:
    1. Something else landed this turn (`_updated_line`) — context, not a
       repeat.
    2. `spec` was ALSO the pending slot at the end of the previous turn
       (`state["missing_slots"]`, which `load_context` deliberately does not
       reset — see its docstring) and nothing landed this turn to explain
       why it is still pending: either an answer attempt failed validation
       (`rejected_changes`) or nothing about the reply was recognized at
       all. Either way this is a genuine RE-ask, so it gets a "didn't catch
       that" framing distinct from the question's own first-time text.
       A slot's first-ever ask (not in the previous turn's `missing_slots`)
       never gets this framing — there is nothing to have "not caught" yet.
    """
    updated = _updated_line(state.get("applied_changes") or [], language)
    if updated:
        return updated

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
    question = _render_question(spec, language)
    context = _context_line(state, spec, language)
    full_text = f"{context}\n\n{question}" if context else question

    return {"missing_slots": [spec.name], "next_question": full_text}
