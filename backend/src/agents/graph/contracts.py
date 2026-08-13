"""Per-worker data contracts (doc §36): what a worker node may read and
write, enforced at the node boundary rather than trusted.

`reads`/`writes` entries are `TravelState` dotted paths (`ALLOWED_PATHS`
shape, wildcard segments included), never graph-state keys or node names —
that split matters because `enforce_contract` diffs the *business* state
(`state["travel_state"]`), not the execution scratch fields every worker
also touches (`task_results`, `pending_tasks`, ...).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from src.agents.graph.state import TravelGraphState


class ContractViolation(RuntimeError):
    """A node wrote a `TravelState` path outside its declared contract."""


@dataclass(frozen=True)
class NodeContract:
    reads: frozenset[str]
    writes: frozenset[str]
    tools: frozenset[str] = frozenset()


# qa_node is read-only by construction (doc §36) — the empty `writes` set is
# what stops a Q&A turn from mutating a trip; hotel_node/itinerary_node stay
# scoped to their own workflow's paths per IMPACT_MAP even once Phases 8-9
# fill their bodies. booking_node writes nothing today: it only replies.
CONTRACTS: dict[str, NodeContract] = {
    "hotel_node": NodeContract(
        reads=frozenset(
            {
                "destination",
                "dates.start",
                "dates.end",
                "people",
                "budget.min",
                "budget.max",
                "budget.target",
                "hotel_preferences.amenities",
                "hotel_preferences.radius_km",
                "hotel_preferences.center",
                "hotel_preferences.min_star_rating",
                "hotel_preferences.min_review_score",
            }
        ),
        writes=frozenset(
            {
                "hotel_preferences.amenities",
                "hotel_preferences.radius_km",
                "hotel_preferences.center",
                "hotel_preferences.min_star_rating",
                "hotel_preferences.min_review_score",
            }
        ),
        tools=frozenset(),
    ),
    "itinerary_node": NodeContract(
        reads=frozenset({
            "destination",
            "dates.start",
            "dates.end",
            "people",
            "preferences.themes",
            "preferences.pace",
            # Phase 9: the full trip bundle and locked-days constraint
            "trip_data",
            "planning_constraints.locked_days",
        }),
        writes=frozenset({
            # Phase 9: day-level theme overrides and planning_constraints.locked_days
            "daily_preferences.*.theme",
            "constraints.max_items_per_day",
            "planning_constraints.locked_days",
            # itinerary_node owns the trip_data written back after rebuild_day
            "trip_data",
        }),
        tools=frozenset(),
    ),
    "booking_node": NodeContract(reads=frozenset(), writes=frozenset(), tools=frozenset()),
    "qa_node": NodeContract(
        reads=frozenset({"destination", "dates.start", "dates.end"}),
        writes=frozenset(),
        tools=frozenset({"query_hotel", "query_hotel_rooms"}),
    ),
}


def _path_matches(pattern: str, path: str) -> bool:
    if pattern == path:
        return True
    if "*" not in pattern:
        return False
    pattern_segments = pattern.split(".")
    path_segments = path.split(".")
    if len(pattern_segments) != len(path_segments):
        return False
    return all(p == "*" or p == s for p, s in zip(pattern_segments, path_segments))


def _allowed(path: str, writes: frozenset[str]) -> bool:
    return any(_path_matches(pattern, path) for pattern in writes)


def changed_paths(before: Mapping[str, Any], after: Mapping[str, Any]) -> set[str]:
    """`TravelState.to_dict()` paths added, removed, or changed between two
    snapshots — a plain dict diff since `to_dict()` is already flat."""
    changed: set[str] = set()
    for path in before.keys() | after.keys():
        if before.get(path) != after.get(path):
            changed.add(path)
    return changed

def enforce_contract(
    node_name: str, node_fn: Callable[[TravelGraphState], dict[str, Any]]
) -> Callable[[TravelGraphState], dict[str, Any]]:
    """Wrap a worker node so any `travel_state` path it writes outside its
    declared contract raises `ContractViolation` instead of silently
    corrupting state another worker owns."""
    contract = CONTRACTS[node_name]

    def _wrapped(state: TravelGraphState) -> dict[str, Any]:
        before = state.get("travel_state") or {}
        update = node_fn(state)
        after = update.get("travel_state", before)
        violations = {path for path in changed_paths(before, after) if not _allowed(path, contract.writes)}
        if violations:
            raise ContractViolation(f"{node_name} wrote path(s) outside its contract: {sorted(violations)}")
        return update

    _wrapped.__name__ = f"{node_name}_contract_enforced"
    return _wrapped
