"""`qa_node` — the ReAct agent, reduced to a read-only worker.

Node-vs-subgraph table (Phase 5 doc): `create_react_agent` returns a
*compiled graph*, so this is wired as a subgraph node, not a plain
function — and its checkpointer is passed explicitly, sharing the
app-lifespan checkpointer every other node in this graph uses (Phase 4),
rather than falling back to a fresh `MemorySaver()`.

Tool list is `query_hotel`/`query_hotel_rooms` (Phase 5) plus `search_places`
(Phase 13, `phase-13-place-search.md`). `recommend_hotels`/`select_hotel`/
`modify_trip_plan` are worker node actions now (`CONTRACTS["qa_node"].writes`
is empty) — the model can no longer decide whether a trip gets rebuilt, only
answer questions about already-generated hotel data or search for places. It
never appears in `pending_tasks` bookkeeping: the parent graph state
(`TravelGraphState`) and this subgraph's own state share only the `messages`
channel, so `travel_state`/`pending_tasks`/`task_results` are structurally
unreachable from inside it — the contract is enforced by the schema boundary
itself, not a runtime check. This is why `search_places` takes `destination`
as an explicit tool argument (the model already has it from conversation
history) rather than reading `travel_state` — there is nothing to read.

No `select_place` tool: the plan's own Architecture section is explicit that
"a picked suggestion" is resolved through a pause-and-resume point **inside
`rebuild_day`** (`subgraphs/rebuild_day.py`, via LangGraph's interrupt
mechanism), not a qa_node tool call — the
plan's "Hotels (exists) | Places (new)" comparison table describing a
`select_place(selection)` tool documents the *legacy plane's* prior art it
is superseding, not the target design. A qa_node tool that applies an edit
would also contradict this node's own charter ("You never modify the trip").
The general interrupt-resume path (`routes.py::_run_turn_via_graph`) already
carries a shortlist reply back to whichever node paused — no separate tool
is needed for the user's reply to reach it.

This is the only node handed the whole `messages` channel, so it is also
the only one whose prompt grows with the conversation — every other prompt
in the graph is a single message plus structured facts. `fit_context_window`
(`pre_model_hook`) is what bounds it; see its docstring.

Deliberately NOT wired here: `get_current_itinerary`/`search_hotels`/
`current_time` tools some in-progress branches reference. Those modules
don't exist and aren't in any accepted plan (`phase-13-place-search.md`
only asks for `search_places`) — adding them here would be inventing a
design for someone else's unscoped feature.
"""

from __future__ import annotations

from typing import Any, Sequence

from langchain_core.messages.utils import count_tokens_approximately, trim_messages
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import create_react_agent

from src.agents.tools.query_hotel import query_hotel
from src.agents.tools.query_hotel_rooms import query_hotel_rooms
from src.agents.tools.search_places import search_places
from src.config import get_settings
from src.services.llm import get_fast_llm

QA_TOOLS: Sequence[Any] = (
    query_hotel,
    query_hotel_rooms,
    search_places,
)

QA_SYSTEM_PROMPT = (
    "You answer questions about hotels and rooms already shown to the user, "
    "and you can search for nearby places like restaurants or attractions. "
    "You never modify the trip, never recommend or select a hotel, and never "
    "build or edit an itinerary — use only the provided tools."
)


def fit_context_window(state: dict[str, Any]) -> dict[str, Any]:
    """Keep the newest slice of the transcript within a token budget.

    Runs as `create_react_agent`'s `pre_model_hook`, i.e. before EVERY LLM
    call in the ReAct loop rather than once per turn — so a single question
    that fans out into several tool calls cannot grow past the budget
    mid-turn either.

    Returns `llm_input_messages`, the key LangGraph adds to the agent's
    state schema for exactly this (`chat_agent_executor.py`): it is what
    `call_model` reads, while the persisted `messages` channel is left
    untouched. Trimming here therefore changes what the model is shown, not
    what the conversation remembers — the parent graph's transcript, and
    `respond`'s `asked_slot` tags on it, stay whole.

    `start_on`/`end_on` are load-bearing, not tuning: this agent's history
    interleaves `AIMessage(tool_calls=...)` with the `ToolMessage` answering
    it, and a window boundary landing between the two produces an orphaned
    half that the provider rejects outright (`tool_call_id not found`) — a
    hard failure, not a quality loss. Both arguments force the cut onto a
    valid boundary.

    Counting is `count_tokens_approximately` (local, tokenizer-free): an
    estimate is the right tool for a budget whose purpose is bounding cost,
    and it costs no API round-trip to compute.
    """
    return {
        "llm_input_messages": trim_messages(
            state["messages"],
            strategy="last",
            token_counter=count_tokens_approximately,
            max_tokens=get_settings().qa_context_token_budget,
            start_on="human",
            end_on=("human", "tool"),
        )
    }


def build_qa_subgraph(checkpointer: BaseCheckpointSaver, *, temperature: float = 0.2) -> CompiledStateGraph:
    llm = get_fast_llm(temperature=temperature)
    return create_react_agent(
        llm,
        list(QA_TOOLS),
        checkpointer=checkpointer,
        prompt=QA_SYSTEM_PROMPT,
        pre_model_hook=fit_context_window,
    )
