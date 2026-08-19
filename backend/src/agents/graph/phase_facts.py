"""Facts a finished node contributes to its `phase` SSE frame.

The frontend owns every word the user reads (`phase-labels.ts`); the backend
sends opaque keys and numbers. This module is the second half of that contract:
it turns the dict a node just returned into the handful of values a progress
line needs, and nothing else.

**Default deny.** Every node without a branch here contributes `{}`. That is not
defensiveness for its own sake — see the observed shapes below: `load_context`
returns the entire graph state (22 keys, including the full `response` payload
and every `task_result`), and `supervisor` returns free-text the LLM wrote. A
whitelist is the only structure where adding a node cannot accidentally publish
either.

## Observed update shapes (measured 2026-08-19, not read off `return` statements)

    node             phase key             keys in the update dict
    ---------------- --------------------- ---------------------------------------
    load_context     compacting_history    22 keys: the whole state, incl. response
    scope_guard      —                     None  ← not a dict at all
    extract_patch    intake_check          patch, intent, extraction_failed,
                                           patch_reason, pending_clarify_day
    validate_patch   —                     proposed_travel_state, applied_changes,
                                           rejected_changes, impacted_workflows
    apply_patch      —                     travel_state, pending_tasks
    ask_slot         —                     missing_slots, next_question
    supervisor       routing               next_worker, task_description,
                                           routing_source, routing_reasoning,
                                           supervisor_iterations
    hotel_node       hotel_search          pending_tasks, task_results
    intake_qa        generating            intake_answer
    qa_node          generating            language, messages
    respond          —                     messages, response

Two of those contradicted the plan that specified this module, which is why the
shapes were observed before the code was written:

- `scope_guard` returns `None`, so `update` is not always a dict.
- `supervisor.task_description` and `.routing_reasoning` are prose the LLM wrote
  ("auto-routed to hotel_node via impact_map"). Sending them would put
  backend-authored display text on the wire, which is the one thing the phase
  contract forbids. Only `next_worker` — a node name, effectively an enum —
  leaves this module.

`hotel_node` carries no search counts (confirmed above: only `pending_tasks` and
`task_results`), so `hotel_search` facts are emitted from inside the node instead,
next to the numbers themselves.
"""

from __future__ import annotations

from typing import Any

#: Patch entries name a field path in the travel-state schema (`budget.target`,
#: `dates.start`). Those are schema identifiers, not user content — the frontend
#: already labels them — so they cross the wire; the accompanying `value` never does.
_MAX_FIELDS = 12


def _fields_from_patch(patch: Any) -> list[str]:
    """Field paths a patch touches, in order, without their values."""
    if not isinstance(patch, list):
        return []
    paths = []
    for change in patch:
        if isinstance(change, dict):
            path = change.get("path")
            if isinstance(path, str) and path:
                paths.append(path)
    return paths[:_MAX_FIELDS]


def _intake_check_facts(update: dict) -> dict[str, Any]:
    facts: dict[str, Any] = {}
    intent = update.get("intent")
    # An empty intent is what `load_context` seeds; only a real classification is a fact.
    if isinstance(intent, str) and intent:
        facts["intent"] = intent
    fields = _fields_from_patch(update.get("patch"))
    if fields:
        facts["fields"] = fields
    return facts


def _routing_facts(update: dict) -> dict[str, Any]:
    worker = update.get("next_worker")
    # `task_description` and `routing_reasoning` sit right next to this one in the
    # same dict and are deliberately not read: both are LLM prose.
    return {"worker": worker} if isinstance(worker, str) and worker else {}


#: node name -> extractor. Absent means no facts, which is the default for every
#: node that is not listed.
_EXTRACTORS = {
    "extract_patch": _intake_check_facts,
    "supervisor": _routing_facts,
}


def phase_facts(node_name: str, update: Any) -> dict[str, Any]:
    """Facts to attach to `node_name`'s `phase` frame; `{}` when there are none.

    Never raises. It runs inside a chat turn, and a progress annotation must not
    be able to cost the user their answer — `emit_phase` holds the same contract
    for the same reason.

    `update` is whatever the node returned, which is not always a dict
    (`scope_guard` returns `None`).
    """
    if not isinstance(update, dict):
        return {}
    extractor = _EXTRACTORS.get(node_name)
    if extractor is None:
        return {}
    try:
        return extractor(update)
    except Exception:  # a malformed update must not end the turn
        return {}
