"""`booking_node` — declines explicitly, it does not pass through.

`plan.md` defers booking entirely: no auth model, no inventory source. But
the supervisor needs a routable destination for a booking request, or such
a turn would silently fall to `respond` with nothing said — the exact
silent no-op this whole plan exists to eliminate. So this node answers: it
states booking is not supported yet and names what the user can do instead.

`_IMPOSSIBLE["booking_node"]` (`routing.py`) is unconditionally `True`,
which keeps the supervisor from ever selecting this node for planning work
today — nothing routes here yet in Phase 5 (no intent classification
exists before Phase 6). The node's body is real and independently
correct regardless: once a later phase adds an explicit-booking-intent
path that bypasses the possibility guard, this is what it will land on.
"""

from __future__ import annotations

from typing import Any

from src.agents.graph.state import TravelGraphState

_WORKER_NAME = "booking_node"

_DECLINE_VI = (
    "Mình chưa hỗ trợ đặt chỗ trực tiếp — bạn có thể xem và chọn khách sạn/lịch trình ở đây, "
    "rồi tự đặt qua kênh của khách sạn hoặc đại lý du lịch."
)
_DECLINE_EN = (
    "I can't book anything directly yet — you can browse and pick a hotel/itinerary here, "
    "then book through the hotel's own channel or a travel agent."
)


def booking_node(state: TravelGraphState) -> dict[str, Any]:
    reply = _DECLINE_EN if state.get("language") == "en" else _DECLINE_VI
    pending = [worker for worker in (state.get("pending_tasks") or []) if worker != _WORKER_NAME]
    task_results = [
        *(state.get("task_results") or []),
        {"worker": _WORKER_NAME, "status": "declined", "reply": reply},
    ]
    return {"pending_tasks": pending, "task_results": task_results}
