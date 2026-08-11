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
| select_hotel | 0.034 | 0.170 |
| finalize | 0.016 | 0.022 |
| intake | 0.029 | 0.035 |
| chat | 0.156 | 0.625 |
