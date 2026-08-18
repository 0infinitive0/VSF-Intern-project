"""`get_hotel_options` — the whole shortlist, for questions that span it.

`query_hotel` answers about ONE hotel the caller can already name. Nothing
answered "which of these is cheapest?", "list them again", or "which has a
pool AND breakfast?" — the model had to guess an identifier, call
`query_hotel`, and repeat, which it mostly resolved by asking the user to
pick a hotel first ("bạn muốn mình kiểm tra tất cả 5 khách sạn chứ?"). One
call now returns the comparable fields for every card on screen.

Deliberately compact: the card list can be a dozen hotels, this is a
read-only lookup that runs inside a ReAct loop with a token budget
(`qa_node.fit_context_window`), and the fields below are the ones users
actually compare on. `query_hotel` remains the way to get depth on one
hotel once the model knows which.
"""

from __future__ import annotations

import json
import logging

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from src.agents.graph.state import TravelGraphState
from src.agents.tools.shown_hotels import labelled_amenities, shown_hotel_options
from src.i18n import t

logger = logging.getLogger(__name__)

#: Enough to compare on without pulling whole descriptions into the loop.
_AMENITY_PREVIEW_LIMIT = 8


@tool
def get_hotel_options(
    *,
    runtime: ToolRuntime[None, TravelGraphState],
) -> Command:
    """
    Use this to see the CURRENT list of hotels shown to the user, with the
    fields needed to compare them: rank, name, area, nightly price, review
    score, star rating and amenities.

    Call this FIRST for any question that spans the list rather than naming
    one hotel — "which is cheapest?", "which has a pool?", "list them",
    "which is closest to the beach?", "compare 1 and 3" — and for any
    question where you need to know what the user is looking at. Use
    `query_hotel` afterwards only when you need more depth on one of them.
    """
    language = str(runtime.state.get("language") or "vi")
    options = shown_hotel_options(runtime.state)

    if not options:
        reply = t(
            "Chưa có danh sách khách sạn nào. Hãy nói với người dùng rằng bạn cần tìm khách sạn trước.",
            language,
        ) if language == "vi" else "No hotel list exists yet. Tell the user a hotel search is needed first."
        return Command(update={"messages": [ToolMessage(reply, tool_call_id=runtime.tool_call_id)]})

    summary = []
    for index, option in enumerate(options, start=1):
        amenities = labelled_amenities(option.get("amenities"), language=language)
        summary.append(
            {
                # `rank` is what the cards are numbered by; fall back to
                # position so a card missing it is still referable by "số N".
                "rank": option.get("rank") or index,
                "name": option.get("name"),
                "area": option.get("area_name") or option.get("city"),
                "price_per_night": option.get("average_nightly_price") or option.get("lowest_price"),
                "total_stay_price": option.get("total_stay_price"),
                "currency": option.get("currency") or "VND",
                "review_score": option.get("review_score"),
                "review_count": option.get("review_count"),
                "star_rating": option.get("star_rating"),
                "amenities": amenities[:_AMENITY_PREVIEW_LIMIT],
                "amenities_truncated": len(amenities) > _AMENITY_PREVIEW_LIMIT,
            }
        )

    payload = json.dumps(summary, ensure_ascii=False, indent=2)
    reply = (
        f"The user is currently looking at these {len(summary)} hotels. "
        f"Refer to them by `rank` (\"khách sạn số 1\"):\n{payload}"
    )
    return Command(update={"messages": [ToolMessage(reply, tool_call_id=runtime.tool_call_id)]})
