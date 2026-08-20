---
phase: 4
title: "Widen context capture"
status: pending
priority: P1
effort: "0.5d"
dependencies: [2]
---

# Phase 4: Widen context capture

## Overview

`context_recorder` was built on a fact that stopped being true. Extend it to cover the vector
search paths that now bypass `_execute_rpc`, before the new baseline bakes the blind spot in.

## Problem

The original harness plan recorded, as a verified established fact:

> Every Supabase vector search funnels through one function: `supabase_search._execute_rpc`
> — this is the single interception point for capturing retrieved contexts during an e2e turn.

That was true on 2026-08-07. It is not true on 2026-08-20. `itinerary_store.py:163` calls
`self._client.rpc("match_itineraries", params)` directly, with `query_embedding`,
`match_threshold` and `match_count` — an unambiguous vector search, added by the
itinerary-template reuse feature (`b288843`), completely invisible to a monkeypatch on
`_execute_rpc`.

The consequence is quiet and bad: a turn that grounds its answer in a reused itinerary template
has that context recorded as *absent*. Faithfulness is then judged against contexts the model
did not actually work from — the answer looks unfaithful when it may be perfectly grounded, or
worse, a genuine hallucination hides in the gap.

## Requirements

- Functional: contexts retrieved via `match_itineraries` are captured for the turn that
  retrieved them.
- Functional: capture stays scoped to a single turn — no leakage across turns or conversations.
- Non-functional: no production module changes. The harness observes from outside, as the
  original plan required.
- Non-functional: a future bypass should be noticed, not silently tolerated.

## Architecture

Two options, and the second is the one worth building.

**Option A — patch each call site.** Add a second monkeypatch for
`itinerary_store`'s client. Works, and rots exactly the same way: the next feature that opens a
new RPC path is invisible again, and nothing tells us.

**Option B — patch one layer down, at the Supabase client.** Every path in the table below
bottoms out at `client.rpc(name, params).execute()`. Wrapping `rpc` on the client returned by
`get_supabase_client()` catches all of them, present and future, with one interception point.
Filter by RPC name to keep only vector searches.

Known `.rpc(` call sites today:

| Location | RPC | Vector search? |
|---|---|---|
| `supabase_search.py:109` (`_execute_rpc`) | `match_hotels_with_rooms`, `match_attractions` | yes |
| `itinerary_store.py:163` | `match_itineraries` | **yes — currently missed** |
| `itinerary_store.py:303,332,346,376` | writes / `finalize_itinerary` | no |
| `session_store.py:374` | session write | no |
| `booking_service.py:31` | booking | no |
| `place_details.py:84` | id lookup | no |

Option B restores the "single interception point" property the original plan valued, one layer
lower than it originally sat. Prefer an explicit allow-list of `match_*` RPCs over a
deny-list — a new write RPC silently entering the recorded context set is worse than a new
search RPC being briefly missed.

**Make the assumption self-checking.** The reason this went unnoticed for weeks is that nothing
asserted it. Add a test that enumerates `.rpc(` call sites across `backend/src/` and fails when
an unrecognised RPC name appears, so the next new retrieval path shows up as a red test rather
than a silently wrong faithfulness score.

## Related Code Files

- Modify: `eval/harness/context_recorder.py`
- Create: `backend/tests/test_rpc_call_sites_known.py` (or the eval-side equivalent)
- Read only: `backend/src/services/itinerary_store.py`, `backend/src/services/supabase_search.py`

## Implementation Steps

1. Re-enumerate `.rpc(` call sites; confirm the table above is still complete at implementation
   time rather than trusting it.
2. Move interception to the client returned by `get_supabase_client()`, keeping an allow-list of
   `match_*` RPC names.
3. Confirm `itinerary_store` and `supabase_search` share that client instance — if
   `itinerary_store` builds its own, patch its accessor too and say so in a comment.
4. Verify capture is per-turn and cleaned up afterwards.
5. Add the call-site guard test.
6. Replay one conversation that reaches itinerary reuse; confirm `match_itineraries` contexts
   appear in the recorded set.

## Success Criteria

- [ ] A conversation reaching itinerary reuse records `match_itineraries` contexts.
- [ ] Hotel and attraction capture behave exactly as before (no regression in Layer 2 contexts).
- [ ] Non-search RPCs (`finalize_itinerary`, session writes, bookings) are **not** captured.
- [ ] Contexts do not leak between turns or conversations.
- [ ] The call-site guard test fails when a new unrecognised RPC name is introduced.
- [ ] No file under `backend/src/` modified.

## Risk Assessment

**`itinerary_store` may not share the client.** Step 3 checks rather than assumes. If it holds
its own client, Option B needs a second patch point — still better than Option A, because the
interception is per-client rather than per-call-site.

**Over-broad capture.** Recording a write RPC's rows as retrieved context would corrupt
faithfulness scoring in the opposite direction. Hence the allow-list, and an explicit success
criterion asserting the negative.

**Ordering.** This must land before the phase 5 baseline run. Widening capture after the
baseline means the next run moves for harness reasons and looks like a regression — the plan's
own risk table calls this out.
