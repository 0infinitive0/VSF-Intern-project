"""Phase 7 (260812-0927-langgraph-orchestration-state-patch-and-interrupts):
the declarative slot table that replaces `_run_intake`'s five-branch `if`
ladder — `next_question` is the one expression the ladder becomes.
"""

from __future__ import annotations

from src.domain.slot_registry import SLOT_REGISTRY, next_question
from src.domain.travel_state import TravelState, apply_patch

_FUTURE_START = "2099-01-01"
_FUTURE_END = "2099-01-05"


def _apply(state: TravelState, path: str, value: object) -> TravelState:
    return apply_patch(state, [{"path": path, "operation": "set", "value": value}]).state


def test_default_ordering_is_destination_people_dates_budget() -> None:
    ordered = [spec.name for spec in sorted(SLOT_REGISTRY, key=lambda s: s.order)]
    assert ordered == ["destination", "people", "dates.start", "dates.end", "budget.target"]


def test_next_question_on_empty_state_asks_destination_first() -> None:
    spec = next_question(TravelState())
    assert spec is not None
    assert spec.name == "destination"


def test_date_picker_is_not_gated_behind_budget() -> None:
    """The literal regression: destination + people known, budget untouched
    -- next_question must ask for a DATE, never budget, because dates.start
    sorts ahead of budget.target in SLOT_REGISTRY."""
    state = TravelState()
    state = _apply(state, "destination", "Đà Nẵng")
    state = _apply(state, "people", 2)

    spec = next_question(state)
    assert spec is not None
    assert spec.name == "dates.start"


def test_next_question_returns_none_once_every_required_slot_is_answered() -> None:
    state = TravelState()
    state = _apply(state, "destination", "Đà Nẵng")
    state = _apply(state, "people", 2)
    state = _apply(state, "dates.start", _FUTURE_START)
    state = _apply(state, "dates.end", _FUTURE_END)
    state = _apply(state, "budget.target", 1_000_000)

    assert next_question(state) is None


def test_budget_is_skippable_via_not_applicable_not_just_fixed_phrases() -> None:
    """The literal fix for the old 8-fixed-phrase escape hatch: ANY patch
    that sets budget.target to NOT_APPLICABLE (value=None) skips it -- no
    special-cased phrase list anywhere in this module."""
    state = TravelState()
    state = _apply(state, "destination", "Đà Nẵng")
    state = _apply(state, "people", 2)
    state = _apply(state, "dates.start", _FUTURE_START)
    state = _apply(state, "dates.end", _FUTURE_END)
    state = _apply(state, "budget.target", None)  # NOT_APPLICABLE

    assert next_question(state) is None


def test_budget_ceiling_only_counts_as_answered() -> None:
    """A user who only ever states a ceiling ("tối đa 5 triệu") sets
    budget.max, never budget.target -- that must still satisfy the budget
    slot, or the same question would loop forever despite a real answer."""
    state = TravelState()
    state = _apply(state, "destination", "Đà Nẵng")
    state = _apply(state, "people", 2)
    state = _apply(state, "dates.start", _FUTURE_START)
    state = _apply(state, "dates.end", _FUTURE_END)
    state = _apply(state, "budget.max", 5_000_000)

    assert next_question(state) is None


def test_an_already_filled_required_slot_never_reappears_as_next_question() -> None:
    state = _apply(TravelState(), "destination", "Đà Nẵng")
    spec = next_question(state)
    assert spec is not None
    assert spec.name == "people"

    # Revising the already-filled destination doesn't reset the pointer.
    state = _apply(state, "destination", "Huế")
    spec = next_question(state)
    assert spec is not None
    assert spec.name == "people"


def test_not_applicable_on_a_non_skippable_slot_does_not_satisfy_it() -> None:
    """A slot with skippable=False (every slot except budget) has no
    legitimate "no preference" answer -- a stray NOT_APPLICABLE (any patch
    can produce one via `value: null`, it is not scoped per-path) must not
    permanently mark it answered-but-empty and let intake proceed with, say,
    no destination at all."""
    state = _apply(TravelState(), "destination", None)  # -> NOT_APPLICABLE

    spec = next_question(state)
    assert spec is not None
    assert spec.name == "destination"
