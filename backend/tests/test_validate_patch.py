"""`validate_patch`'s budget.target -> budget.min/budget.max derivation.

A "khoảng X" / "tầm X" chat answer only ever sets budget.target (prompts.py's
per-field contract: a single preferred price). Without a derived band,
budget.min/budget.max stay UNKNOWN -- the frontend's slider has nothing to
draw and the hotel search RPC applies no price filter at all. See
plans/reports/ for the budget.target-vs-range design discussion this pins.
"""

from __future__ import annotations

from src.agents.graph.nodes.validate_patch import validate_patch
from src.agents.graph.state import TravelGraphState, initial_graph_state


def _state(patch: list[dict], travel_state: dict | None = None) -> TravelGraphState:
    state = initial_graph_state("t1")
    state["travel_state"] = travel_state or {}
    state["patch"] = patch
    return state


def test_bare_target_derives_a_percentage_band() -> None:
    result = validate_patch(_state([{"path": "budget.target", "operation": "set", "value": 1_000_000}]))

    proposed = result["proposed_travel_state"]
    assert proposed["budget.target"]["value"] == 1_000_000
    assert proposed["budget.min"]["value"] == 800_000
    assert proposed["budget.max"]["value"] == 1_200_000


def test_low_target_uses_the_floor_tolerance_and_clamps_at_zero() -> None:
    """"tầm 100k" -- 20% of 100k (20k) is below the 100k floor, so the floor
    wins; the lower edge clamps at 0 rather than going negative."""
    result = validate_patch(_state([{"path": "budget.target", "operation": "set", "value": 100_000}]))

    proposed = result["proposed_travel_state"]
    assert proposed["budget.min"]["value"] == 0.0
    assert proposed["budget.max"]["value"] == 200_000


def test_no_preference_target_derives_nothing() -> None:
    """The explicit "bao nhiêu cũng được" answer sets budget.target to null
    -- not a number to build a band around."""
    result = validate_patch(_state([{"path": "budget.target", "operation": "set", "value": None}]))

    proposed = result["proposed_travel_state"]
    assert "budget.min" not in proposed
    assert "budget.max" not in proposed


def test_explicit_range_in_the_same_turn_is_never_overridden() -> None:
    """"2-3 triệu/đêm" sets target AND an explicit min/max in one patch --
    the derived band must not clobber the explicit answer."""
    result = validate_patch(
        _state(
            [
                {"path": "budget.target", "operation": "set", "value": 2_500_000},
                {"path": "budget.min", "operation": "set", "value": 2_000_000},
                {"path": "budget.max", "operation": "set", "value": 3_000_000},
            ]
        )
    )

    proposed = result["proposed_travel_state"]
    assert proposed["budget.min"]["value"] == 2_000_000
    assert proposed["budget.max"]["value"] == 3_000_000


def test_a_prior_turns_explicit_range_is_never_overridden() -> None:
    """A later turn answering only budget.target (e.g. correcting the
    preferred price) must not blow away an already-SET explicit range from
    an earlier turn."""
    existing_travel_state = {
        "budget.min": {"presence": "set", "value": 1_500_000},
        "budget.max": {"presence": "set", "value": 2_500_000},
    }
    result = validate_patch(
        _state(
            [{"path": "budget.target", "operation": "set", "value": 1_800_000}],
            travel_state=existing_travel_state,
        )
    )

    proposed = result["proposed_travel_state"]
    assert proposed["budget.min"]["value"] == 1_500_000
    assert proposed["budget.max"]["value"] == 2_500_000
