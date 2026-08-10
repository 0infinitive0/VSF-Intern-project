---
title: "Phase 6 verification — streaming chat messages"
plan: 260806-1602-streaming-chat-messages
date: 2026-08-07
---

# Phase 6 verification report

Scope: Phases 1, 2, 3, 5, 6 of `260806-1602-streaming-chat-messages`. Phase 4
(cancellation with rollback) stays paused per the prior user decision recorded
in `plan.md` — not attempted, not claimed.

## Critical bugs found and fixed during this pass

The plan's uncommitted WIP (Phases 1-2 mostly done, Phase 3 partially wired)
had two bugs that would have broken the feature in production. Both are fixed
and covered by new regression tests.

1. **`process_chat_turn` passed `stream=stream` to `_run_intake`/`_run_chat_agent`,
   which didn't accept it.** `TypeError` on every single chat turn, including
   the plain `POST /planner_chat` — the whole app was down. Fixed by adding
   `stream: bool = False` to both signatures and threading it through.
2. **The stream endpoint never actually passed `stream=True`** to
   `process_chat_turn` (`routes.py`'s `_run_turn()`). `phase`/`final` events
   worked, but **zero `delta` events would ever have shipped** — the P1 token-
   streaming goal would have silently not worked, with all tests for it
   passing (because they exercised `_run_chat_agent(stream=True)` directly,
   never through the real endpoint). Caught by the new
   `test_stream_post_parity.py::test_parity_agent_chat_branch`, which drives
   the real endpoint end-to-end. Fixed with a one-line addition.

A third, narrower bug in the already-existing `_DeltaGate`: the gate correctly
decided to mute an attempt whose content looked like tool-call JSON or a
`SYSTEM ERROR:` prefix, but `close()` re-entered `_flush()` and — because the
early-return guard only fired on the branch that *made* the decision, not on
every call — flushed the muted text anyway on the second call. Caught by the
new `test_delta_gate.py` unit suite. This is the exact leak the plan's Phase 3
architecture doc is built around preventing.

## Independent code review (post-implementation)

A `code-reviewer` subagent reviewed the full diff after the above three fixes
landed and before this report was first finalized. It found four more
blocking/high-severity bugs, all verified (three empirically) and fixed
before shipping:

- **B1 — `stream_mode` was unconditional, not gated on `stream`.** Including
  `"messages"` in `stream_mode` isn't a free extra channel: LangGraph attaches
  a `StreamMessagesHandler` callback to drive it, and
  `BaseChatModel._should_stream()` treats ANY attached streaming callback
  handler as reason to call the provider's streaming API instead of its plain
  `.generate()` — verified with a recording fake model: `stream_mode="values"`
  hit `_generate`, `stream_mode=["values","messages"]` hit `_stream`, nothing
  else different. Every turn, including plain `POST /planner_chat`, would have
  silently started issuing streaming requests to Ollama/OpenRouter/Cloudflare
  Workers AI, changing how tool-call arguments get reassembled provider-side.
  Fixed: `stream_mode = ["values", "messages"] if stream else "values"`, with
  the consuming loop normalizing both shapes.
- **B3 — `_DeltaGate`'s mute decision fired on raw (including whitespace)
  buffer length, not real content length.** Two reproduced leaks: a
  whitespace-only first chunk reaching `PROBE_CHARS` in raw length decided
  "open" on zero real content, so a JSON chunk fed right after streamed
  straight through; a chunk boundary landing exactly at `PROBE_CHARS` raw
  chars could cut `"SYSTEM ERROR:"` in half (no colon yet), reading as
  ordinary prose. Fixed: the decision now waits for `PROBE_CHARS` of
  **stripped** content before firing. Both cases are now regression tests.
- **B2 — delta could diverge from `final.reply` in multi-tool-call turns,
  with no `reset`.** The agent can emit prose before deciding to call a tool
  ("Let me check...") — that prose streams as delta (empty tool_calls while
  generating), then the SAME per-attempt gate kept accumulating through the
  tool round into the real final answer, so client-visible delta text was a
  superset of `final.reply`. Fixed: when the "values" branch sees an AI
  message with `tool_calls` and the gate had already flushed something, emit
  `reset` and replace it with a fresh `_DeltaGate()` for whatever follows the
  tool round. Also wired `reset` into the `tool_output_response` branch
  (defense in depth). New regression test drives `_run_chat_agent` through a
  chatter → tool-call → real-answer sequence and asserts deltas after the
  last `reset` equal `final.reply` exactly.
- **B4 — `_poll` drew from the same default asyncio executor as `_run_turn`.**
  The original polling loop called `run_in_executor(None, emitter.get, ...)`
  roughly once a second for the whole turn — on top of the one executor
  thread `_run_turn` already holds — competing for the SAME
  `ThreadPoolExecutor(max_workers=min(32, cpu_count+4))` (6 threads on this
  project's t3.micro EC2 target, per prior memory). A live 10-concurrent-
  stream test on this dev machine (32-worker pool) showed no queuing, which
  masked the risk — the constraint only bites on a small pool. Fixed:
  `TurnEmitter` now delivers via `loop.call_soon_threadsafe` onto an
  `asyncio.Queue`, costing zero executor threads for polling.

Two frontend bugs in `stream-client.ts`, both about the retry-safety boundary:

- **H2 — `firstFrameTimeoutMs` never actually aborted anything.** The timer
  called `controller.abort()`, but `fetch()` was given the OUTER caller's
  `signal`, not `controller.signal` — aborting a signal fetch was never
  passed does nothing to a pending `reader.read()`. Fixed: one controller now
  drives both the outer abort and the timeout, and is what's actually passed
  to `fetch()`.
- **H3 — "zero frames received" was wrongly treated as "safe to retry via
  POST."** `routes.py`'s `planner_chat_stream` submits the turn to its worker
  pool BEFORE constructing the `StreamingResponse` it returns, so a 200
  `text/event-stream` response means the turn is already running
  server-side — whether or not the client subsequently parsed any frame out
  of the body. The old code threw `StreamUnsupported` (safe-to-resend) for a
  stream that closed with zero frames even after a valid response; that risks
  a double-send (two LLM calls, two session mutations, possibly two DB
  writes). Fixed: `StreamUnsupported` is now thrown ONLY for pre-response
  failures (`fetch()` rejecting, non-2xx, wrong content-type); every failure
  after a valid response — including the (now-working) first-frame timeout —
  throws a plain `Error`.

Also fixed at Medium/Low severity: nginx's `proxy_buffering off` etc. were
scoped to the whole `/api/` location instead of just the streaming endpoint
(re-verified live against an isolated nginx container after narrowing to an
exact-match `location`); `format_sse` now degrades a non-JSON-serializable
frame to a dropped-and-logged frame instead of silently ending the generator
with no terminal frame; a `msg.content` type guard (H1 — some providers can
hand back a list of content blocks, not a plain str) prevents a stream-only
turn failure; dead `_DeltaGate.discard()`/`.discarded`/`.full_text()` API
(zero production call sites, only phantom tests) removed.

**Not fixed, accepted as-is:** M2 (the API-layer `streaming.py` is imported
into the service/agent layers — a layering inversion, no cycle, not a
correctness issue) and the `turn-phases.tsx` key-collision Low finding
(`at` carries sub-second float precision in practice, verified in the live
proxy traces below — collision risk is theoretical).

## Test suite status

```
pytest backend/tests/test_api backend/tests/test_agents \
  backend/tests/test_chat_turn_characterization.py \
  backend/tests/test_intake_form_characterization.py
```
134 passed, 20 failed (final count, after the code-review fixes above added
2 more regression tests) — all 20 failures independently confirmed present on
a clean `main` checkout (unrelated pre-existing issues: a `build_supervisor`
rename in `src.agents.supervisor` that `test_supervisor.py` hasn't caught up
to, a few `to_hotel_options_payload`/`IntakeStatus` fixture mismatches, one
missing migration file, three intake-form characterization gaps). **None
introduced by this work; none touched to force green**, per the plan's own
rule.

New test files added this pass: `test_delta_gate.py` (15 tests, `_DeltaGate`
in isolation, including the B3 leak repros), `test_stream_post_parity.py` (4
tests, one per TurnResult branch), plus fixes to the existing
`test_chat_stream.py` / `test_phase_events.py` / `test_chat_turn_characterization.py`
mocks so they correctly react to `stream_mode` being `"values"` (bare dicts)
when `stream=False` and `["values","messages"]` (tuples) when `stream=True` —
per the B1 fix, these are no longer the same shape regardless of `stream`.
`test_phase_events.py` also gained a regression test for B2 (chatter →
tool-call → real-answer sequence, asserting deltas after the last `reset`
equal `final.reply`).

Frontend: `npm run test` — 75/75 passed (includes new `stream-client.test.ts`
for the SSE frame parser AND the `sendMessageStream` retry-safety boundary —
H2/H3 — plus `phase-labels.test.ts` for the i18n key coverage). `npm run
typecheck`, `npm run lint`, `npm run build` all clean.

## `final` / POST parity (invariant #1)

`test_stream_post_parity.py` runs the real `process_chat_turn` (only
`session.tools` / `session.agent` / the LLM supervisor are stubbed — no
Supabase/Ollama) through both endpoints on identical twin sessions, across all
four TurnResult-producing branches:

| Branch | `final` == POST body | Notes |
|---|---|---|
| intake | ✅ | no `delta` |
| recommend_hotels | ✅ | no `delta` |
| agent chat (`agent_stream`) | ✅ | **also** asserts `"".join(deltas) == final.reply` |
| finalize | ✅ | no `delta` |

## delta == final.reply (invariant #2)

Covered at two levels: `test_delta_gate.py` proves the gate's own invariant
(`concat(fed) == concat(emitted)` when open, empty when muted) in isolation;
`test_stream_post_parity.py::test_parity_agent_chat_branch` proves it through
the real HTTP endpoint end-to-end on the one branch that streams tokens.

## Proxy verification (manual, `curl -N`, timestamped)

Caddy staging was not reachable from this environment — **not verified**,
per the plan's own instruction to say so rather than assume it (nginx/Caddy
default docs are exactly what the plan warns not to trust).

The other two layers were verified live, against the real code on this
branch, driving actual Supabase/Ollama-backed turns (not mocked):

**Direct backend** (`localhost:8001`, baseline):
```
open            t=0.000s
phase received  t=0.006s
phase routing   t=0.014s
phase route_decided t=1.974s   (LLM supervisor call)
phase intake_check  t=1.987s
final           t=4.374s
```

**Vite dev proxy** (own standalone Vite instance, `DEV_PROXY_TARGET` pointed
at the same backend — did not touch the user's running dev server):
```
open            t=0.000s
phase received  t=0.005s
phase routing   t=0.012s
phase route_decided t=8.537s
phase intake_check  t=8.545s
final           t=11.421s
```

**nginx** (isolated `nginx:alpine` container running the actual
`frontend/nginx.conf` from this branch, `proxy_pass` pointed at the same
verification backend via `host.docker.internal` — a standalone container, NOT
the user's running `vsf-intern-project-frontend-1`, which was left untouched
the whole time since it has this branch's code baked into an image, not
mounted, and rebuilding it would have restarted the user's active session):
```
open            t=0.000s
phase received  t=0.006s
phase routing   t=0.019s
phase route_decided t=3.030s
phase intake_check  t=3.041s
final           t=4.575s
```

All three: frames arrive incrementally (`open` immediately, `final` seconds
later), never dumped as one block — no proxy layer in reach is buffering.
Gap between first phase frame and `final` exceeds 1s on every run (success
criterion from phase-01.md), by a wide margin.

**nginx re-verified after the M1 fix** (narrowing `proxy_buffering off` etc.
from the whole `/api/` location to an exact-match `location = /api/v1/planner_chat/stream`,
so every other API call gets nginx's normal buffering back): re-ran against a
fresh isolated container with the updated config — normal API calls
(`POST /chat/session`) still route and respond correctly through the
broader `location /api/`, and the streaming endpoint (routed through the
more specific exact-match location, which nginx always prefers over a
prefix match) is still fully unbuffered:
```
open            t=0.000s
phase received  t=0.005s
phase routing   t=0.019s
phase route_decided t=2.328s
phase intake_check  t=2.335s
final           t=6.267s
```

**Mock server** (`frontend/mock/server.js`, isolated `MOCK_PORT=8099`): all 4
scripted turns (intake ×2, hotel-options with delay, plan with delay) emit
their `phase` scripts then `final`; the `:stream` dev hook (forced agent-chat
turn) emits 4 `phase` events, 39 `delta` chunks, then `final` — confirms the
mock's SSE branch matches contract shape end-to-end.

## Performance numbers

| Measure | Result | Threshold | Verdict |
|---|---|---|---|
| `emit_phase` cost, unbound (POST path) | 0.062 µs/call | — | negligible |
| `emit_phase` cost, bound (stream path) | 0.433 µs/call | >1% of turn cost flagged | ~10 events/turn × 0.4µs ≈ 4µs against a multi-second turn — no optimization needed |
| 10 concurrent streams, first-byte latency (pre-B4-fix code) | 11-92ms each | queued if serialized (~4s stagger) | not queued on THIS dev machine's 32-worker default executor pool — but this measurement predates the B4 fix below and doesn't transfer to a small pool |
| 10 concurrent streams, wall-clock (pre-B4-fix code) | 5.4s (vs. ~43s if serial) | — | confirms real parallelism at 32 workers |
| `deepcopy(session.state)` snapshot cost | not measured | >50ms flagged | **deferred** — this number only matters for Phase 4's rollback snapshot, which is paused; re-measure when Phase 4 resumes |

**B4 correction (post-review):** the two rows above were measured BEFORE the
code review found that `_poll`'s `run_in_executor` calls drew from the SAME
default asyncio executor as `_run_turn` — invisible at 32 workers (this dev
machine), but a real risk at the ~6-worker pool a 2-vCPU deployment target
gets by default. Not re-measured after the fix (which removes `_poll`'s
executor draw entirely via `asyncio.Queue` + `call_soon_threadsafe`) — the
mechanism is a standard, well-understood pattern and doesn't need a live
number to justify keeping it; see the code-review section above for details.

## End-to-end scenarios

Ran live against real backend services (not the mock server): intake turn
(destination question → next question, phase list grows, no delta) and the
three proxy-layer traces above, which double as an intake-branch e2e run.
**Not run this pass:** the hotel-search, finalize, and free-chat scenarios
end-to-end against real services (would need a full multi-turn conversation
walked by hand); those branches ARE covered by the mocked
`test_stream_post_parity.py` branches and phase-02/03's own test suites, just
not manually walked end-to-end in `vi`/`en` per phase-06's 7-scenario list.
Scenarios 5-6 (cancel mid-turn, cancel after point-of-no-return) don't apply —
Phase 4 is paused, there is no cancel endpoint to test.

## Docs updated

- `docs/chat_api_contract.md` — added an explicit "Not shipped" note for
  cancellation so a reader doesn't infer a `cancelled` event or cancel
  endpoint exists.
- `plans/260805-1022-claude-design-ui-integration/plan.md` item #14 — marked
  shipped (07/08/2026), pointing at this plan.
- `plans/260723-1015-v-ota-poc-master-roadmap/phase-03-bilingual-conversational-core.md`
  and `phase-05-web-chat-ui.md` — both pending streaming criteria checked off.

## Open items / not done

- Caddy staging proxy behavior — unverified (no reachable staging environment
  from this session).
- `deepcopy(session.state)` timing — deferred to Phase 4 (paused).
- Manual `en` pass of the 7 end-to-end scenarios — not run (automated coverage
  exists for the underlying branches; only the manual walk-through is
  outstanding).
- Phase 4 (cancellation with rollback) — intentionally out of scope, unchanged
  from the prior paused state.
