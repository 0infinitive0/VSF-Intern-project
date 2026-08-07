# Chat API Contract

Frozen 2026-07-31 in Phase 1 of `plans/260729-1637-trip-planner-chat-ui-and-agents-backend/`
so Phase 3 (backend) and Phase 4 (React frontend) can build against it independently.

**Status of this document relative to the shipped code:** the `POST /api/v1/planner_chat` endpoint was shipped in Phase 1 and extended in Phase 3. The other endpoints are built in Phase 3. 

## Endpoints Overview

| Method | Path | Body / Query | Returns | Status |
|---|---|---|---|---|
| `POST` | `/api/v1/chat/session` | — | `{session_id, created_at}` | Phase 3 |
| `GET` | `/api/v1/chat/{session_id}/plan` | — | `{trip_plan}` or 404 | Phase 3 (Alias: `/session/{session_id}/state`) |
| `DELETE` | `/api/v1/chat/{session_id}` | — | `204` | Phase 3 |
| `POST` | `/api/v1/planner_chat` | `{message, session_id, language, stay_dates, min_price, max_price}` | `PlannerChatResponse` | Shipped (extended in Phase 3) |
| `POST` | `/api/v1/planner_chat/stream` | same as `/planner_chat` | `text/event-stream` (SSE) | Shipped (plan 260806-1602, Phase 1) |
| `POST` | `/api/v1/hotels/search` | `{session_id, load_more}` | `{hotels, has_more}` | Phase 3 |
| `POST` | `/api/v1/hotels/select` | `{session_id, hotel_id}` | `PlannerChatResponse` | Alias: `/chat/select_hotel` |
| `POST` | `/api/v1/itineraries/generate` | `{session_id, language}` | `{status, trip_plan}` | Phase 3 |
| `GET` | `/api/v1/search_attractions` | `?q=...&k=10` | `{status, results}` | Phase 3 |
| `GET` | `/api/v1/search_hotels` | `?q=...&k=10` | `{status, results}` | Phase 3 |
| `GET` | `/api/v1/hotels/{hotel_id}` | `?check_in=YYYY-MM-DD&check_out=YYYY-MM-DD` | `HotelDetail` | Phase 3 |
| `GET` | `/api/v1/attractions/{attraction_id}` | â€” | `AttractionDetail` | Phase 3 |
| `GET` | `/api/v1/chat/sessions` | â€” | `SessionSummary[]` | Phase 4, opt-in persistence |
| `GET` | `/api/v1/chat/{session_id}/restore` | â€” | `SessionRestore` | Phase 4, opt-in persistence |

`message` stays required with `min_length=1`, and `session_id` stays required on
`planner_chat`, so `tests/test_api/test_routes.py` passes unchanged (backwards
compatibility, per D10).

## Endpoint Details

### Session Lifecycle

#### `POST /chat/session`
Creates a new conversational trip planning session.
- **Request Body:** None
- **Response:**
  ```json
  {
    "session_id": "uuid-string",
    "created_at": "2024-03-20T10:00:00+00:00"
  }
  ```

#### `GET /chat/{session_id}/plan` (Alias: `/session/{session_id}/state`)
Retrieves the current state and trip plan for a given session. Used by the frontend on initial load/reload to restore context.
- **Request Body:** None
- **Response:**
  ```json
  {
    "trip_plan": {
      "status": "string",
      "hotel": { "name": "...", "id": "..." },
      "days": [],
      "adjustments": []
    }
  }
  ```
  Returns `404` if the session is not found.

#### `DELETE /chat/{session_id}`
Deletes an active session and drops it from the registry.
- **Request Body:** None
- **Response:** `204 No Content`

### Core Conversation (`POST /planner_chat`)

Submits a new chat message to the trip planner agent.

**Request Body:**
```json
{
  "session_id": "uuid-string",
  "message": "string (optional)",
  "language": "string (optional)",
  "stay_dates": {
    "start_date": "YYYY-MM-DD",
    "end_date": "YYYY-MM-DD"
  },
  "min_price": 0,
  "max_price": 2000000
}
```

**Response (`PlannerChatResponse`):**
```json
{
  "session_id": "uuid",
  "reply": "text reply, already formatted",
  "suggestions": [ { "label": "1. Muong Thanh", "value": "1" } ],
  "stage": "intake | hotel_options | planned | modified | finalized | error",
  "hotel_options": [
    { "index": 1, "id": "uuid", "name": "...", "star_rating": 4,
      "description": "...", "matched_rooms": ["..."] }
  ],
  "trip_plan": { "...null until a hotel is picked..." },
  "intake": { "destination": "...", "start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD", "people": "2", "min_price": 0, "max_price": 0, "missing": ["people"] },
  "requires_stay_dates": false
}
```

- `reply` and `suggestions` — shipped today (`src/models/schemas.py:49-57`). Unchanged
  meaning: `reply` is the formatted text reply; `suggestions` is a list of tappable
  quick-reply chips (`{label, value}`), built by `suggestions_for()`
  (`chat_session.py:67`). Empty means the turn wants free text.
- `stage`, `hotel_options`, `trip_plan`, `intake` — added in Phase 3. `stage` is
  **derived, not routed** (see section below). `hotel_options` is populated only when
  `stage="hotel_options"`.
- `session_id` — currently accepted unvalidated by the request and auto-creates a
  session if unknown (`routes.py:29-32`, tracked as a red-team finding, not fixed in
  this phase).

### Streaming Conversation (`POST /planner_chat/stream`)

Added by plan `260806-1602-streaming-chat-messages` (Phase 1). A parallel SSE channel
for the same chat turn — the plain `POST /planner_chat` above is kept **unchanged**
and remains the fallback when SSE is unavailable (e.g. a proxy strips/chokes
streaming). Both endpoints serve the identical payload: the stream's `final` frame is
the exact dict the POST endpoint serializes (both assemble via
`build_chat_response()` in `src/api/routes.py`; Phase 6 asserts byte-for-byte equality).

**Request Body:** identical to `/planner_chat`.

**Response:** `200`, `Content-Type: text/event-stream`, `Cache-Control: no-cache`,
`X-Accel-Buffering: no`, `Connection: keep-alive`. Unknown session → plain `404`
(not an SSE stream), exactly like the POST endpoint — clients treat that as "SSE
unsupported" and fall back to `POST /planner_chat`.

**Wire format** — one frame per event, frames separated by a blank line; lines
starting with `:` are comments (open probe / heartbeat) and must be ignored by
parsers. JSON is UTF-8 unescaped (`ensure_ascii=False` — Vietnamese text is not
ASCII-escaped):

```
: open

event: phase
data: {"key":"hotel_search","tool":"recommend_hotels","at":1754...}

event: delta
data: {"text":"Khách sạn này "}

event: reset
data: {"reason":"discarded_tool_call_json"}

event: final
data: {"session_id":"...","reply":"...","suggestions":[...],"stage":"hotel_options",
       "hotel_options":[...],"trip_plan":null,"intake":{...},"requires_stay_dates":false}

event: error
data: {"detail":"Đã xảy ra lỗi máy chủ. Vui lòng thử lại."}

: heartbeat
```

- `: open` — comment frame sent immediately, forcing proxies to flush headers.
- `: heartbeat` — comment frame every 15s of silence, guarding proxy idle timeouts.
- `phase` — real pipeline progress (see key table below). `key` is **opaque**:
  the backend never sends display text; the frontend owns i18n labels.
- `delta` — real LLM tokens, only on the `_run_chat_agent` branch (Phase 3).
  Clients must NOT assume every turn has deltas.
- `reset` — safety net telling the client to discard buffered delta text
  (an agent attempt was dropped after streaming had started) (Phase 3).
- `final` — terminal frame carrying the full `PlannerChatResponse` dict.
- `error` — terminal frame for turn failures; `detail` is sanitized, no internals.

**Invariants:**

- Every stream ends with EXACTLY ONE terminal frame: `final` or `error`. Never both,
  never zero (`emitter.close()` is in the worker's `finally`).
- `final.data` is the same dict `POST /planner_chat` serializes for the same
  scenario — no extra/missing/renamed fields.
- Concatenating all `delta.text` (after the most recent `reset`) equals
  `final.reply` on turns that streamed tokens. Asserted by tests, not hoped for.
- `delta` only appears on the `_run_chat_agent` branch.
- `phase.key` is an opaque key — no display text crosses the wire.

**`phase` key table** (every key = a real code position it is emitted at; nothing is
emitted on a schedule — if a branch doesn't pass through a position, the key does not
exist for that turn, and UIs must tolerate missing steps):

| `key` | Emitted at | Deterministic or LLM |
|---|---|---|
| `received` | start of the turn (stream endpoint worker, `routes.py`) | — |
| `routing` | immediately before `_decide_route` (`agents/session.py`) — only when the supervisor router is enabled | LLM supervisor |
| `route_decided` | after `_decide_route`, carries `route` | — |
| `compacting_history` | inside `_compact_history`, only when compaction actually runs (`agents/session.py`) | LLM |
| `intake_check` | entry of `_run_intake` (`agents/session.py`) | deterministic |
| `hotel_search` | before `tools.recommend_hotels.invoke` (`agents/session.py`) | DB + vector |
| `tool_start` / `tool_end` | agent event loop (`agents/session.py`), carries `tool` | — |
| `itinerary_build` | entry of `_generate_and_save_itinerary` (`services/trip_planner.py`) | LLM + scheduler |
| `routing_legs` | inside `recalculate_itinerary_routes` (`services/routing.py`), once before the day loop, carries `days` | HTTP routing |
| `persisting` | right before the first external DB write — inside BOTH `_persist_itinerary_metadata` (`services/trip_planner.py`) and `ItineraryStore.finalize_trip_data` (`services/itinerary_store.py`) | DB write |
| `generating` | first prose token of the agent (Phase 3) | LLM |

**Not shipped:** turn cancellation (`POST /chat/{session_id}/cancel`, a `cancelled`
terminal frame, and the "Dừng" stop control). This is plan `260806-1602`'s Phase 4,
paused after Phase 1-3/5/6 shipped. Every stream in this ship runs to one of the two
terminal frames documented above; there is no server-side way to interrupt one.

Observed key order follows the real call graph, not a schedule. Example: on the
hotel-selection build turn the order is `itinerary_build` → `persisting` →
`routing_legs`, because route recalculation runs INSIDE
`persist_itinerary_bundle` (`itinerary_store.py`) which sits between the
`persisting` key and the RPC write. (The plan's illustration `itinerary_build
→ routing_legs → persisting` assumed the opposite nesting; truthful emission
positions win, and `persisting` must stay right before the first external
write — that position is the Phase 4 point-of-no-return anchor.) Clients must
never rely on a fixed order beyond `received` first and the terminal frame last.

### Hotel Selection & Itinerary Flow

#### `POST /hotels/search`
Requests additional hotel recommendations for the current session (Pagination). Returns up to 5 new hotels that haven't been shown in the current session.

**Request Body:**
```json
{
  "session_id": "uuid-string",
  "load_more": true
}
```

**Response:**
```json
{
  "hotels": [
    {
      "id": "uuid",
      "index": 6,
      "name": "Hotel Name",
      "star_rating": 4,
      "average_nightly_price": 1200000,
      "description": "...",
      "matched_rooms": []
    }
  ],
  "has_more": true
}
```

#### `POST /hotels/select` (Alias: `/chat/select_hotel`)
Explicitly selects a hotel from the provided options. The AI engine registers the selection in the session state.

**Request Body:**
```json
{
  "session_id": "uuid-string",
  "hotel_id": "string (or index)"
}
```

**Response:** `PlannerChatResponse` (Same as `/planner_chat` response)

#### `POST /itineraries/generate`
Forces the generation of an itinerary based on the current session state. Call this after a hotel is selected if the itinerary isn't immediately attached to the hotel selection response.

**Request Body:**
```json
{
  "session_id": "uuid-string",
  "language": "string (optional)"
}
```

**Response:**
```json
{
  "status": "success",
  "trip_plan": {
    "hotel": {},
    "days": [
      {
        "day_number": 1,
        "theme": "string",
        "items": [
           { "activity": "string", "start_time": "08:00", "end_time": "12:00" }
        ]
      }
    ],
    "status": "Draft",
    "adjustments": []
  }
}
```

### Detail Lookups

#### `GET /hotels/{hotel_id}`

Returns one hotel, its rooms, and at most one `price` per room. `hotel_id` is a UUID;
malformed IDs return FastAPI validation `422`, unknown IDs return `404`, and database
failures return a generic `500`. This endpoint is sessionless and read-only.

`check_in` and `check_out` are optional ISO dates, but must be supplied together with
checkout after check-in. When supplied, `price` is a non-sold-out row matching exactly
that stay; otherwise it is the latest non-sold-out room price. `price: null` means no
matching price exists. The API never substitutes `hotels.lowest_price` for a room price.
The current `room_prices` schema has no package-details column, so
`rooms[].price.package_details` is currently `null`.

#### `GET /attractions/{attraction_id}`

Returns one attraction with nullable ticket prices preserved exactly: `0` means free and
`null` means unknown. `opening_time` and `closing_time` serialize as `HH:MM:SS` strings.

Live verification on 2026-08-06 found itinerary `reference_type` values only `Hotel`
and `Attraction` (765 sampled rows: 127 and 638 respectively). Therefore the two detail
routes cover all currently persisted itinerary references; there is no separate tour
reference type or endpoint requirement.

### Persisted Session History

Session persistence is opt-in through `SESSION_PERSISTENCE_ENABLED=true`. When disabled,
all existing session behavior remains in-memory and `GET /chat/sessions` returns an empty
list. When enabled, each completed turn stores the serializable business state in
`sessions.context_data`; persistence failures are logged and the in-memory chat turn still
completes.

The existing `chat_messages` table is not used for restoration because its current shape
only stores sender/content/timestamp and cannot preserve LangChain message metadata or the
frontend stage. Converted LangChain messages are instead stored under
`context_data.messages`. Runtime-only `remaining_steps`, agent/tool instances, and locks
are never persisted; rehydration constructs a fresh runtime session before attaching the
saved state.

#### `GET /chat/sessions`

Returns persisted sessions newest first. `title` is the first real user message when one
exists (otherwise `null`); the frontend owns any translated fallback. `status` is
`completed` when a trip exists and `draft` otherwise.

#### `GET /chat/{session_id}/restore`

Returns the same structured planning state used by `planner_chat`, plus the restored
`messages` stream. An in-memory miss rehydrates from `sessions` when persistence is
enabled; unknown sessions return `404`.

### Semantic Search Utility

These endpoints use Supabase RPCs to execute similarity matching (RAG/Vector embeddings) for arbitrary queries.

#### `GET /search_attractions`
Searches for tourist attractions by semantic similarity.

**Query Parameters:**
- `q`: Search string (e.g. "Bãi biển đẹp")
- `k`: Number of results (default: 10)

**Response:**
```json
{
  "status": "success",
  "results": [
    {
      "id": "uuid",
      "score": 0.89,
      "name": "string",
      "category": "string"
    }
  ]
}
```

#### `GET /search_hotels`
Searches for hotels and rooms by semantic similarity.

**Query Parameters:**
- `q`: Search string
- `k`: Number of results (default: 10)

**Response:**
```json
{
  "status": "success",
  "results": [
    {
      "id": "uuid",
      "score": 0.85,
      "name": "Hotel Name",
      "star_rating": 5,
      "matched_rooms": { "room_0": "Room Name" },
      "matched_room_names": ["Room Name"]
    }
  ]
}
```

## `trip_plan` shape

```json
{
  "status": "Draft",
  "destination": "Nha Trang", "duration_days": 3, "number_of_adults": 2,
  "hotel": { "id": "...", "name": "...", "star_rating": 4, "description": "...",
             "matched_rooms": ["..."], "coordinates": "..." },
  "days": [ { "day_number": 1, "theme": "...",
              "items": [ { "order_index": 1, "start_time": "08:00", "end_time": "09:30",
                           "activity": "...", "kind": "breakfast",
                           "reference_type": "Attraction", "reference_id": "uuid",
                           "route_to_next": {
                             "distance_km": 6.4,
                             "duration_mins": 14.2,
                             "polyline": "yseeAo...",
                             "profile": "driving-traffic"
                           } } ] } ],
  "adjustments": ["..."]
}
```

**`profile` values**:
- `driving-traffic`: For routes >= 1.2km
- `walking`: For routes < 1.2km


## Internal Architecture & Routing

### `hotel_options[].index` <-> `suggestions[].value`

When a hotel list is pending, `suggestions_for()` emits one chip per option:
`{label: "<index>. <hotel name>", value: "<index>"}` (`chat_session.py:81-89`). The
client sends the chosen `index` back as the plain next `message` — that is exactly what
`select_hotel` already parses (`process_chat_turn`, branch 1 below). `hotel_options[].index`
in the structured payload is the same ordinal as `suggestions[].value`; the two are two
views of one list, not independent contracts.

### `stage` values

| `stage` | Meaning | Set when |
|---|---|---|
| `intake` | Gathering destination/duration/people, or hotel budget/preference questions | Branch 5/6/7 asked a question and returned without calling a tool |
| `hotel_options` | A hotel list is pending pick | `recommend_hotels` ran (branch 7) |
| `planned` | A hotel was just picked and the itinerary generated | `select_hotel` resolved (branch 1a) |
| `modified` | A saved plan was edited | `execute_trip_edit_request` ran (branch 4, `decision == "apply"`) |
| `finalized` | The plan was finalized | `finalize_trip_plan` ran (branch 2) |
| `error` | A tool or the agent returned `"SYSTEM ERROR: ..."` | Any branch whose tool response starts with that prefix |

### `stage` derivation table

`chat_session.py:354`'s agent stream is a single unconditional `agent.stream()` call —
the shared core makes no distinction between an "edit" turn and any other agent turn, so
the API cannot mirror one directly. **`stage` must be derived from which tool actually
ran**, not from which branch of `process_chat_turn` was entered. Four of the five tool
invocations bypass the agent entirely; only the fifth reaches `agent.stream()`.

| # | Call site | Line | Tool | Bypasses agent? | Derived `stage` |
|---|---|---|---|---|---|
| 1 | Pending hotel selection | `chat_session.py:222` | `select_hotel.invoke(...)` | Yes | `planned` on success, `error` on `SYSTEM ERROR:` |
| 2 | Finalization phrase on a saved plan | `chat_session.py:245` | `finalize_trip_plan.invoke({})` | Yes | `finalized` on success, `error` on failure |
| 3 | Saved-plan edit, `decision == "apply"` | `chat_session.py:276` | `execute_trip_edit_request(...)` | Yes | `modified` on success, `error` on failure/`None` |
| 4 | Intake/hotel-prefs complete | `chat_session.py:307` | `recommend_hotels.invoke(...)` | Yes | `hotel_options` |
| 5 | Fallthrough | `chat_session.py:319` | `session.agent.stream(...)` (ReAct agent) | No | Depends on which tool the agent itself called inside the stream (`modify_trip_plan`, `finalize_trip_plan`, etc.) — inspect `tool_output_response`'s originating tool name, or `error` on agent failure |

Any turn that returns a question without invoking a tool (intake gate, hotel-preference
gate, edit clarification) is `stage="intake"` — no tool ran, so there is nothing to
derive from except "still gathering input."

### Routing order — 7 branches, sub-branches 1a/1b/1c

`process_chat_turn` (`src/services/chat_session.py:215`) is the single source of truth
for both the CLI and the web API. The order is load-bearing — reordering is a
regression. Derived directly from the current source, `chat_session.py:221-357`, after
Phase 1 removed two dead blocks (the `if False and session.pending_trip_change...`
branch and the unreachable `change_intent = None` branch that used to sit between
branches 3 and 5).

```
1. pending hotel selection exists     -> select_hotel(message)                    :221
   1a. resolved                        -> return; initial_plan_complete = True     :227
   1b. unresolved but still an attempt -> return the retry prompt, keep the list   :233
   1c. unresolved, not an attempt      -> DROP the list, fall through              :241
2. saved plan + finalization phrase   -> finalize_trip_plan()                     :244
3. saved plan, not planning_new_trip  -> new-trip detection / unsupported-city     :250-256
4. is_saved_plan_edit                 -> plan_trip_edit -> clarify | apply         :258-278
5. not initial_plan_complete
   and not is_saved_plan_edit          -> intake gate: question                    :280-287
6.   intake just completed             -> first hotel-preference question          :293
7.   hotel prefs incomplete            -> next preference question                 :295-300
     both complete                     -> recommend_hotels(verified_arguments)     :307
8. unconditional fallthrough          -> ReAct agent, 2 attempts                   :311-357
```

Branch 5 is the guard that stops the LLM inventing a destination or duration. It ends at
`recommend_hotels`, **not** at itinerary generation — itinerary generation only happens
inside `select_hotel` (branch 1a), gated on a hotel actually being picked.

**Branch 1c is load-bearing.** With a hotel list pending, every later message used to be
read as a choice, trapping the user: "chốt lịch trình" and "thêm quán cà phê ngày 2"
both came back as "chưa xác định được khách sạn", forever. `_is_hotel_choice_attempt()`
(`chat_session.py:177`) decides whether an unresolved reply is still trying to name a
hotel (1b, keep the list) or has moved on (1c, drop the list and fall through). Any
re-derivation of this machine that drops 1c reintroduces that bug.

### Error semantics

- Tool-level failure: the tool's own response text starts with `"SYSTEM ERROR: ..."`
  (Vietnamese-language, user-facing). `process_chat_turn` treats this prefix as the
  success/failure signal at every direct-call site (e.g. `chat_session.py:228,247`), not
  the tool's return type.
- Agent-level failure: `session.agent.stream(...)` raising any `Exception` is caught at
  `chat_session.py:342` and returns a generic Vietnamese `"SYSTEM ERROR: ..."` string —
  the raw exception is never surfaced to the reply text at this layer.
- HTTP-level failure: `POST /api/v1/planner_chat` currently wraps any exception from
  `process_chat_turn`/`suggestions_for` in `HTTPException(status_code=500, detail=str(e))`
  (`routes.py:36`) — this leaks raw exception text to the client and is a known defect
  (plan.md "Verified current state", row "Raw exception text leaks"). Phase 3 is expected
  to replace `detail=str(e)` with a generic 5xx body; not fixed in Phase 1.
- No endpoint should raise an unhandled `TypeError` on a normal request (Phase 1 success
  criterion, verified via manual walkthrough — see phase notes).

## New endpoints (Pending — `260805-1022-claude-design-ui-integration`)

None of the four endpoints below exist in `backend/src/api/routes.py` yet. Shapes are
frozen here so the frontend can build against `frontend/mock/server.js` fixtures now and
swap to the real backend without a contract change once each phase ships.

### `GET /api/v1/hotels/{hotel_id}` (Phase 3)

Serves the Hotel Detail Focus Mode. Reads `hotels` + `rooms` + `room_prices`. `404` with
`{"detail": "..."}` if `hotel_id` doesn't exist.

```jsonc
{
  "id": "uuid", "name": "...", "star_rating": 5, "description": "...",
  "address": "...", "city": "...", "area_name": "...", "location_highlight": "...",
  "coordinates": "16.0544,108.2022",
  "image_url": "https://…", "images": ["https://…"],
  "amenities": ["..."], "amenity_groups": { "Hồ bơi": ["..."] },
  "review_score": 8.9, "review_count": 1284, "category_scores": { "Vị trí": 9.1 },
  "check_in_time": "14:00", "check_in_until": "22:00",
  "check_out_time": "12:00", "reception_open_until": "23:00",
  // nearby_attractions shape confirmed 06/08/2026 against real DB rows — objects,
  // NOT free strings. The rows include airports and bus stations, not only sights.
  // distance_text/category are pre-formatted VI strings from the DB: pass through,
  // but the frontend rebuilds the km figure from distance_km for the UI locale.
  "nearby_attractions": [{
    "name": "Sân bay Quốc tế Đà Nẵng (DAD)", "category": "Sân bay lân cận",
    "coordinates": "16.056327,108.200833", "distance_km": 4.81, "distance_text": "4,81 km"
  }],
  "nearby_essentials": ["..."],
  "lowest_price": 1800000, "currency": "VND",
  "rooms": [{
    "id": "uuid", "name": "Superior Ocean View", "bed_description": "1 giường đôi lớn",
    "room_size_sqm": 32, "max_guests": 2, "view": "Hướng biển",
    "room_facilities": ["..."], "images": ["https://…"],
    "price": {
      "amount": 2200000, "currency": "VND",
      "check_in_date": "2026-10-12", "check_out_date": "2026-10-14",
      "sold_out": false, "package_details": null
    } // | null — no room_prices row matches the requested stay
  }]
}
```

Read-only. There is no "select this room" action — `select_hotel` only accepts a hotel
index, and there is no per-room price-recalculation logic to hang a selection off of
(`plan.md` "Phần chưa làm" #4).

### `GET /api/v1/attractions/{attraction_id}` (Phase 3)

Serves the Place Detail Focus Mode. The frontend gets the id from
`trip_plan.days[].items[].reference_id` when `reference_type == "attraction"`. `404` if
`attraction_id` doesn't exist.

```jsonc
{
  "id": "uuid", "name": "...", "description": "...", "category": "Biển", "is_tour": false,
  "estimated_duration_minutes": 120,
  "opening_time": "06:00", "closing_time": "22:00",
  "ticket_price_adult": 100000, "ticket_price_child": 50000,
  "rating": 4.6, "review_count": 892,
  "coordinates": "16.0490,108.2493",
  "images": ["https://…"]
}
```

No review-quote field exists — `attractions` has `rating`/`review_count` but no review
text rows (`plan.md` "Phần chưa làm" #6). No nearby-attractions field either — there is no
attraction-to-attraction adjacency data (#7); that relation only exists for hotels
(`hotels.nearby_attractions`).

### `GET /api/v1/chat/sessions` (Phase 4)

Serves the conversation-history sidebar rail.

```jsonc
{
  "sessions": [{
    "session_id": "uuid",
    "title": "Đà Nẵng – Hội An 4N3Đ",      // inferred from destination + duration_days
    "destination": "Đà Nẵng", "duration_days": 3,
    "status": "draft",                        // "completed" once trip_data exists
    "created_at": "2026-08-01T09:12:00Z", "updated_at": "2026-08-01T09:40:00Z",
    "thumbnail_url": "https://…"              // chosen hotel's image_url, or null
  }]
}
```

Never `404` — an empty `sessions: []` list is the correct response when a user has no
saved conversations. The frontend treats a `404` from this endpoint (e.g. before Phase 4
ships) as "history feature not available" and hides the rail, not as an error state.

### `GET /api/v1/chat/{session_id}/restore` (Phase 4)

Reopens a past conversation. Same shape as `PlannerChatResponse`, plus the message
timeline. `404` if `session_id` doesn't exist or was never persisted.

```jsonc
{
  "session_id": "uuid",
  "messages": [
    { "role": "user", "text": "Tôi muốn đi Đà Nẵng 3 ngày", "stage": "intake", "at": "2026-08-01T09:12:00Z" },
    { "role": "ai", "text": "...", "stage": "hotel_options", "at": "2026-08-01T09:13:30Z" }
  ],
  "suggestions": [], "stage": "planned",
  "hotel_options": [], "trip_plan": { "...same shape as PlannerChatResponse.trip_plan..." },
  "intake": { "...same shape as PlannerChatResponse.intake..." }
}
```
