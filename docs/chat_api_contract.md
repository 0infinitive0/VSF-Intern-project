# Chat API Contract

Frozen 2026-07-31 in Phase 1 of `plans/260729-1637-trip-planner-chat-ui-and-agents-backend/`
so Phase 3 (backend) and Phase 4 (React frontend) can build against it independently.

**Status of this document relative to the shipped code:** the four endpoints and the
extended `PlannerChatResponse` fields below (`stage`, `hotel_options`, `trip_plan`,
`intake`) are the **target** contract. As of this Phase 1 commit, only
`POST /api/v1/planner_chat` exists, and it returns only `{reply, suggestions}` — the
extended fields and the other three endpoints are built in Phase 3. `reply` and
`suggestions` keep their current meaning throughout (D10); `GET /chat` depends on that
and must keep working unmodified through Phase 4.

## Endpoints

| Method | Path | Body / Query | Returns | Status |
|---|---|---|---|---|
| `POST` | `/api/v1/chat/session` | — | `{session_id, created_at}` | Phase 3 |
| `POST` | `/api/v1/planner_chat` | `{message, session_id}` | `PlannerChatResponse` | Shipped (extended in Phase 3) |
| `GET` | `/api/v1/chat/{session_id}/plan` | — | `{trip_plan}` or 404 | Phase 3 |
| `DELETE` | `/api/v1/chat/{session_id}` | — | `204` | Phase 3 |

`message` stays required with `min_length=1`, and `session_id` stays required on
`planner_chat`, so `tests/test_api/test_routes.py` passes unchanged (backwards
compatibility, per D10).

## `PlannerChatResponse`

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
