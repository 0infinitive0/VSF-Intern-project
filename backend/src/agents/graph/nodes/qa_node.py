"""`qa_node` — the ReAct agent, reduced to a read-only worker.

Node-vs-subgraph table (Phase 5 doc): `create_react_agent` returns a
*compiled graph*, so this is wired as a subgraph node, not a plain
function — and its checkpointer is passed explicitly, sharing the
app-lifespan checkpointer every other node in this graph uses (Phase 4),
rather than falling back to a fresh `MemorySaver()`.

Tool list is `query_hotel`/`query_hotel_rooms` ONLY.
`recommend_hotels`/`select_hotel`/`modify_trip_plan` are worker node
actions now (`CONTRACTS["qa_node"].writes` is empty) — the model can no
longer decide whether a trip gets rebuilt, only answer questions about
already-generated hotel data. It never appears in `pending_tasks`
bookkeeping: the parent graph state (`TravelGraphState`) and this
subgraph's own state share only the `messages` channel, so `travel_state`/
`pending_tasks`/`task_results` are structurally unreachable from inside
it — the contract is enforced by the schema boundary itself, not a runtime
check.
"""

from __future__ import annotations

from typing import Any, Sequence

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import create_react_agent

from src.agents.tools.get_itinerary import get_current_itinerary
from src.agents.tools.search_hotels import search_hotels
from src.agents.tools.search_places import search_places
from src.agents.tools.select_place import select_place
from src.agents.tools.time import current_time
from src.services.llm import get_fast_llm

QA_TOOLS: Sequence[Any] = (
    current_time,
    get_current_itinerary,
    search_hotels,
    search_places,
    select_place,
)

QA_SYSTEM_PROMPT = (
    "You answer questions about hotels and rooms already shown to the user, "
    "and you can search for nearby places like restaurants or attractions. "
    "You never modify the trip, never recommend or select a hotel, and never "
    "build or edit an itinerary — use only the provided tools."
)


def build_qa_subgraph(checkpointer: BaseCheckpointSaver, *, temperature: float = 0.2) -> CompiledStateGraph:
    llm = get_fast_llm(temperature=temperature)
    return create_react_agent(
        llm,
        list(QA_TOOLS),
        checkpointer=checkpointer,
        prompt=QA_SYSTEM_PROMPT,
    )
