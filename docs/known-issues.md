# Known Issues & Technical Debt

A running list of known defects and deliberate compromises, so nothing is rediscovered
as a surprise. Architectural rationale lives in
[`../ARCHITECTURE.md`](../ARCHITECTURE.md) § Known debt and
[`architecture/langgraph_orchestrator_vi.md`](architecture/langgraph_orchestrator_vi.md)
§ Nợ kỹ thuật; this file is the flat, actionable index.

Legend: **Bug** = wrong/broken behavior · **Debt** = works but compromised · **Gap** = missing thing.

---

## Broken

| # | Kind | Item | Detail | Suggested fix |
|---|---|---|---|---|
| 1 | Bug | **Terminal CLI is broken** | `backend/src/cli/terminal_chat.py:12` imports `process_chat_turn` from `src.agents.session`, deleted in the graph cutover → `ImportError` on `python -m scripts.poc_trip_planner`. Nothing imports it, so nothing failed loudly. | Port the CLI onto `build_graph` / `turn_runner`, or delete it. Product call. |
| 2 | Bug | **Raw exception text can leak on `POST /planner_chat`** | Non-stream path wraps errors as `HTTPException(500, detail=str(e))` historically; the stream path already sanitizes. Confirm current state and make both return a generic body. | Generic 5xx body on the non-stream route. |

## Debt (works, compromised)

| # | Kind | Item | Detail | Suggested fix |
|---|---|---|---|---|
| 3 | Debt | **`POST /hotels/change` uses NL-string signalling** | Drives the turn by injecting the string `"đổi khách sạn"` into the graph for an extractor to re-interpret, instead of a deterministic state signal like `POST /hotels/select` (`extra_state={"selected_hotel_id": …}`). | Add a signal `hotel_node` reads directly. |
| 4 | Debt | **No reducer on `pending_tasks` / `task_results`** | Overwrite-on-write is only safe because delegation is strictly sequential. The first parallel fan-out (`Send` API / concurrent subgraphs) will silently lose one branch's result. | Add `operator.add` (or a merge) reducer **before** any node runs more than once per super-step. |
| 5 | Debt | **Legacy fields on `TripSession`** | `intake_state`, `hotel_pref_state`, `pending_hotel_selection`, `session.trip_data` belong to the deleted plane. `routes.py` no longer reads them, but `agents/session.py`, `models/schemas.py`, `services/trip_planner.py`, `services/session_store.py`, some `agents/tools/*`, and the broken CLI still do. | Its own removal plan. |
| 6 | Debt | **Stale `process_chat_turn` mentions in docstrings** | In prose only: `api/streaming.py`, `agents/tools/*`, `agents/graph/__init__.py`. Harmless but misleading. | One sweep. |
| 7 | Debt | **`pending_clarify_day` can outlive its turn** | On paths that skip `extract_patch` (blocked turn, hotel pick, interrupt resume). Documented in `extract_patch`'s docstring. | — |
| 8 | Debt | **`backend/.env.example` has pre-reorg leftovers** | `DATABASE_URL` (SQLite/Railway), `CHROMA_PERSIST_DIR`, `PINECONE_*`, Railway deploy hints — none read by `config.py`. Also sets `LLM_PROVIDER=ollama` under a "Default: Cloudflare" heading. | Prune to match `config.py`; see [`setup/environment-variables.md`](setup/environment-variables.md). |
| 9 | Debt | **Some migrations applied directly on Supabase, never committed** | e.g. `20260814_move_available_room_count_to_rooms.sql` — referenced by `test_room_availability_schema.py` but absent from `backend/scripts/migrations/`. The folder is not a complete history. | Export the live schema and reconcile. |

## Gaps (missing)

| # | Kind | Item | Detail |
|---|---|---|---|
| 10 | Gap | **Out-of-scope guardrail not built** | `guardrails/scope.py` (refuse math/code/flight-booking questions) was marked done in an old plan but never implemented. `scope_guard` passes those through to the LLM. Only jailbreak detection runs. |
| 11 | Gap | **No cron to release expired holds** | Expired `RESERVED` bookings only stop mattering when `expires_at` passes; nothing sweeps them to `EXPIRED`. Manual: `POST /api/v1/admin/orders/holds/release-expired`. |
| 12 | Gap | **No "unlock day"** | `itinerary_node` has `lock_days` (cumulative) but no inverse. |
| 13 | Gap | **No monitoring / alerting** | Only `GET /health` + container logs (no central store, no retention, no uptime check, no error alerting, no disk alert). See [`ops/deployment-runbook.md`](ops/deployment-runbook.md) § 8. |
| 14 | Gap | **No `LICENSE` file** | `README.md` says "MIT" but there is no `LICENSE` at the repo root. Needs a copyright holder + year to add. |
| 15 | Gap | **No KPI / go-no-go report (BR-09)** | The eval harness produces retrieval + e2e numbers; no summary report or recommendation has been written. |
| 16 | Gap | **`turn cancellation` not shipped** | Plan `260806-1602` Phase 4: `POST /chat/{id}/cancel`, a `cancelled` SSE frame, the "Dừng" stop control. Every stream currently runs to `final` or `error`. |

## Notes on scope (deliberate, not debt)

- `booking_node` stays registered and unconditionally impossible — booking ships as a
  REST flow, the node is kept in case chat-driven booking is added later.
- Straight-line (Haversine) travel time in the scheduler is intentionally approximate;
  add a routing provider only if street-network ETA becomes a requirement.
- Hotels physically duplicated across Agoda + Booking are kept as **two rows** on
  purpose (different prices/policies); `hotel_identity_groups`/`_members` de-dupe for
  RAG without merging rows — and that persistence step is not yet wired into
  `load_hotels_to_db()`.
