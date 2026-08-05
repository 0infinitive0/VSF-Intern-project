# Chat API Contract

Frozen 2026-07-31 in Phase 1 of `plans/260729-1637-trip-planner-chat-ui-and-agents-backend/`
so Phase 3 (backend) and Phase 4 (React frontend) could build against it independently.
Extended 2026-08-05 in Phase 1 of `plans/260805-1022-claude-design-ui-integration/` to add
four more endpoints and extend two existing payloads for the Claude Design UI integration.
Phase numbers below without a plan prefix refer to the **2026-08-05** plan; the original
2026-07-31 phase numbers are gone now that those endpoints are shipped.

**Status of this document relative to the shipped code, as of 2026-08-05:** the four
endpoints below marked "Shipped" are live — `PlannerChatResponse` already carries `stage`,
`hotel_options`, `trip_plan`, and `intake` in production
(`backend/src/models/schemas.py:257-265`), correcting this doc's prior "Phase 3 target"
framing, which was stale. The four endpoints marked "Pending" do not exist yet; the
frontend develops against `frontend/mock/server.js` fixtures for them until their phase
ships (contract-first, per `plans/260805-1022-claude-design-ui-integration/plan.md`).

## Endpoints

| Method | Path | Body / Query | Returns | Status |
|---|---|---|---|---|
| `POST` | `/api/v1/chat/session` | — | `{session_id, created_at}` | Shipped |
| `POST` | `/api/v1/planner_chat` | `{message, session_id}` | `PlannerChatResponse` | Shipped |
| `GET` | `/api/v1/chat/{session_id}/plan` | — | `{trip_plan}` or 404 | Shipped |
| `DELETE` | `/api/v1/chat/{session_id}` | — | `204` | Shipped |
| `GET` | `/api/v1/hotels/{hotel_id}` | — | `HotelDetail` or 404 | Pending (Phase 3) |
| `GET` | `/api/v1/attractions/{attraction_id}` | — | `AttractionDetail` or 404 | Pending (Phase 3) |
| `GET` | `/api/v1/chat/sessions` | — | `{sessions: SessionSummary[]}` | Pending (Phase 4) |
| `GET` | `/api/v1/chat/{session_id}/restore` | — | `SessionRestore` or 404 | Pending (Phase 4) |

`message` stays required with `min_length=1`, and `session_id` stays required on
`planner_chat`, so `tests/test_api/test_routes.py` passes unchanged (backwards
compatibility, per D10). The four new endpoints above are additive only — none of them
change `planner_chat`'s request or the four shipped endpoints' shapes.

> Not documented here: `POST /api/v1/chat/select_hotel`, `GET /api/v1/status`,
> `GET /api/v1/search_attractions`, `GET /api/v1/search_hotels` exist in
> `backend/src/api/routes.py` but are not called by the current frontend
> (`frontend/src/api/chat-client.ts` only calls the four "Shipped" rows above) and are out
> of scope for this contract.

## `PlannerChatResponse`

```json
{
  "session_id": "uuid",
  "reply": "text reply, already formatted",
  "suggestions": [ { "label": "1. Muong Thanh", "value": "1" } ],
  "stage": "intake | hotel_options | planned | modified | finalized | error",
  "hotel_options": [
    { "index": 1, "id": "uuid", "name": "...", "star_rating": 4,
      "description": "...", "matched_rooms": ["..."],
      "average_nightly_price": 3200000, "total_stay_price": 9600000,
      "stay_night_count": 3, "currency": "VND" }
  ],
  "trip_plan": { "...null until a hotel is picked..." },
  "intake": { "destination": "...", "duration": "...", "people": "...", "missing": ["people"] }
}
```

- `reply` and `suggestions` — shipped today (`src/models/schemas.py:49-57`). Unchanged
  meaning: `reply` is the formatted text reply; `suggestions` is a list of tappable
  quick-reply chips (`{label, value}`), built by `suggestions_for()`
  (`chat_session.py:67`). Empty means the turn wants free text.
- `stage`, `hotel_options`, `trip_plan`, `intake` — added in Phase 3. `stage` is
  **derived, not routed** (see below). `hotel_options` is populated only when
  `stage="hotel_options"`.
- `session_id` — currently accepted unvalidated by the request and auto-creates a
  session if unknown (`routes.py:29-32`, tracked as a red-team finding, not fixed in
  this phase).

### `trip_plan` shape

```json
{
  "status": "Draft",
  "destination": "Nha Trang", "duration_days": 3, "number_of_adults": 2,
  "hotel": { "id": "...", "name": "...", "star_rating": 4, "description": "...",
             "matched_rooms": ["..."], "coordinates": "..." },
  "days": [ { "day_number": 1, "theme": "...",
              "items": [ { "order_index": 1, "start_time": "08:00", "end_time": "09:30",
                           "activity": "...", "kind": "breakfast",
                           "reference_type": "Attraction", "reference_id": "uuid" } ] } ],
  "adjustments": ["..."]
}
```

### `hotel_options[].index` <-> `suggestions[].value`

When a hotel list is pending, `suggestions_for()` emits one chip per option:
`{label: "<index>. <hotel name>", value: "<index>"}` (`chat_session.py:81-89`). The
client sends the chosen `index` back as the plain next `message` — that is exactly what
`select_hotel` already parses (`process_chat_turn`, branch 1 below). `hotel_options[].index`
in the structured payload is the same ordinal as `suggestions[].value`; the two are two
views of one list, not independent contracts.

### `hotel_options[]` extension (Pending, Phase 2)

`hotel_selection.py:50` already selects these columns for ranking; `to_hotel_options_payload`
currently throws them away. All new fields are optional so a pre-Phase-2 backend still
satisfies the type:

```jsonc
{
  "index": 1, "id": "uuid", "name": "...", "star_rating": 5,
  // Already shipped (schemas.py:92, to_hotel_options_payload) — a types.ts gap fix,
  // same as days[].items[].coordinates below, not a new Phase 2 field.
  // "lat,lng"; verified against database_schema.sql:12 and both backend
  // parse_coordinates() functions — never WKT.
  "coordinates": "16.0544,108.2022",
  "address": "Mỹ Khê, Ngũ Hành Sơn",
  "area_name": "Ngũ Hành Sơn",
  "image_url": "https://…",            // null if the hotel row has none
  "amenities": ["Hồ bơi vô cực", "Bãi biển riêng"],
  "review_score": 8.9,                 // 0..10
  "review_count": 1284,
  "match_score": 0.96,                 // 0..1, the real _composite_score (hotel_selection.py:172)
  "match_reasons": [                   // codes + raw values, never display strings
    { "code": "budget_fit",    "value": 0.39 },
    { "code": "high_rating",   "value": 8.9 },
    { "code": "amenity_match", "value": "Hồ bơi vô cực" }
  ]
}
```

`match_reasons[].code` is an i18n key (`matchReason.<code>`); the frontend builds the
displayed sentence from the code + value. This keeps the "AI đề xuất vì..." panel honest —
it can only ever restate a real ranking parameter — and keeps display strings out of the
backend, matching `route_to_next.profile` below. The exact set of codes `hotel_selection.py`
emits is decided in Phase 2; the three above are illustrative, not exhaustive.

### `days[].items[]` extension (Pending, Phase 2)

```jsonc
{
  "order_index": 1, "start_time": "08:00", "end_time": "09:30",
  "activity": "...", "kind": "breakfast",
  "reference_type": "Attraction", "reference_id": "uuid",

  // Already returned today by to_trip_plan_payload
  // (backend/src/services/trip_formatter.py:320-323) — a types.ts gap fix, not a new
  // backend field. "lat,lng", same format as hotel_options.
  "coordinates": "16.0678,108.2208",

  // New — from routing.py, currently computed but dropped by to_trip_plan_payload
  "route_to_next": {
    "distance_km": 6.4,
    "duration_mins": 14.2,
    "polyline": "yseeAo...",      // Google Encoded Polyline, precision 1e5
    "profile": "driving-traffic"  // code Mapbox Directions was called with (Phase 12);
                                    // null until Phase 12 ships — today's OSRM call site
                                    // (routing.py:44-48) does not set this key at all
  }, // | null

  "route_from_hotel": { /* same shape */ } // | null — see caveat below
}
```

`route_to_next` / `route_from_hotel` is `null` when either endpoint's coordinates are
missing, the routing call failed or timed out, or no route was found — the frontend must
render its straight-line fallback in every one of those cases (`index.html:874-876` in the
airflow dashboard reference implementation is the pattern to port).

When origin and destination coordinates are **identical**, `get_route_to_next`
(`routing.py:84-89`) instead returns `{distance_km: 0.0, duration_mins: 0.0, polyline: ""}`
— no `profile` key at all today, so the frontend type allows `profile: null` here too. This
is "no travel needed", a different UI state from the route being absent.

`route_from_hotel` is commonly `null` even on itineraries where it was computed at
generation time: `recalculate_itinerary_routes` (`routing.py:127`) does set it, but
`ITEM_RPC_FIELDS` (`itinerary_store.py:47-60`) does not include `route_from_hotel`, so it is
silently dropped on the next DB round-trip. Expect this on most saved/reloaded itineraries,
not as a rare edge case (`plan.md` "Phần chưa làm" #15) — fixing it is out of this plan's
scope (would need an `ITEM_RPC_FIELDS` change plus a DB migration/RPC update).

## `stage` values

| `stage` | Meaning | Set when |
|---|---|---|
| `intake` | Gathering destination/duration/people, or hotel budget/preference questions | Branch 5/6/7 asked a question and returned without calling a tool |
| `hotel_options` | A hotel list is pending pick | `recommend_hotels` ran (branch 7) |
| `planned` | A hotel was just picked and the itinerary generated | `select_hotel` resolved (branch 1a) |
| `modified` | A saved plan was edited | `execute_trip_edit_request` ran (branch 4, `decision == "apply"`) |
| `finalized` | The plan was finalized | `finalize_trip_plan` ran (branch 2) |
| `error` | A tool or the agent returned `"SYSTEM ERROR: ..."` | Any branch whose tool response starts with that prefix |

## `stage` derivation table

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

## Routing order — 7 branches, sub-branches 1a/1b/1c

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

## Error semantics

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
  "nearby_attractions": ["..."], "nearby_essentials": ["..."],
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
