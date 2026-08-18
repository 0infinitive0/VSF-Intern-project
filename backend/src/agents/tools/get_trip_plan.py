"""`get_trip_plan` — the itinerary that has actually been built.

`qa_node` could see hotels and nearby places but never the plan itself, so
every question about the thing the user was looking at on the right-hand
panel — "what am I doing on day 2?", "how far is the museum from the
hotel?", "when do I check out?", "is there time for lunch on day 3?" — had
no source to answer from. The model either declined or improvised from the
transcript, which is exactly the ungrounded answer this node exists to
avoid.

Read-only, like the rest of this node's tools: seeing the plan is not
editing it, and `CONTRACTS["qa_node"].writes` stays empty.

The route/coordinate/image fields of the real payload are dropped here.
They exist to draw the map, are the bulk of its size, and carry nothing the
model can say out loud — except the leg distances and durations, which are
what "how far" questions need, so those two are kept and everything else in
`route_to_next` is not.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from src.agents.graph.state import TravelGraphState
from src.i18n import t
from src.services.trip_formatter import to_trip_plan_payload

logger = logging.getLogger(__name__)


def _leg(route: Any) -> dict[str, Any] | None:
    """Distance/duration only — the polyline is for the map, not the model."""
    if not isinstance(route, dict):
        return None
    distance = route.get("distance_km")
    duration = route.get("duration_mins")
    if distance is None and duration is None:
        return None
    return {"distance_km": distance, "duration_mins": duration}


@tool
def get_trip_plan(
    *,
    runtime: ToolRuntime[None, TravelGraphState],
) -> Command:
    """
    Use this to see the CURRENT itinerary: destination, dates, the chosen
    hotel, and every day with its theme, activities and times.

    Call this for any question about the plan itself — "what's on day 2?",
    "when do I visit X?", "how far is that from the hotel?", "how many days
    is my trip?", "which hotel did I pick?" — and before answering anything
    that depends on what is already scheduled. Returns an explicit
    "no itinerary yet" when the user has not built one.
    """
    language = str(runtime.state.get("language") or "vi")
    plan = to_trip_plan_payload(runtime.state.get("trip_data"))

    if not plan:
        reply = t(
            "Chưa có lịch trình nào được tạo. Hãy nói với người dùng rằng cần chọn khách sạn và tạo lịch trình trước.",
            language,
        ) if language == "vi" else (
            "No itinerary has been built yet. Tell the user a hotel must be chosen and an itinerary created first."
        )
        return Command(update={"messages": [ToolMessage(reply, tool_call_id=runtime.tool_call_id)]})

    hotel = plan.get("hotel") or {}
    summary = {
        "destination": plan.get("destination"),
        "start_date": plan.get("start_date"),
        "end_date": plan.get("end_date"),
        "duration_days": plan.get("duration_days"),
        "number_of_adults": plan.get("number_of_adults"),
        "hotel": {"name": hotel.get("name"), "star_rating": hotel.get("star_rating")},
        "days": [
            {
                "day_number": day.get("day_number"),
                "theme": day.get("theme"),
                "items": [
                    {
                        "start_time": item.get("start_time"),
                        "end_time": item.get("end_time"),
                        "activity": item.get("activity"),
                        "kind": item.get("kind"),
                        "travel_to_next": _leg(item.get("route_to_next")),
                        "travel_from_hotel": _leg(item.get("route_from_hotel")),
                    }
                    for item in day.get("items") or []
                ],
            }
            for day in plan.get("days") or []
        ],
    }

    payload = json.dumps(summary, ensure_ascii=False, indent=2)
    reply = f"Here is the user's current itinerary:\n{payload}"
    return Command(update={"messages": [ToolMessage(reply, tool_call_id=runtime.tool_call_id)]})
