# Phase 2 turn-latency baseline (2026-08-02)

Measured with the LLM/Supabase boundary fully stubbed (see this file's
fixtures) — this is process_chat_turn's own Python overhead, NOT
end-to-end latency including a live model call. It exists so Phase 6 can
re-measure the same way and compare like-for-like; it is not a
production latency figure.

Conditions: warm interpreter (run inside the full pytest session, not
cold-started), 20 samples per route, local dev machine, no network.

| Route | p50 (ms) | p95 (ms) |
|---|---|---|
| select_hotel | 0.040 | 0.219 |
| finalize | 0.016 | 0.028 |
| intake | 0.089 | 0.216 |
| chat | 0.362 | 0.729 |
