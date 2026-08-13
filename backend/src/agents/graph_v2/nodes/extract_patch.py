"""`extract_patch` — Phase 6 stub.

Phase 6 fills this with LLM-based patch extraction from the latest user
message, producing `{path, operation, value}` changes for
`validate_patch`/`apply_patch` to run through the Phase 3 patch layer. For
Phase 5 the pipeline must exist and be wired end to end, so this always
proposes zero changes: a turn that reaches here today flows through with an
empty patch, which is consistent with `hotel_node`/`itinerary_node` also
being pass-through stubs in this phase.
"""

from __future__ import annotations

from typing import Any

from src.agents.graph_v2.state import TravelGraphState


def extract_patch(state: TravelGraphState) -> dict[str, Any]:  # noqa: ARG001
    return {"patch": []}
