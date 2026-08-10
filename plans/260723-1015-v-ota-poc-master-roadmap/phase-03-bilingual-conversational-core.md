---
phase: 3
title: "Bilingual conversational core"
status: pending
priority: P1
dependencies: [2]
effort: ""
---

# Phase 3: Bilingual conversational core

## Overview

Replace the 29-line template stub with a real LangGraph agent: bilingual intent understanding, multi-turn session context, grounded response generation, and a validation node that blocks hallucinated facts. This is BRD §13.2's "Lõi hội thoại" and the heart of Sprint 2.

## Requirements

- Functional: understand intent and extract parameters from Vietnamese, English, and mixed-language input (BR-03, BR-10).
- Functional: reply in the language the user is currently using (BR-10).
- Functional: maintain multi-turn session context — refinement must not restart the conversation (BR-04).
- Functional: every factual claim traces to a retrieved record; unsupported claims are blocked (BR-07).
- Non-functional: streaming responses (`design_proposal.md` §1 cites async streaming as the reason FastAPI was chosen).
- Non-functional: bounded context window to control LLM cost (BRD §10).

## Architecture

**Dialog state machine.** BRD §13.4 requires one as a Sprint 2 L3 deliverable with explicit "nhánh VI/EN". Design it before coding — it is both a required artifact and the clearest specification of what the graph must do. The five slots from `design_proposal.md` §3A's progressive profiling (Đi đâu, Từ đâu, Với ai, Khi nào, Phong cách) are the state to accumulate, and the Stitch comp already visualises them.

**Language handling.** Detect per-turn rather than per-session — BR-10's mixed-query requirement means a user may switch mid-conversation, and place names commonly appear in the other language. Carry the detected language through state so response generation and UI copy agree. Do *not* translate the query before searching: Phase 2's multilingual embeddings are designed to handle cross-language retrieval directly, and a translation hop adds latency, cost, and a failure mode.

**Grounding (BR-07) is the requirement most likely to embarrass the demo.** BRD §11 rates wrong AI information as Medium likelihood / High impact. `design_proposal.md` §4A already specifies the mechanism: a validation node that checks generated entities against retrieved records and forces re-grounding rather than emitting the claim. Implement it as a real graph node with a test, not a prompt instruction — prompt-only grounding fails silently and exactly when it matters.

**Graph shape:** detect language → classify intent → extract/merge slots → route (search | refine | itinerary | chitchat) → retrieve → generate → **validate** → respond. Validation failure loops back to retrieval, not to generation.

## Related Code Files

- Rewrite: `src/agents/graph.py` (29-line stub), `src/agents/state.py` (18-line stub), `src/services/llm.py` (12-line stub)
- Create: `src/agents/nodes/` — language detection, intent, slot extraction, generation, validation
- Create: `src/agents/tools/` — search tool wrapping Phase 2's `search.py`
- Create: `docs/dialog_state_machine.md` (BRD §13.4 required L3 artifact)
- Modify: `src/models/schemas.py` (conversation/session contracts)
- Read only: `design_proposal.md` §3A, §4A; `docs/design/v-ota-chat-ui/DESIGN.md`

## Implementation Steps

1. **Design and document the dialog state machine** with VI/EN branches. Required BRD deliverable; do it first because it specifies the graph.
2. **Define state schema** in `state.py`: messages, detected language, the five profiling slots, active filters, retrieved candidates, selected hotel.
3. **Implement per-turn language detection.** Handle the mixed case — a Vietnamese sentence containing an English hotel name is Vietnamese, not English.
4. **Implement intent classification and slot extraction** in one LLM call where practical; two calls per turn doubles cost for marginal benefit at PoC scale.
5. **Wire the search tool** to Phase 2's interface. The agent must not embed or query Qdrant directly — keep retrieval behind the service boundary.
6. **Implement grounded generation**, passing retrieved records as the only factual source, with explicit instruction to answer in the detected language.
7. **Implement the validation node.** Extract entity claims from the generated response, verify each against retrieved record IDs, and on failure re-ground rather than emit. Unit-test with a deliberately hallucinating fixture.
8. **Persist sessions and messages** to the `sessions` and `chat_messages` tables — they exist in the schema with no producer, and this phase is their producer.
9. **Expose a streaming chat endpoint** in `src/api/routes.py`, replacing the stub.

## Success Criteria

- [ ] `docs/dialog_state_machine.md` exists with VI/EN branches (BRD §13.4).
- [ ] Agent answers a Vietnamese query, an English query, and a mixed-language query, replying in the matching language.
- [ ] Multi-turn refinement preserves context — "rẻ hơn" after a search narrows rather than restarts.
- [ ] Validation node demonstrably blocks a hallucinated hotel, proven by test.
- [ ] Sessions and messages persist to Postgres.
- [x] Chat endpoint streams tokens. Shipped 07/08/2026 via `POST /api/v1/planner_chat/stream` (plan [`260806-1602-streaming-chat-messages`](../260806-1602-streaming-chat-messages/plan.md), Phase 3) — real `delta` SSE frames on the `_run_chat_agent` branch, gated so no tool-call JSON or `SYSTEM ERROR:` text ever streams.

## Risk Assessment

- **Risk:** Prompt-only grounding passes casual testing and fails at the demo.
  **Mitigation:** Step 7 makes validation a graph node with a hallucination fixture. Phase 6 re-tests adversarially, per BRD §11.
- **Risk:** Bilingual handling doubles prompt complexity and degrades both languages.
  **Mitigation:** One language-detection node feeding a single generation prompt, rather than parallel per-language paths. Phase 6 tests both.
- **Risk:** LangGraph learning curve consumes Sprint 2.
  **Mitigation:** Ship the thin vertical slice first — search intent only, end-to-end — then add intents. `docs/guide/chapter-04.md` (1,392 lines on LangGraph) is already vendored in the repo and is the fastest available reference.
- **Risk:** Per-turn LLM cost scales badly with conversation length.
  **Mitigation:** Bound history; summarise older turns rather than resending them.
