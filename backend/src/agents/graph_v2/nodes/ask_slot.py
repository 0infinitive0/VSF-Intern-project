"""`ask_slot` — Phase 7 stub.

Phase 7 fills this with the slot registry and `next_question` derivation,
plus the actual `interrupt()` call that pauses the turn for a reply.
`missing_slots` is never populated before Phase 7 lands (nothing upstream
writes it), so `route_ask_slot` always falls through to `supervisor`.
"""

from __future__ import annotations

from typing import Any

from src.agents.graph_v2.state import TravelGraphState


def ask_slot(state: TravelGraphState) -> dict[str, Any]:  # noqa: ARG001
    return {"missing_slots": [], "next_question": None}
