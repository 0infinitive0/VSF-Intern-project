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


# Default ordering: destination -> people -> dates -> budget. Budget sorts
# last and is the only skippable slot — dates.start/dates.end both sort
# ahead of it, so the date picker can never again be gated behind budget.
SLOT_REGISTRY: tuple[SlotSpec, ...] = (
    SlotSpec(name="destination", required=True, order=1, prompt_key="destination"),
    SlotSpec(name="people", required=True, order=2, prompt_key="people"),
    SlotSpec(name="dates.start", required=True, order=3, prompt_key="dates_start"),
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
