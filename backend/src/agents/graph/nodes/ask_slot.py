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

That HOW is then reworded by one `get_fast_llm` call
(`_render_question_llm`) so the intake stops reading as a fixed form recited
back. The split is the point: `slot_registry` still decides WHICH slot is
asked, deterministically and testably, and the model only ever sees the one
sentence that decision produced. `_render_question` remains the value sent
whenever the rewording is unavailable or fails `_slot_question_is_usable`,
so a provider outage costs wording and nothing else.

The frontend keeps its own hardcoded copy of these questions
(`frontend/src/i18n/locales/*.json`), rendered by `chat-panel.tsx` when the
widget rail advances a step locally with no chat turn. It is deliberately
left alone: it is a different renderer on a different surface, and the two
are deduped by FIELD (`serverAskedField`, derived from `IntakeStatus.missing`
in `next-intake-field.ts`), never by matching reply text — so nothing
downstream can notice the wordings differ. `_render_question`'s output stays
byte-identical to that copy, which is what `test_ask_slot.py` still pins.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from src.agents.graph.nodes.extract_patch import (
    UNKNOWN_DESTINATION_REASON,
    UNSUPPORTED_LABEL_REASON,
    _destination_choices,
    _known_facts_summary,
)
from src.agents.graph.prompts import build_slot_question_prompt
from src.agents.graph.routing import is_intake_question
from src.agents.graph.state import TravelGraphState
from src.domain.slot_registry import SlotSpec, next_question, pending_question_slots
from src.domain.travel_state import END_NOT_AFTER_START_REASON, Presence, Slot, TravelState
from src.i18n import t
from src.services.llm import get_fast_llm, response_text
from src.services.trip_intake import _PREFERENCE_LABELS
from src.services.trip_planner import _get_destination_names

logger = logging.getLogger(__name__)


def _destination_catalog(language: str) -> str:
    """The comma-joined destination list both renderings need — the hardcoded
    question interpolates it, and the LLM rendering has to verify the model
    reproduced every entry. `_get_destination_names` is `lru_cache`d, so the
    second reader costs no extra Supabase round-trip.

    Shares `extract_patch._destination_choices` rather than re-joining:
    the extractor grounds an answer against exactly this list
    (`_match_known_destination`), so a question offering a differently
    rendered set could offer something the extractor then refuses.
    """
    del language  # names are proper nouns; the surrounding sentence is what t() translates
    return _destination_choices(_get_destination_names())


def _render_destination(language: str) -> str:
    choices = _destination_catalog(language)
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


def _render_preferences(language: str) -> str:
    # Names the closed label set the extractor will actually accept
    # (`_PREFERENCE_LABELS`, the same vocabulary `build_extract_patch_prompt`
    # grounds against) AND says out loud that having no preference is a real
    # answer -- without that sentence the user has no way to know silence is
    # allowed, and this is the one required slot whose honest answer is
    # often nothing.
    return t(
        'Cuối cùng, bạn thích kiểu trải nghiệm nào? Có thể chọn vài mục ({choices}), '
        'hoặc nói "không có gì đặc biệt" nếu bạn không có yêu cầu riêng.',
        language,
        choices=", ".join(_PREFERENCE_LABELS),
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
    if spec.prompt_key == "preferences":
        return _render_preferences(language)
    raise AssertionError(f"ask_slot: no renderer registered for prompt_key {spec.prompt_key!r}")


# What each question is ABOUT, in one clause, for the model that rewords it.
# Deliberately not the question text itself: `_render_question`'s output is
# passed separately as the anchor, and giving the model the subject and the
# sentence as two independent statements is what lets a bad paraphrase be
# noticed instead of silently inheriting the sentence's own ambiguity.
_SLOT_BRIEFS = {
    "destination": "which destination the user wants to travel to",
    "people": "how many people are going on the trip",
    "dates_end": "which date the trip ends",
    "budget": "what nightly hotel price the user wants",
    "preferences": "what kind of experiences the user enjoys on a trip",
}
_MAX_QUESTION_LENGTH = 300
# Slots whose question enumerates a closed set the extractor grounds against.
# A rewording that drops an entry hides an option the user could have picked;
# one that invents an entry offers an answer the extractor will refuse. Both
# are checked verbatim, per slot, in `_slot_question_is_usable`.
_CATALOG_SLOTS = frozenset({"destination", "preferences"})
# A numbered or lettered option ("1.", "2)") -- see `_BUDGET_EXTRA_RULE`.
_MENU_OPTION = re.compile(r"\d+[.)]\s")


def _slot_brief(spec: SlotSpec, pending: tuple[str, ...]) -> str:
    if spec.prompt_key == "dates_start":
        # Mirrors `_render_question`'s own split: one question covers both
        # ends while both are missing, and narrows once one has landed.
        return (
            "which dates the trip starts and ends"
            if "dates.end" in pending
            else "which date the trip starts"
        )
    return _SLOT_BRIEFS[spec.prompt_key]


def _slot_question_is_usable(question: str, spec: SlotSpec, choices: str) -> bool:
    """Whether a reworded question can be sent in the hardcoded one's place.

    Every check here defends something a caller downstream actually relies
    on, not merely style:

    - A line break would be read as `ask_slot`'s own context-line separator
      (`full_text` below joins with a blank line), so a multi-line question
      would look like a rejection explanation that isn't there.
    - A `_CATALOG_SLOTS` question must reproduce every catalog entry
      verbatim: the extractor grounds the answer against exactly that list
      (`_match_known_destination` for destinations, `_PREFERENCE_LABELS` for
      preferences), so an entry the question drops becomes an option the
      user cannot discover, and one it invents becomes an answer the
      extractor will refuse.
    - `budget` must not present a menu: nothing parses menu indices, and a
      bare "2" reply lands as `people=2` (see `_render_budget`).

    Anything rejected here falls back to the hardcoded rendering, which is
    always correct — a failed rewording costs wording, never the turn.
    """
    if not question or len(question) > _MAX_QUESTION_LENGTH:
        return False
    if "\n" in question or "?" not in question:
        return False
    if spec.prompt_key == "budget" and _MENU_OPTION.search(question):
        return False
    if spec.prompt_key in _CATALOG_SLOTS and choices:
        return all(name.strip() in question for name in choices.split(","))
    return True


def _slot_choices(spec: SlotSpec, language: str) -> str:
    """The closed set this slot's question must offer, comma-joined, or `""`
    for the slots that offer none."""
    if spec.prompt_key == "destination":
        return _destination_catalog(language)
    if spec.prompt_key == "preferences":
        return ", ".join(_PREFERENCE_LABELS)
    return ""


def _render_question_llm(
    spec: SlotSpec, pending: tuple[str, ...], travel_state: TravelState, language: str, fallback: str
) -> str | None:
    """`fallback` reworded, or `None` to keep `fallback` itself.

    This never chooses WHICH slot is asked — `slot_registry.next_question`
    already did, deterministically, and this is handed the outcome. One
    `get_fast_llm` call, no tools, no retry: on any exception or any
    rejected output the caller sends the hardcoded question, which is what
    every turn sent before this existed.
    """
    choices = _slot_choices(spec, language)
    prompt = build_slot_question_prompt(
        slot_brief=_slot_brief(spec, pending),
        known_facts=_known_facts_summary(travel_state),
        fallback=fallback,
        language=language,
        prompt_key=spec.prompt_key,
        choices=choices,
    )
    try:
        llm = get_fast_llm(temperature=0.3)
        question = response_text(llm.invoke(prompt)).strip()
    except Exception:
        logger.warning("ask_slot question rewording failed for slot %r", spec.name, exc_info=True)
        return None

    if not _slot_question_is_usable(question, spec, choices):
        logger.info("ask_slot discarded a reworded question for slot %r: %r", spec.name, question)
        return None
    return question


# Path -> (label, echo the new value). Only the slots a user names in their
# own words get a label at all; anything else revised in the same turn is
# left out rather than described with a name the user never used.
#
# `echo` is off for budget on purpose: all four budget paths share one
# label, so a range revision would have to pick one of them to echo and
# would read as a single price the user never said.
_SLOT_LABELS: dict[str, tuple[str, bool]] = {
    "destination": ("điểm đến", True),
    "people": ("số người", True),
    "dates.start": ("ngày bắt đầu", True),
    "dates.end": ("ngày kết thúc", True),
    "budget.target": ("ngân sách", False),
    "budget.min": ("ngân sách", False),
    "budget.max": ("ngân sách", False),
    "budget.trip_total": ("ngân sách", False),
    "preferences.themes": ("sở thích", True),
}


def _revised_value_text(slot: Slot) -> str:
    """The new value as the user would read it back, or `""` when there is
    nothing quotable -- an explicit opt-out (NOT_APPLICABLE) has no value to
    echo, and the label alone already says what changed."""
    if slot.presence is not Presence.SET:
        return ""
    if isinstance(slot.value, list):
        return ", ".join(str(item) for item in slot.value)
    return str(slot.value)


def _revision_ack(state: TravelGraphState, travel_state: TravelState, language: str) -> str | None:
    """"Đã cập nhật điểm đến thành Nha Trang." -- the line above the next question
    when this turn CHANGED something already answered.

    Without it, correcting a value mid-intake ("đi Hà Nội" -> "đi Nha Trang")
    gets only the next question back, and nothing in the reply tells the
    user the correction landed. `revised_slots` (`apply_patch`) is already
    scoped to real overwrites, so a first-time answer never reaches here.

    The value is read from `travel_state` -- the committed state, not the
    patch -- so what gets echoed is what was actually stored, never what was
    merely proposed.
    """
    parts: list[str] = []
    seen: set[str] = set()
    for path in state.get("revised_slots") or []:
        entry = _SLOT_LABELS.get(str(path))
        if entry is None:
            continue
        label, echo = entry
        if label in seen:
            continue
        seen.add(label)
        label_text = t(label, language)
        value = _revised_value_text(travel_state.get(str(path))) if echo else ""
        parts.append(
            t("{label} thành {value}", language, label=label_text, value=value) if value else label_text
        )
    if not parts:
        return None
    return t("Đã cập nhật {changes}.", language, changes=", ".join(parts))


def _rejection_value_text(value: Any) -> str:
    """The user's own wording for a rejected value. A closed-list path holds
    a list, so it is joined rather than printed as a Python repr."""
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value or "").strip()


def _grounding_rejection_line(state: TravelGraphState, language: str) -> str | None:
    """"Rất tiếc, mình chưa hỗ trợ Rạch Giá." — for a value the user named
    clearly and this system simply has no data for.

    Checked on EVERY path, not only the slot being asked: naming an
    unsupported value is worth saying out loud whichever question happens to
    be pending, and this information exists nowhere else once `extract_patch`
    drops the change.

    Runs ahead of the per-slot rejection loop below on purpose. Both live in
    `rejected_changes` now, and the generic rendering there
    ("Dữ liệu chưa hợp lệ: ...") is exactly the wrong thing to say about a
    real place name — it reads as "you typed it wrong" and sends the user
    off to re-type something that was never mistyped.
    """
    for rejection in state.get("rejected_changes") or []:
        reason = rejection.get("reason")
        value = _rejection_value_text(rejection.get("value"))
        if not value:
            continue
        if reason == UNKNOWN_DESTINATION_REASON:
            return t("Rất tiếc, mình chưa hỗ trợ {value}.", language, value=value)
        if reason == UNSUPPORTED_LABEL_REASON:
            return t("Mình chưa hỗ trợ lựa chọn: {value}.", language, value=value)
    return None


def _context_line(
    state: TravelGraphState, spec: SlotSpec, language: str, travel_state: TravelState
) -> str | None:
    """The line prefixed above the re-asked question — never a bare, silent
    repeat. `spec` was ALSO the pending slot at the end of the previous turn
    (`state["missing_slots"]`, which `load_context` deliberately does not
    reset — see its docstring) and nothing landed this turn to explain why it
    is still pending: either an answer attempt failed validation
    (`rejected_changes`) or nothing about the reply was recognized at all.
    Either way this is a genuine RE-ask, so it gets a "didn't catch that"
    framing distinct from the question's own first-time text. A slot's
    first-ever ask (not in the previous turn's `missing_slots`) never gets
    this framing — there is nothing to have "not caught" yet.

    Exception (Phase 15): a turn `is_intake_question` is never a re-ask,
    however `missing_slots` looks — the user asked something, not failed to
    answer, so this returns `None`, `intake_qa`'s answer taking that context
    line's place in `respond`.

    Also never fires when this turn actually applied a change to some OTHER
    slot (`applied_changes` non-empty) -- `next_question` is only ever
    still-UNKNOWN for a slot `applied_changes` did NOT just fill, so a
    non-empty `applied_changes` here always means something legitimate
    landed elsewhere, never that `spec`'s own answer failed. Without this
    check a valid, unrelated change (e.g. a date update while budget is
    still pending) would wrongly read as "didn't catch that".
    """
    grounding = _grounding_rejection_line(state, language)
    if grounding is not None:
        return grounding

    rejected = state.get("rejected_changes") or []
    for rejection in rejected:
        if rejection.get("path") == spec.name:
            reason = rejection.get("reason", "")
            # Clean up the prefix "path: " if it exists
            prefix = f"{spec.name}: "
            if reason.startswith(prefix):
                reason = reason[len(prefix):]
            if reason == END_NOT_AFTER_START_REASON:
                # A same-day trip is an ordinary request, not a malformed value: the
                # planner books hotel nights, so it needs at least one. Echoing the
                # validator's own English sentence into a Vietnamese conversation
                # ("Dữ liệu chưa hợp lệ: end date must be after the trip's start
                # date") reads as an internal error and says nothing actionable.
                return t(
                    "Chuyến đi cần ít nhất 1 đêm nghỉ, nên ngày kết thúc phải sau ngày bắt đầu.",
                    language,
                )
            return t("Dữ liệu chưa hợp lệ: {reason}", language, reason=reason)

    # A correction the user just made outranks everything below: those
    # branches all explain why NOTHING landed, and something did.
    revision = _revision_ack(state, travel_state, language)
    if revision is not None:
        return revision

    # Phase 15: a genuine question routes to `intake_qa` right after this
    # node runs (`route_ask_slot`/`is_intake_question`) -- it is not a
    # failed attempt to answer the pending slot, so it must never get
    # blamed for "not catching" an answer nobody tried to give.
    if is_intake_question(state):
        return None

    if state.get("applied_changes"):
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
    fallback = _render_question(spec, pending, language)
    # The hardcoded rendering is built first either way: it is the anchor the
    # rewording is measured against, and the value sent when that rewording
    # is unavailable or unusable.
    question = _render_question_llm(spec, pending, travel_state, language, fallback) or fallback
    context = _context_line(state, spec, language, travel_state)
    full_text = f"{context}\n\n{question}" if context else question

    return {"missing_slots": list(pending), "next_question": full_text}
