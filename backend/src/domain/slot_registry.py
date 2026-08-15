"""Declarative slot ordering over Phase 3's `TravelState` tri-state model.

Replaces the five-branch `if` ladder in the legacy `_run_intake` — each
branch hard-coding exactly one question and exactly one order, budget asked
BEFORE dates (the literal mechanism behind "ngân sách chưa nhập chưa cho
edit") — with one table and one expression: `next_question` is the first
spec whose slot is still `UNKNOWN`, by `order`. Every slot inherits
revisable/skippable/interruptible behavior for free, because nothing here
ever special-cases "the pending question": the patch pipeline
(`extract_patch -> validate_patch -> apply_patch`) always runs first, and
`ask_slot` only asks about whatever is STILL missing afterward.

Pure module: no `services`, no I/O, no LLM client. See `ARCHITECTURE.md`
§ Layer Architecture & Import Rules. `SlotSpec.prompt_key` is deliberately a
`str`, not a render callable — rendering needs `format_guided_question`/
`t()` (services layer), which `ask_slot` (the graph node, not this module)
is allowed to import.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.domain.travel_state import Presence, TravelState


@dataclass(frozen=True)
class SlotSpec:
    name: str  # canonical path from ALLOWED_PATHS
    required: bool
    order: int
    prompt_key: str  # WHICH question to ask — ask_slot decides how to render it
    skippable: bool = False
    # Other ALLOWED_PATHS that also count as "this slot answered" -- budget
    # is one guided question but three independent paths (a ceiling only, a
    # floor only, a range, or one preferred price are all legitimate
    # answers); without this, stating only budget.max would leave
    # budget.target UNKNOWN forever and re-ask the same question every turn.
    alt_names: tuple[str, ...] = ()
    # Other required slots this spec's question asks about at the same time.
    # Distinct from `alt_names`: an alt name is a DIFFERENT way to answer
    # this one slot, while these are separate slots that still each need
    # their own answer -- the question just gathers them in one breath, and
    # the user is free to answer one, the other, or both. Only `dates.start`
    # uses it today ("đi và về ngày nào?"), matching what the frontend's
    # date-range widget has always asked in a single step.
    asked_with: tuple[str, ...] = ()


# Default ordering: destination -> people -> dates -> budget. Budget sorts
# last and is the only skippable slot — dates.start/dates.end both sort
# ahead of it, so the date picker can never again be gated behind budget.
SLOT_REGISTRY: tuple[SlotSpec, ...] = (
    SlotSpec(name="destination", required=True, order=1, prompt_key="destination"),
    SlotSpec(name="people", required=True, order=2, prompt_key="people"),
    SlotSpec(name="dates.start", required=True, order=3, prompt_key="dates_start", asked_with=("dates.end",)),
    SlotSpec(name="dates.end", required=True, order=4, prompt_key="dates_end"),
    SlotSpec(
        name="budget.target",
        required=True,
        order=5,
        prompt_key="budget",
        skippable=True,
        alt_names=("budget.max", "budget.min"),
    ),
)


def _slot_satisfies(spec: SlotSpec, state: TravelState, path: str) -> bool:
    presence = state.get(path).presence
    if presence is Presence.SET:
        return True
    if presence is Presence.NOT_APPLICABLE:
        # Only a slot the user can genuinely opt out of treats "no
        # preference" as answered. Every other slot's validator accepts
        # `value: null` too (it is a uniform mechanism in apply_patch, not
        # something scoped per-path) -- e.g. a stray/misextracted
        # `{"path": "destination", "operation": "set", "value": null}` must
        # NOT permanently mark destination "answered but empty" and let
        # intake proceed with no destination at all.
        return spec.skippable
    return False


def _is_answered(spec: SlotSpec, state: TravelState) -> bool:
    if _slot_satisfies(spec, state, spec.name):
        return True
    return any(_slot_satisfies(spec, state, alt) for alt in spec.alt_names)


def next_question(state: TravelState) -> SlotSpec | None:
    """First required spec that is not yet answered, by `order`. SET always
    counts as answered; NOT_APPLICABLE only counts for a `skippable` spec —
    that's the whole point of the tri-state model, and how a skippable slot
    actually gets skipped (setting it NOT_APPLICABLE, not just matching one
    of a fixed list of phrases) without opening the same escape hatch on a
    slot nothing can legitimately skip."""
    for spec in sorted(SLOT_REGISTRY, key=lambda s: s.order):
        if spec.required and not _is_answered(spec, state):
            return spec
    return None


def _spec_by_name(name: str) -> SlotSpec | None:
    return next((spec for spec in SLOT_REGISTRY if spec.name == name), None)


def pending_question_slots(state: TravelState) -> tuple[str, ...]:
    """Every slot the NEXT question covers, in the order it presents them —
    `next_question`'s own slot first, then any `asked_with` companion still
    unanswered. Empty when nothing is left to ask.

    One question can legitimately gather more than one slot ("bạn đi và về
    ngày nào?"), and two consumers need to agree on exactly which: `ask_slot`
    picks the wording from it, and `extract_patch` anchors its prompt on it
    so a reply naming one date, the other, or both lands on the right paths.
    Deriving both from this one function is what keeps the question the user
    reads and the paths the extractor will accept from drifting apart.

    A companion already answered drops out, so once `dates.start` is known
    the question narrows back to `dates.end` alone rather than re-asking for
    a date the user already gave."""
    spec = next_question(state)
    if spec is None:
        return ()
    companions = tuple(
        name
        for name in spec.asked_with
        if (companion := _spec_by_name(name)) is not None and not _is_answered(companion, state)
    )
    return (spec.name, *companions)
