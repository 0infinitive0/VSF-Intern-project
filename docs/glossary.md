# Glossary

Domain and project-specific terms used across the codebase and docs. Bilingual where the
code mixes languages.

## Product / domain

| Term | Meaning |
|---|---|
| **V-OTA / VP-OTA / VSF Trip Planner** | The product. A multi-turn AI trip-planning chat for Vietnamese travellers. `app_name` in config is `VP-OTA`. |
| **OTA** | Online Travel Agency — here specifically Booking.com and Agoda, the two hotel data sources. |
| **BRD** | Business Requirements Document (`docs/brd/`). `BR-xx` = a numbered business requirement; `BO-xx` = a business objective with a measurable threshold. |
| **Destination / điểm đến** | A city/region (`destinations` table). Resolved from a user's free text via `name` + `aliases`. |
| **Itinerary / lịch trình** | A day-by-day plan (`itineraries` + `itinerary_items`). `Draft` until finalized, then `Finalized` (immutable). |
| **Day theme / chủ đề ngày** | `{day_number, title, query}` — an LLM-generated semantic query for one day's activities. Stored in `itineraries.day_themes`. |
| **Hotel hold / giữ chỗ / room hold** | A temporary `RESERVED` booking with a 15-minute TTL (`bookings.expires_at`). Not a confirmed booking. |
| **Happy path / happy case** | The end-to-end scenario where everything succeeds — documented in `chatbot-capabilities-and-happy-path-vi.md`. |
| **Tier 1 cache / itinerary reuse** | Reusing a finalized itinerary as a template when a new trip's BGE-M3 fingerprint matches it > 88%. |

## The agent / LangGraph

| Term | Meaning |
|---|---|
| **Graph / orchestrator** | The 14-node LangGraph `StateGraph` (`backend/src/agents/graph/`). The **only** control plane a chat turn runs through. |
| **Turn / lượt** | One user message → one assembled `PlannerChatResponse`. |
| **`process_chat_turn`** | The **deleted** pre-graph routing cascade. Any doc/comment describing it or `src/services/chat_session.py` is historical. |
| **Patch pipeline** | The 6 nodes that run on every turn: `load_context → scope_guard → extract_patch → validate_patch → apply_patch → ask_slot`. |
| **Patch** | A list of `{path, operation, value}` changes the LLM proposes from the user message (`operation` ∈ `set`/`unset`/`append`/`remove`). |
| **`travel_state` / `TravelState`** | The validated business state (a slot map). Round-trips through `from_dict`/`to_dict` every turn and **silently drops any key outside `ALLOWED_PATHS`** — which is why `trip_data` is a separate top-level key. |
| **`TravelGraphState`** | The execution-level state (`TypedDict`): messages, patch working data, supervisor bookkeeping, `trip_data`, injected keys. |
| **`ALLOWED_PATHS`** | The frozenset of dotted state paths a patch may touch (`domain/travel_state.py`). A write outside it is rejected, not coerced. |
| **Slot** | A required piece of intake (`destination`, `people`, `dates.start`, `dates.end`, `budget.target`). `ask_slot` is the sole writer of `missing_slots`. |
| **Supervisor** | The node that delegates to one worker per iteration. ~90% code-decided (`detect_impact` → `WORKFLOW_TO_WORKER`); LLM only for multi-workflow / recovery. |
| **Worker** | `hotel_node`, `itinerary_node`, `booking_node`, `qa_node` — the nodes that do the actual work. `WORKER_ORDER` fixes their sequence (`hotel_node` first — it anchors the itinerary). |
| **`qa_node`** | Read-only Q&A. A compiled **subgraph** that structurally cannot reach `travel_state`/`trip_data` — isolation by schema, not by check. |
| **`rebuild_day`** | A compiled subgraph that rebuilds one itinerary day; declares its own `MemorySaver`. |
| **Node contract / `enforce_contract`** | Per-worker declaration of the state paths it may read/write and whether it owes a reply. Violations raise (`strict`, CI) or log (`log`, production). |
| **`respond`** | The response **assembler** — builds `PlannerChatResponse` from state. It does **not** generate language; replies with data come from deterministic templates. |
| **`derive_stage`** | Function in `response_payload.py` that computes the API `stage` field from graph state (shared with `/restore`). |
| **`stage`** | API field: `intake` \| `hotel_options` \| `planned` \| `modified` \| `finalized` \| `error`. Derived, not routed. |
| **Checkpointer** | LangGraph's per-session state store. `MemorySaver` for CLI/tests, `PostgresSaver` in the FastAPI server (`thread_id = session_id`). |
| **`interrupt()` / resume** | LangGraph pause point — e.g. `hotel_node` asking once to disambiguate a search center. |
| **Intake QA** | `intake_qa` node — answers a genuine question asked *while* a slot is still missing, so the pending slot question isn't blindly re-asked. |
| **Grounding** | Resolving LLM output against real DB rows before use. An unmatched destination guess is discarded, not trusted. |
| **`_IMPOSSIBLE`** | The map of workers that cannot run in a given state. `booking_node` is unconditionally impossible — chat never books. |

## Search / RAG

| Term | Meaning |
|---|---|
| **`bge-m3`** | The embedding model. 1024-dim, multilingual. **Locked** — only the provider (`EMBEDDING_PROVIDER`: Cloudflare default, or Ollama) is swappable, never the model. |
| **`match_hotels_with_rooms` / `match_attractions` / `match_itineraries`** | Supabase pgvector RPCs doing similarity search + hard filters. Default thresholds: hotels 0.35, attractions 0.40, itinerary reuse 0.88. |
| **Hydration** | After a vector search returns ranked IDs, a second relational read fetches the full row (coordinates, hours, price…) needed for scheduling. Candidates without a UUID/name/coordinates are rejected. |
| **pgvector** | Postgres vector extension — used for the `itineraries.embedding` column and the `match_*` RPCs. |
| **Qdrant** | Dedicated vector store for `hotels_vector` / `attractions_vector` / `rooms_vector` collections (populated by the Airflow pipeline). Addressed by `QDRANT_URL`. |
| **Fingerprint** | A text string built from an `ItineraryReuseQuery`, embedded with BGE-M3, matched against finalized itineraries for Tier-1 reuse. |
| **Scheduler / `trip_scheduler.py`** | Pure-Python deterministic engine: scores candidates, assigns time blocks, applies distance/hours/meal/rest rules. No LLM. |
| **`PlaceCandidate`** | A hydrated venue record the scheduler consumes. |
| **`item_kind`** | A schedule slot's role: `breakfast` / `attraction` / `lunch` / `rest` / `coffee` / `dinner` / `evening`. Distinct from `reference_type` (which table the item points at). |

## Booking / payment

| Term | Meaning |
|---|---|
| **`temporary_user_ref`** | A UUID in the browser's `localStorage` identifying a guest for booking — no login required. |
| **`guest_ref`** | Same concept, in graph/service code. |
| **IPN** | Instant Payment Notification — VNPay's server-to-server callback to `/api/v1/payments/vnpay/ipn`. **The only trusted confirmation** (the browser redirect is display-only). |
| **`vnp_TxnRef`** | VNPay transaction reference = `payment.id` with dashes removed. |
| **Booking status** | `PENDING` → `RESERVED` (hold) → `CONFIRMED` (after IPN) / `CANCELLED` / `EXPIRED`. |
| **Payment status** | `PENDING` → `PAID` (IPN only) / `FAILED` / `CANCELLED`. |
| **Finalize gate** | `POST /chat/{id}/finalize` returns `409` unless the session has a `CONFIRMED` booking. |
| **Brevo** | The transactional-email provider (switched from Resend on 2026-08-26). Sends the booking-confirmation email after IPN. |

## Infra / ops

| Term | Meaning |
|---|---|
| **Caddy** | The reverse proxy (auto-HTTPS) in front of the frontend; `DOMAIN` from `CADDY_DOMAIN`. |
| **`Caddyfile.swagger-debug`** | Alternate Caddy config that also proxies `/docs`, `/redoc`, `/openapi.json`. Applied only when `deploy.yml` runs with `expose_swagger=true`. |
| **`EXPOSE_SWAGGER`** | GitHub Actions variable / dispatch input that toggles the swagger-debug Caddyfile for one deploy. |
| **`AUTH_REQUIRED`** | Flag: when `false` (default), requests with no/invalid token proceed as anonymous; when `true`, they get `401`. A valid token is always honored either way. |
| **`CONTRACT_ENFORCEMENT_MODE`** | `strict` (raise, dev/CI) vs `log` (log + continue, production) for node-contract violations. |
| **`airflow_net`** | External Docker network shared between the app's compose stack and the separate Airflow stack. |
| **BTC** | *Ban Tổ Chức* — the competition organizers (context for `AI_LOG_*` / `LANGCHAIN_*` "AI Logs" deliverable). |
| **PoC** | Proof of Concept — the intended scope; not production/commercial (see BRD § Scope). |
