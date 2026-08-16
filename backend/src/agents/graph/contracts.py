"""Per-worker data contracts (doc §36): what a worker node may read and
write, enforced at the node boundary rather than trusted.

`reads`/`writes` entries are `TravelState` dotted paths (`ALLOWED_PATHS`
shape, wildcard segments included), never graph-state keys or node names —
that split matters because `enforce_contract` diffs the *business* state
(`state["travel_state"]`), not the execution scratch fields every worker
also touches (`task_results`, `pending_tasks`, ...).

`emits_reply` is the one exception to that split, and it exists because
nothing else in the graph obliged a worker to speak: `respond` only ever
*picks up* a reply left in `task_results`, so a worker that finished its
job silently produced a successful turn answered by a generic
acknowledgement. Declaring `emits_reply=True` turns "this worker speaks
every time it finishes" into a checked obligation instead of a convention.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from src.agents.graph.state import TravelGraphState
from src.config import get_settings

logger = logging.getLogger(__name__)


class ContractViolation(RuntimeError):
    """A node wrote a `TravelState` path outside its declared contract, or
    finished its work without leaving the reply it declared it would."""


@dataclass(frozen=True)
class NodeContract:
    reads: frozenset[str]
    writes: frozenset[str]
    tools: frozenset[str] = frozenset()
    # Does this worker owe the user a reply on every turn it finishes?
    # Enforced against the `task_results` entries the node appends, with
    # two exemptions the node signals in its own update — see
    # `_is_continuation` and `unresolved_resume_text` in `enforce_contract`.
    emits_reply: bool = False


# qa_node is read-only by construction (doc §36) — the empty `writes` set is
# what stops a Q&A turn from mutating a trip; hotel_node/itinerary_node stay
# scoped to their own workflow's paths per IMPACT_MAP even once Phases 8-9
# fill their bodies. booking_node writes nothing today: it only replies.
#
# Every worker the supervisor can delegate to declares `emits_reply` —
# delegation means the turn is answered by that worker, so a silent one
# leaves the user with a generic ack. `qa_node` is the exception twice
# over: it is never wrapped by `enforce_contract` (graph.py) and it answers
# through the `messages` channel rather than `task_results`.
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
        emits_reply=True,
    ),
    "itinerary_node": NodeContract(
        reads=frozenset({
            "destination",
            "dates.start",
            "dates.end",
            "people",
            "preferences.themes",
            "preferences.pace",
            # Phase 9 / review finding F4: the patch-validated lock list --
            # synced into trip_data's planning_constraints, authoritative.
            "locked_days",
        }),
        writes=frozenset({
            # Phase 9: day-level theme overrides
            "daily_preferences.*.theme",
            "constraints.max_items_per_day",
        }),
        tools=frozenset(),
        emits_reply=True,
    ),
    "booking_node": NodeContract(
        reads=frozenset(), writes=frozenset(), tools=frozenset(), emits_reply=True
    ),
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

def _violate(message: str) -> None:
    """Raise or log, per `contract_enforcement_mode`.

    Raising in production turns a silent worker into a lost turn (HTTP 500)
    — worse for the user than the bad reply the check exists to catch. The
    default is `strict` so CI, which runs on defaults, still refuses to
    merge a new violation; production sets `log` and degrades to the
    generic acknowledgement plus a loud log line instead."""
    if getattr(get_settings(), "contract_enforcement_mode", "strict") == "log":
        logger.error("ContractViolation (mode=log, not raised): %s", message)
        return
    raise ContractViolation(message)


def _is_continuation(node_name: str, update: Mapping[str, Any]) -> bool:
    """The worker re-queued itself, so it is mid-job, not done.

    `itinerary_node` builds a multi-day trip one day per invocation, keeping
    itself in `pending_tasks` until the queue drains. Those intermediate
    turns are correctly silent — the user hears about the trip once, when it
    is finished."""
    return node_name in (update.get("pending_tasks") or [])


def _new_reply_entries(state: TravelGraphState, update: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The `task_results` entries this node appended during this call."""
    before_count = len(state.get("task_results") or [])
    after = update.get("task_results", state.get("task_results") or [])
    return list(after)[before_count:]


def enforce_contract(
    node_name: str, node_fn: Callable[[TravelGraphState], dict[str, Any]]
) -> Callable[[TravelGraphState], dict[str, Any]]:
    """Wrap a worker node so any `travel_state` path it writes outside its
    declared contract, or any turn it finishes without the reply it declared
    it owes, is caught at the node boundary instead of silently corrupting
    state another worker owns or reaching the user as a generic ack."""
    contract = CONTRACTS[node_name]

    def _wrapped(state: TravelGraphState) -> dict[str, Any]:
        before = state.get("travel_state") or {}
        update = node_fn(state)
        after = update.get("travel_state", before)
        violations = {path for path in changed_paths(before, after) if not _allowed(path, contract.writes)}
        if violations:
            _violate(f"{node_name} wrote path(s) outside its contract: {sorted(violations)}")

        if contract.emits_reply and not _is_continuation(node_name, update):
            # `unresolved_resume_text` marks the turn `_run_turn_via_graph`
            # discards and replays as a fresh turn (hotel_node's unresolved
            # search centre): its empty reply never reaches the user, so
            # demanding one here would be demanding dead text.
            if not update.get("unresolved_resume_text"):
                new_entries = _new_reply_entries(state, update)
                if not any(str(entry.get("reply") or "").strip() for entry in new_entries):
                    _violate(
                        f"{node_name} declares emits_reply but left no reply "
                        f"(appended {len(new_entries)} task_results entr"
                        f"{'y' if len(new_entries) == 1 else 'ies'}, none with reply text)"
                    )
        return update

    _wrapped.__name__ = f"{node_name}_contract_enforced"
    return _wrapped
