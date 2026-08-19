"""Which graph nodes report progress, and which are allowed to stream tokens.

Both maps are read by `routes.py`'s streaming branch while draining
`app.stream(stream_mode=["updates", "messages"])`.

Only nodes worth a line of UI appear in `PHASE_KEY_BY_NODE`. `scope_guard`,
`validate_patch`, `apply_patch`, `ask_slot`, `budget_check` and `booking_node`
are deliberately absent: they finish faster than a user can read, and a
progress list that scrolls is worse than one that doesn't move.

`hotel_node` and `itinerary_node` are absent for a different, more specific
reason. The work itself already emits a finer-grained phase from inside —
`hotel_search` (`hotel_node`'s own `_result`, which every exit path returns
through, carrying the destination, radius, amenities and result count), plus
`itinerary_build` (`trip_planner.py`), `routing_legs` (`routing.py`) and
`persisting` (`itinerary_store.py`). Mapping the node as well would emit the
same key twice for one turn, and the frontend keys its progress rows by
`${key}-${at}`, so the user would see the same step listed twice. The
in-service emits win because they say more; the node mapping covers only nodes
that report nothing about themselves.
"""

from __future__ import annotations

#: Graph node name -> the frontend's `PhaseKey` (frontend/src/types.ts). A node
#: missing from this map emits no phase frame.
PHASE_KEY_BY_NODE: dict[str, str] = {
    "load_context": "compacting_history",
    "extract_patch": "intake_check",
    "supervisor": "routing",
    "intake_qa": "generating",
    "qa_node": "generating",
}

#: Nodes whose LLM tokens may be forwarded to the client as `delta` frames.
#:
#: A WHITELIST on purpose: a node added later streams nothing until someone
#: adds it here deliberately. The two members are the only nodes that produce
#: prose for the user to read. Everything else that touches the `messages`
#: channel must stay out, and not merely as a matter of taste:
#:
#: - `extract_patch` and `supervisor` emit JSON. Streaming either shows the
#:   user the machinery.
#: - `respond` writes the turn's finished reply into the same channel, so
#:   forwarding it would send the whole answer twice — once as deltas, then
#:   again inside the `final` frame.
#:
#: Verified empirically against `stream_mode="messages"`: `qa_node`'s ReAct
#: subgraph reports `metadata["langgraph_node"] == "qa_node"` (the parent node
#: name, not an inner one), so matching on these names is enough.
STREAMING_NODES: frozenset[str] = frozenset({"qa_node", "intake_qa"})

#: For a member of `STREAMING_NODES` that is a compiled subgraph, the ONE inner
#: node whose tokens are the reply.
#:
#: `qa_node` is a `create_react_agent` subgraph, so its tokens only become
#: visible when the drain streams with `subgraphs=True`. That also exposes every
#: other node inside it — and measured 2026-08-19, the `tools` node emits a
#: `ToolMessage` whose content is real text (a tool's error string, in the run
#: that was recorded). Allowing a whole subgraph by name would put that on the
#: user's screen, so membership is by (subgraph, inner node), not by subgraph.
#:
#: A plain node has no entry here: it streams under the empty namespace and is
#: matched by `STREAMING_NODES` alone.
SUBGRAPH_STREAMING_NODE: dict[str, str] = {"qa_node": "agent"}
