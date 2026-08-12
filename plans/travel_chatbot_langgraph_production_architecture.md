# Production Travel Chatbot Architecture
## FastAPI + PostgreSQL + GPT + LangGraph + Domain Tools

> **Purpose:** Technical architecture specification for an LLM/AI coding agent implementing a production travel-planning chatbot.
>
> **Core principle:** The LLM is the natural-language understanding/reasoning layer. PostgreSQL is the application source of truth. LangGraph orchestrates stateful workflows. Domain services and tools execute deterministic business logic and external API calls.

---

## 1. Goals

The chatbot must support natural-language interaction for:

- Hotel discovery and hotel Q&A
- Hotel filtering by:
  - amenities
  - price
  - rating
  - location
  - radius
  - dates
- Trip creation
- Personalized itinerary generation
- Daily themes/preferences
- Budget management
- Date changes
- Hotel selection
- Itinerary modification
- Natural-language refinement such as:
  - "Ngày 1 tôi muốn thiên nhiên khám phá"
  - "Budget của tôi còn 8 triệu"
  - "Tìm khách sạn trong bán kính 3km"
  - "Có gym và hồ bơi"
  - "Chọn khách sạn thứ 2"
  - "Đổi cái này"
  - "Giữ nguyên ngày 1"
  - "Ngày 2 cho tôi ăn uống nhiều hơn"
- Clarification when user input is ambiguous or incomplete
- Booking/handoff workflows with explicit confirmation
- Multi-turn conversation where the user can modify previously supplied constraints

The system must not require a separate hard-coded intent/tool for every possible user sentence.

---

# 2. Architectural Principle

Use this model:

```text
User message
    |
    v
Natural-language understanding
    |
    v
Structured intent + state patch
    |
    v
Validation
    |
    v
Update application state
    |
    v
Detect affected domains
    |
    +----> Hotel workflow
    |
    +----> Itinerary workflow
    |
    +----> Booking workflow
    |
    v
Deterministic validation
    |
    v
Response
```

Do NOT design the system as:

```text
User -> LLM -> final answer
```

Do NOT allow the LLM to be the source of truth for:

- dates
- hotel availability
- hotel distance
- route feasibility
- budget calculations
- booking status
- itinerary time conflicts

The LLM may interpret and reason over these domains, but deterministic code/tools must validate them.

---

# 3. Evidence and References

## 3.1 LangGraph Persistence

LangGraph provides persistence/checkpointing for stateful graph execution. This supports durable execution, conversation threads, and resuming execution.

Reference:

- LangGraph Persistence:
  https://docs.langchain.com/oss/python/langgraph/persistence

Use LangGraph checkpointing for execution state such as:

- current graph execution
- thread/conversation execution
- interrupted workflow
- resumable operations
- debugging/replay

Do not treat LangGraph checkpoint state as the application's only business database.

Recommended separation:

```text
PostgreSQL
    = application/business source of truth

LangGraph checkpointer
    = workflow execution/checkpoint state
```

---

## 3.2 LangGraph Interrupts / Human-in-the-Loop

LangGraph supports `interrupt()` to pause graph execution, persist state, and resume later after external/user input.

Reference:

- LangGraph Interrupts:
  https://docs.langchain.com/oss/python/langgraph/interrupts

This is directly applicable to:

### Ambiguous date

User:

```text
01/07
```

System:

```text
Missing year
    |
    v
interrupt()
    |
    v
"Bạn muốn ngày 01/07 của năm nào?"
```

User responds:

```text
2027
```

Graph resumes.

### Booking confirmation

```text
Check availability
    |
    v
Price confirmation
    |
    v
interrupt()
    |
    v
"Phòng này có giá X. Bạn có muốn đặt không?"
    |
    v
User confirms
    |
    v
Resume
    |
    v
Booking API
```

LangGraph documentation explicitly describes pausing execution, saving state, waiting for input, and resuming later.

---

## 3.3 TravelAgent

Reference:

- Chen et al., "TravelAgent: An AI Assistant for Personalized Travel Planning"
- https://arxiv.org/abs/2409.08069

TravelAgent describes a travel-planning system composed of:

- Tool-usage module
- Recommendation module
- Planning module
- Memory module

The paper emphasizes that travel planning must balance:

- rationality
- comprehensiveness
- personalization

This supports separating:

```text
Tool usage
Recommendation
Planning
Memory/state
```

rather than relying on a single unconstrained LLM response.

---

## 3.4 Vaiage

Reference:

- "Vaiage: A Multi-Agent Solution to Personalized Travel Planning"
- https://arxiv.org/abs/2505.10922

Vaiage uses a graph-structured multi-agent approach for personalized travel planning with:

- user intent
- budget
- timing
- group size
- weather
- external tools
- map-based feedback
- iterative planning

The important architectural lesson for this project is not necessarily to copy the multi-agent structure. The useful idea is to combine:

```text
LLM reasoning
+
structured tools
+
external data
+
constraint-aware planning
+
feedback
```

For the initial production implementation, avoid unnecessary agent proliferation.

---

## 3.5 ATLAS

Reference:

- "ATLAS: Constraints-Aware Multi-Agent Collaboration for Real-World Travel Planning"
- https://arxiv.org/abs/2509.25586

ATLAS focuses on:

- dynamic constraint management
- iterative plan critique
- adaptive interleaved search
- multi-turn feedback
- complex real-world travel constraints

The paper reports that constraint-aware planning and iterative feedback can substantially improve travel-planning performance.

Architectural implication:

```text
Constraints
    |
    v
Planning
    |
    v
Validation / Critique
    |
    v
Re-planning
```

Do not generate an itinerary once and assume it is valid.

---

## 3.6 TREK

Reference:

- "TREK: A Travel Reasoning and Evaluation Kit for LLM Agents in Complex Trip Planning"
- https://arxiv.org/abs/2607.26977

TREK evaluates travel plans against multiple dimensions including:

- constraint correctness
- hallucination-free entities
- spatial/route feasibility
- temporal feasibility
- budget validity
- user needs

The key lesson is that a travel itinerary is not simply a good textual answer. It is an executable artifact subject to multiple simultaneous constraints.

Therefore:

```text
LLM generated plan
       |
       v
Deterministic validation
       |
       +--> route
       +--> time
       +--> budget
       +--> entity validity
       +--> availability
       |
       v
Valid itinerary
```

The paper also demonstrates that even strong LLM agents can fail complex multi-dimensional travel tasks. This is a strong argument for deterministic domain validation.

---

## 3.7 TravelEval

Reference:

- "TravelEval: A Comprehensive Benchmarking Framework for Evaluating LLM-Powered Travel Planning Agents"
- https://arxiv.org/abs/2606.01046

TravelEval evaluates plans across dimensions such as:

- accuracy
- constraint compliance
- temporality
- spatiality
- economy
- utility

This supports building evaluation around more than response quality.

Recommended production evaluation metrics:

```text
Intent accuracy
Entity extraction accuracy
State patch accuracy
Constraint satisfaction
Tool selection accuracy
Hotel search correctness
Route validity
Budget validity
Itinerary validity
Response quality
```

---

# 4. High-Level Architecture

```text
                        +----------------+
                        |    Next.js     |
                        | Chat + Trip UI |
                        +-------+--------+
                                |
                           POST /chat
                                |
                                v
                        +---------------+
                        |    FastAPI    |
                        | API / Auth    |
                        | SSE / REST    |
                        +-------+-------+
                                |
                                v
                    +-----------------------+
                    |      LangGraph        |
                    |                       |
                    | Load Context         |
                    |       |               |
                    | Understand Request    |
                    |       |               |
                    | Extract State Patch   |
                    |       |               |
                    | Validate              |
                    |       |               |
                    | Apply Patch           |
                    |       |               |
                    | Detect Impact         |
                    +-----------+-----------+
                                |
                +---------------+----------------+
                |               |                |
                v               v                v
          Hotel Flow      Itinerary Flow    Booking Flow
                |               |                |
                v               v                v
          Hotel APIs       POI / Route       Booking API
                          Weather / Maps
                |               |                |
                +---------------+----------------+
                                |
                                v
                        +---------------+
                        | PostgreSQL    |
                        |               |
                        | Trips         |
                        | Preferences   |
                        | Itinerary     |
                        | Hotels        |
                        | Messages      |
                        | Audit logs    |
                        +---------------+
```

---

# 5. Responsibility of Each Layer

## Next.js

Responsible for:

- chat UI
- itinerary UI
- hotel UI
- state visualization
- approval/confirmation UI
- streaming events

The UI should not maintain a completely separate interpretation of travel state.

---

## FastAPI

Responsible for:

- authentication
- authorization
- REST APIs
- SSE/streaming
- request validation
- invoking LangGraph
- returning structured state changes
- exposing trip/hotel/itinerary APIs

---

## LangGraph

Responsible for:

- orchestration
- stateful workflow execution
- routing
- interruptions
- resumable workflows
- tool coordination
- execution checkpoints

---

## GPT

Responsible for:

- intent detection
- natural-language interpretation
- entity extraction
- reference resolution
- structured state patch generation
- recommendation/ranking reasoning
- response generation

GPT must not be trusted for deterministic business facts.

---

## Domain Services

Responsible for:

- budget calculations
- date calculations
- constraint validation
- route validation
- itinerary scheduling
- hotel filtering
- canonical amenity mapping
- booking rules

---

## PostgreSQL

Source of truth for:

- trip
- preferences
- itinerary
- hotel selection
- hotel search history
- conversation/message persistence
- audit history

---

# 6. PostgreSQL Data Model

## trips

```sql
CREATE TABLE trips (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL,

    destination TEXT,

    start_date DATE,
    end_date DATE,

    status TEXT NOT NULL DEFAULT 'draft',

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

## trip_preferences

```sql
CREATE TABLE trip_preferences (
    trip_id UUID PRIMARY KEY REFERENCES trips(id),

    budget_min NUMERIC,
    budget_max NUMERIC,
    currency TEXT DEFAULT 'VND',

    pace TEXT,

    themes JSONB DEFAULT '[]',
    interests JSONB DEFAULT '[]',

    travelers JSONB DEFAULT '{}',

    hotel_preferences JSONB DEFAULT '{}',

    constraints JSONB DEFAULT '{}',

    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

Example:

```json
{
  "themes": ["nature", "food"],
  "interests": ["hiking"],
  "hotel_preferences": {
    "radius_km": 3,
    "amenities": ["pool", "gym"]
  },
  "constraints": {
    "max_travel_time_minutes": 30
  }
}
```

---

# 7. Itinerary Data Model

Do not store the itinerary as one text blob.

## itinerary_days

```sql
CREATE TABLE itinerary_days (
    id UUID PRIMARY KEY,
    trip_id UUID REFERENCES trips(id),

    day_number INT NOT NULL,
    date DATE,

    theme TEXT,

    status TEXT DEFAULT 'draft',

    UNIQUE(trip_id, day_number)
);
```

## itinerary_items

```sql
CREATE TABLE itinerary_items (
    id UUID PRIMARY KEY,

    day_id UUID REFERENCES itinerary_days(id),

    place_id TEXT,
    title TEXT,
    category TEXT,

    start_time TIME,
    end_time TIME,

    duration_minutes INT,

    order_index INT,

    estimated_cost NUMERIC,

    travel_time_from_previous INT,

    metadata JSONB DEFAULT '{}'
);
```

This allows the system to modify Day 1 without regenerating the entire trip.

---

# 8. Hotel Search Model

```sql
CREATE TABLE hotel_searches (
    id UUID PRIMARY KEY,

    trip_id UUID REFERENCES trips(id),

    center_lat DOUBLE PRECISION,
    center_lng DOUBLE PRECISION,

    radius_km DOUBLE PRECISION,

    min_price NUMERIC,
    max_price NUMERIC,

    amenities JSONB DEFAULT '[]',

    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

# 9. LangGraph State

Keep graph execution state small.

```python
from typing import TypedDict


class TravelGraphState(TypedDict):

    user_id: str
    trip_id: str
    thread_id: str

    messages: list

    intent: str | None

    extracted_data: dict

    state_patch: dict

    validation_errors: list[str]

    missing_fields: list[str]

    affected_domains: list[str]

    tool_results: dict

    response: str | None
```

Do not place the entire application database into every graph state.

Use:

```text
Graph state
    =
execution state

PostgreSQL
    =
business state
```

---

# 10. Main LangGraph

```text
START
  |
  v
load_context
  |
  v
understand_request
  |
  v
extract_changes
  |
  v
validate_changes
  |
  +---- invalid / ambiguous ----> clarify
  |                                  |
  |                                  v
  |                                 END
  |
  v
apply_state_patch
  |
  v
detect_impact
  |
  +------------+-------------+
  |            |             |
  v            v             v
hotel_flow  itinerary_flow  no_action
  |            |
  +------------+
       |
       v
validate_result
       |
       v
generate_response
       |
       v
END
```

---

# 11. Context Resolver

The agent must resolve conversational references.

Examples:

```text
"Chọn cái thứ 2"
"Đổi cái này"
"Tìm cái gần đó"
"Cái khách sạn vừa rồi"
"Giữ nguyên ngày 1"
```

Persist search context:

```json
{
  "last_hotel_results": [
    {"id": "h1", "name": "Hotel A"},
    {"id": "h2", "name": "Hotel B"},
    {"id": "h3", "name": "Hotel C"}
  ],
  "last_place_results": [],
  "selected_hotel": null
}
```

For:

```text
"Chọn cái thứ 2"
```

resolve deterministically:

```text
index 2
    |
    v
hotel_results[1]
    |
    v
hotel_id = h2
```

Do not ask the LLM to invent an ID.

---

# 12. Intent Schema

```python
class IntentResult(BaseModel):

    intent: Literal[
        "hotel_search",
        "hotel_details",
        "create_itinerary",
        "update_itinerary",
        "update_trip",
        "select_hotel",
        "booking",
        "general_question"
    ]

    confidence: float
```

GPT should classify the user's intent rather than immediately generate the final answer.

---

# 13. State Patch

The most important abstraction is a generic state patch.

Example:

```json
{
  "changes": [
    {
      "path": "budget.max",
      "operation": "set",
      "value": 10000000
    }
  ]
}
```

Example:

```json
{
  "changes": [
    {
      "path": "daily_preferences.day_1.theme",
      "operation": "set",
      "value": "nature"
    }
  ]
}
```

Example:

```json
{
  "changes": [
    {
      "path": "hotel_preferences.radius_km",
      "operation": "set",
      "value": 3
    },
    {
      "path": "hotel_preferences.amenities",
      "operation": "set",
      "value": ["gym", "pool"]
    }
  ]
}
```

The LLM produces the patch.

The backend validates and applies it.

---

# 14. Allowed State Paths

Never allow the LLM to modify arbitrary database fields.

Use an allow-list:

```python
ALLOWED_PATHS = {
    "destination",
    "dates.start",
    "dates.end",
    "budget.min",
    "budget.max",
    "preferences.themes",
    "preferences.interests",
    "hotel_preferences.amenities",
    "hotel_preferences.radius_km",
    "hotel_preferences.max_price",
    "hotel_preferences.min_rating",
    "daily_preferences.*.theme",
}
```

The state service rejects unknown paths.

---

# 15. Handling Missing and Ambiguous Data

Do not treat a missing value as an invalid field.

Use explicit states:

```text
UNKNOWN
SET
NOT_APPLICABLE
```

Example:

```text
budget = UNKNOWN
```

means the user has not supplied a budget.

This must still allow:

```text
"Budget của tôi là 10 triệu"
```

to work.

If user says:

```text
"Không quan tâm budget"
```

set:

```text
budget = NOT_APPLICABLE
```

---

# 16. Date Handling

User:

```text
01/07
```

GPT should extract:

```json
{
  "day": 1,
  "month": 7,
  "year": null
}
```

Backend determines that year is missing.

Then:

```text
validate
   |
   v
missing year
   |
   v
interrupt
```

Ask:

```text
Bạn muốn ngày 01/07 của năm nào?
```

Do not let the LLM silently invent the year.

If product requirements explicitly define a deterministic rule such as "choose the next occurrence", implement that rule in code.

---

# 17. Daily Itinerary Editing

User:

```text
Ngày 1 tôi muốn thiên nhiên khám phá.
```

Extract:

```json
{
  "intent": "update_itinerary",
  "changes": [
    {
      "path": "daily_preferences.day_1.theme",
      "operation": "set",
      "value": "nature"
    }
  ]
}
```

Impact:

```text
daily_preferences.day_1
    |
    v
itinerary
```

Workflow:

```text
Update Day 1 theme
    |
    v
Search nature POIs
    |
    v
Filter candidates
    |
    v
Rank candidates
    |
    v
Calculate route
    |
    v
Schedule
    |
    v
Budget validation
    |
    v
Save Day 1
```

Do not regenerate unaffected days.

---

# 18. Budget Editing

User:

```text
Budget của tôi còn 8 triệu.
```

Patch:

```json
{
  "path": "budget.max",
  "value": 8000000
}
```

Impact:

```text
budget
   |
   +----> hotel
   |
   +----> itinerary
```

If Day 1 is locked:

```text
budget changed
    |
    v
optimize Day 2 + Day 3
    |
    v
keep Day 1 unchanged
```

This requires a concept of itinerary locks.

Example:

```json
{
  "locked_days": [1]
}
```

---

# 19. Hotel Amenity Search

Canonicalize user language.

Examples:

```text
"hồ bơi"
"bể bơi"
"swimming pool"
"pool"
```

all map to:

```text
pool
```

Similarly:

```text
"phòng tập"
"chỗ tập thể dục"
"fitness"
"gym"
```

map to:

```text
gym
```

Recommended canonical taxonomy:

```text
pool
gym
spa
parking
breakfast
wifi
restaurant
air_conditioning
airport_shuttle
```

---

# 20. Radius Search

User:

```text
Tìm khách sạn trong bán kính 3km.
```

The system must determine the center.

Possible centers:

```text
destination center
selected POI
hotel
airport
user-selected location
```

If center is ambiguous, ask.

Example:

```text
Tìm khách sạn trong bán kính 3km từ Bà Nà Hills.
```

State:

```json
{
  "hotel_preferences": {
    "radius_km": 3,
    "center": {
      "type": "poi",
      "id": "ba-na-hills"
    }
  }
}
```

Distance calculation must be deterministic.

If PostgreSQL/PostGIS is available:

```sql
SELECT *
FROM hotels
WHERE ST_DWithin(
    location::geography,
    ST_SetSRID(
        ST_MakePoint(:lng, :lat),
        4326
    )::geography,
    :radius_meters
);
```

For 3 km:

```text
radius_meters = 3000
```

Do not let GPT calculate geographic distance.

---

# 21. Hotel Flow

```text
hotel_flow
    |
    v
resolve center
    |
    v
search hotels
    |
    v
availability
    |
    v
filter:
    - radius
    - amenities
    - price
    - rating
    |
    v
rank
    |
    v
save results
    |
    v
response
```

Recommended tools:

```text
search_hotels
get_hotel_details
check_hotel_availability
get_hotel_amenities
get_hotel_reviews
select_hotel
```

---

# 22. Itinerary Flow

```text
itinerary_flow
    |
    v
load current itinerary
    |
    v
identify affected days
    |
    v
search candidate places
    |
    v
filter
    |
    v
LLM ranking
    |
    v
route calculation
    |
    v
time validation
    |
    v
budget validation
    |
    v
save itinerary
```

Recommended tools:

```text
search_places
get_place_details
get_opening_hours
calculate_route
get_travel_time
get_weather
estimate_activity_cost
```

---

# 23. LLM vs Deterministic Logic

## GPT

Use GPT for:

```text
intent detection
entity extraction
natural-language interpretation
reference interpretation
recommendation ranking
explanation
```

## Deterministic code

Use code for:

```text
date validation
budget calculation
distance
route duration
opening hours validation
availability
booking state
time conflicts
constraint validation
```

## External tools

Use tools/APIs for:

```text
hotel inventory
hotel prices
availability
maps
POIs
weather
booking
```

---

# 24. Tool Design

Do not create one tool per sentence.

Bad:

```text
set_budget()
set_day_1_theme()
set_day_2_theme()
set_day_3_theme()
set_hotel_radius()
set_hotel_gym()
...
```

Prefer domain capabilities:

```text
search_hotels
search_places
calculate_route
update_travel_state
update_itinerary
check_availability
select_hotel
create_booking
```

The LLM maps different natural-language expressions into these capabilities.

---

# 25. Tool Safety

Every tool must validate input.

Example:

```python
def validate_radius(radius_km: float):
    if radius_km <= 0:
        raise ValueError("Radius must be positive")

    if radius_km > MAX_SEARCH_RADIUS_KM:
        raise ValueError("Radius exceeds allowed limit")
```

Never trust tool arguments simply because they came from GPT.

---

# 26. Booking Flow

Booking should be separate from planning:

```text
search
  |
  v
select hotel
  |
  v
check availability
  |
  v
confirm price
  |
  v
interrupt / user confirmation
  |
  v
hold room
  |
  v
booking
  |
  v
handoff
```

Use LangGraph interrupt/HITL for sensitive or irreversible operations.

LangGraph's documentation explicitly supports approval, edit, and reject decisions for human-in-the-loop actions.

Reference:

https://docs.langchain.com/oss/python/langchain/human-in-the-loop

---

# 27. State Impact Mapping

Every state field should declare what workflows it affects.

Example:

```python
IMPACT_MAP = {

    "budget": [
        "hotel",
        "itinerary"
    ],

    "dates": [
        "hotel",
        "itinerary"
    ],

    "hotel_preferences": [
        "hotel"
    ],

    "daily_preferences": [
        "itinerary"
    ],

    "preferences.themes": [
        "itinerary"
    ]
}
```

Examples:

```text
budget changed
    -> hotel + itinerary

dates changed
    -> hotel + itinerary

hotel amenities changed
    -> hotel

Day 1 theme changed
    -> Day 1 itinerary

general question
    -> no mutation
```

---

# 28. Audit Log

Every state mutation should be auditable.

Example:

```text
10:30
budget: UNKNOWN -> 10,000,000

10:35
budget: 10,000,000 -> 8,000,000

10:40
day_1.theme: null -> nature

10:42
hotel_preferences.radius_km: null -> 3
```

Suggested table:

```sql
CREATE TABLE state_audit_logs (
    id UUID PRIMARY KEY,
    trip_id UUID NOT NULL,

    source TEXT,
    actor_id UUID,

    patch JSONB NOT NULL,

    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

This is critical for debugging agent behavior.

---

# 29. API Design

## Create trip

```http
POST /api/trips
```

## Get trip

```http
GET /api/trips/{trip_id}
```

## Direct state update

```http
PATCH /api/trips/{trip_id}
```

## Chat

```http
POST /api/trips/{trip_id}/chat
```

## Itinerary

```http
GET /api/trips/{trip_id}/itinerary
```

## Hotel search

```http
POST /api/trips/{trip_id}/hotel-search
```

The Chat API and Trip UI should ultimately operate on the same application state.

---

# 30. Chat Response

Recommended response:

```json
{
  "message": "Đã cập nhật ngày 1 theo chủ đề thiên nhiên.",
  "state_changes": [
    {
      "path": "daily_preferences.day_1.theme",
      "value": "nature"
    }
  ],
  "affected_domains": [
    "itinerary"
  ],
  "itinerary_updated": true
}
```

This lets the UI update itself without parsing natural-language text.

---

# 31. Streaming

Use SSE for long-running operations.

Example events:

```text
event: thinking
data: {"status":"Analyzing request"}

event: state_update
data: {"path":"budget.max","value":8000000}

event: tool
data: {"name":"search_places"}

event: tool_result
data: {"count":12}

event: itinerary
data: {"day":1,"status":"updated"}

event: message
data: {"content":"Tôi đã cập nhật ngày 1..."}
```

---

# 32. Error Handling

External tools must have:

```text
timeout
retry
fallback
validation
logging
```

Never do:

```text
Routing API fails
    |
    v
LLM invents travel time
```

Instead:

```text
Routing API fails
    |
    v
retry
    |
    v
fallback provider
    |
    v
if still failed:
    |
    v
ask user / explain limitation
```

---

# 33. Observability

Log at minimum:

```text
request_id
user_id
trip_id
thread_id

intent
state_patch

tool_name
tool_latency
tool_error

model
input_tokens
output_tokens

itinerary_version
```

Example:

```text
trip=abc123
intent=update_itinerary
patch=day_1.theme:nature
tool=search_places
latency=820ms
tool=calculate_route
latency=430ms
```

Use tracing so failures can be separated into:

```text
LLM extraction failure
State validation failure
Tool failure
External API failure
Planning failure
UI synchronization failure
```

---

# 34. Evaluation Strategy

RAGAS-style evaluation alone is insufficient for this application.

Create a dedicated travel-agent evaluation dataset.

Example cases:

```text
01/07
01/07/2027
Ngày đầu
Ngày 1
Cái thứ 2
Đổi cái này
Budget 10 triệu
Budget còn 8 triệu
Dưới 2 triệu/đêm
Trong vòng 3km
Gần biển
Có gym
Có hồ bơi
Không muốn bảo tàng
Ngày 1 nature
Giữ nguyên ngày 2
```

Metrics:

```text
Intent accuracy
Entity extraction accuracy
State patch accuracy
Reference resolution accuracy
Constraint satisfaction
Tool selection accuracy
Hotel search correctness
Route validity
Budget validity
Itinerary validity
Response quality
```

The most important metric for the conversational state layer:

```text
State Patch Accuracy
```

---

# 35. Production Graph Skeleton

```python
from langgraph.graph import StateGraph, START, END


builder = StateGraph(TravelGraphState)

builder.add_node("load_context", load_context)
builder.add_node("understand", understand_request)
builder.add_node("extract", extract_changes)
builder.add_node("validate", validate_changes)
builder.add_node("apply_patch", apply_state_patch)
builder.add_node("detect_impact", detect_impact)

builder.add_node("hotel_flow", hotel_flow)
builder.add_node("itinerary_flow", itinerary_flow)

builder.add_node("response", generate_response)

builder.add_edge(START, "load_context")
builder.add_edge("load_context", "understand")
builder.add_edge("understand", "extract")
builder.add_edge("extract", "validate")

builder.add_conditional_edges(
    "validate",
    route_validation,
    {
        "clarify": "response",
        "apply": "apply_patch",
    }
)

builder.add_edge("apply_patch", "detect_impact")

builder.add_conditional_edges(
    "detect_impact",
    route_impact,
    {
        "hotel": "hotel_flow",
        "itinerary": "itinerary_flow",
        "none": "response",
    }
)

builder.add_edge("hotel_flow", "response")
builder.add_edge("itinerary_flow", "response")

builder.add_edge("response", END)

graph = builder.compile(
    checkpointer=checkpointer
)
```

Production should use a persistent checkpointer rather than in-memory state.

---

# 36. Recommended Python Project Structure

The production graph is a state-patch workflow first. The supervisor routes
work, but hotel, itinerary, and booking are scoped subgraphs backed by shared
domain tools; they are not unrestricted independent agents. The supervisor
receives a compact session manifest and data references, never full hotel or
itinerary result sets.

```text
backend/
├── src/
│   ├── main.py
│   ├── api/
│   │   ├── chat.py
│   │   ├── trips.py
│   │   ├── hotels.py
│   │   └── bookings.py
│   │
│   ├── graph/
│   │   ├── graph.py              # Parent LangGraph workflow
│   │   ├── state.py              # TravelGraphState + SessionManifest
│   │   ├── contracts.py          # Agent/flow read, write, and required fields
│   │   ├── impact_map.py         # State path -> affected domain flows
│   │   ├── prompting.py          # Composes approved compact context + validates LLM output
│   │   ├── nodes/
│   │   │   ├── load_context.py    # Resolve compact session manifest/references
│   │   │   ├── understand_request.py # Intent/extraction + deterministic validation
│   │   │   ├── apply_change.py    # State patch + affected-flow calculation
│   │   │   ├── route_or_replan.py # Task delegation, completion and loop limits
│   │   │   ├── hotel.py          # Invokes hotel_flow
│   │   │   ├── itinerary.py      # Invokes itinerary_flow
│   │   │   ├── booking.py        # Confirmation-gated booking entry
│   │   │   ├── answer.py          # Read-only questions and answers
│   │   │   └── response.py
│   │   ├── subgraphs/
│   │   │   ├── hotel_flow.py     # Search -> availability -> filter -> rank
│   │   │   ├── itinerary_flow.py # Retrieve -> schedule -> validate -> save
│   │   │   └── booking_flow.py   # Interrupt -> hold -> booking -> handoff
│   │   └── prompts/
│   │       ├── base.md           # Shared safety, language, and response rules
│   │       ├── supervisor.md     # Routing, delegation, and replanning instructions
│   │       ├── understand.md     # Intent and structured-field extraction
│   │       ├── hotel.md          # Hotel-search reasoning only
│   │       ├── itinerary.md      # Itinerary-planning reasoning only
│   │       ├── qa.md             # Read-only question answering
│   │       ├── booking.md        # Clarification before deterministic booking actions
│   │       ├── clarify.md        # Missing or ambiguous information requests
│   │       └── response.md       # Final user-facing response composition
│   │
│   ├── tools/                     # Shared deterministic/external capabilities
│   │   ├── hotels.py
│   │   ├── places.py
│   │   ├── routing.py
│   │   ├── weather.py
│   │   └── booking.py
│   │
│   ├── domain/
│   │   ├── travel_state.py
│   │   ├── state_patches.py
│   │   ├── constraints.py
│   │   ├── validators.py
│   │   └── itinerary.py
│   │
│   ├── repositories/
│   │   ├── trips.py
│   │   ├── itineraries.py
│   │   ├── hotels.py
│   │   ├── messages.py
│   │   └── audit_logs.py
│   │
│   ├── models/
│   │   ├── trip.py
│   │   ├── itinerary.py
│   │   ├── hotel.py
│   │   └── booking.py
│   │
│   └── services/
│       ├── state_service.py
│       ├── hotel_service.py
│       ├── itinerary_service.py
│       └── booking_service.py
│
└── migrations/
```

Only LLM-backed nodes load prompts. Validation within `understand_request`,
patch/impact logic within `apply_change`, completion checks, availability,
booking confirmation, and route/budget validation remain deterministic Python.

`graph/contracts.py` limits each flow to the parameters and tools it needs.
For example, `hotel_flow` may read trip dates and preferences and write hotel
results or a selected hotel; it cannot write itinerary or booking state.
`answer.py` is read-only. The parent graph remains responsible for task creation,
completion checks, dynamic replanning, total-task limits, and loop limits.

<!-- Superseded project-structure draft retained below for document history.

```text
backend/
|
├── app/
│   ├── main.py
│   |
│   ├── api/
│   │   ├── chat.py
│   │   ├── trips.py
│   │   └── hotels.py
│   |
│   ├── graph/
│   │   ├── state.py
│   │   ├── graph.py
│   │   |
│   │   ├── nodes/
│   │   │   ├── context.py
│   │   │   ├── understand.py
│   │   │   ├── extract.py
│   │   │   ├── validate.py
│   │   │   ├── patch.py
│   │   │   ├── impact.py
│   │   │   ├── hotel.py
│   │   │   ├── itinerary.py
│   │   │   └── response.py
│   │   |
│   │   └── prompts/
│   │       ├── understand.md
│   │       └── extract.md
│   |
│   ├── tools/
│   │   ├── hotels.py
│   │   ├── places.py
│   │   ├── routing.py
│   │   ├── weather.py
│   │   └── booking.py
│   |
│   ├── domain/
│   │   ├── travel_state.py
│   │   ├── constraints.py
│   │   ├── validators.py
│   │   └── itinerary.py
│   |
│   ├── repositories/
│   │   ├── trips.py
│   │   ├── itinerary.py
│   │   ├── hotels.py
│   │   └── messages.py
│   |
│   ├── models/
│   │   ├── trip.py
│   │   ├── itinerary.py
│   │   └── hotel.py
│   |
│   └── services/
│       ├── state_service.py
│       ├── itinerary_service.py
│       └── hotel_service.py
|
└── migrations/
```

---

-->

# 37. Example End-to-End Conversation

## User

```text
Tôi muốn đi Đà Nẵng 3 ngày, budget 10 triệu,
ngày đầu thiên nhiên khám phá.
```

GPT extracts:

```json
{
  "intent": "create_itinerary",
  "changes": [
    {
      "path": "destination",
      "value": "Da Nang"
    },
    {
      "path": "duration",
      "value": 3
    },
    {
      "path": "budget.max",
      "value": 10000000
    },
    {
      "path": "daily_preferences.day_1.theme",
      "value": "nature"
    }
  ]
}
```

If dates are missing:

```text
interrupt
```

Ask:

```text
Bạn muốn đi từ ngày nào đến ngày nào?
```

---

## User

```text
01/07 đến 03/07 năm 2027.
```

State is updated.

Then:

```text
search POIs
    |
    v
filter
    |
    v
rank
    |
    v
route
    |
    v
budget
    |
    v
save itinerary
```

---

## User

```text
Tìm khách sạn trong bán kính 3km,
có gym và hồ bơi.
```

Patch:

```json
{
  "hotel_preferences.radius_km": 3,
  "hotel_preferences.amenities": [
    "gym",
    "pool"
  ]
}
```

Hotel flow runs.

---

## User

```text
Chọn khách sạn thứ 2.
```

Resolver:

```text
last_hotel_results[1]
```

Then:

```text
select_hotel(hotel_id)
```

---

## User

```text
Budget còn 8 triệu,
nhưng giữ nguyên ngày 1.
```

Patch:

```json
{
  "budget.max": 8000000,
  "locked_days": [1]
}
```

Planner:

```text
Day 1 -> unchanged

Day 2 + Day 3
    |
    v
optimize
    |
    v
budget <= 8m
```

---

# 38. What NOT to Build

Avoid:

```text
10+ independent agents
```

before the single-domain stateful workflow is stable.

Avoid:

```text
LLM -> SQL
```

Avoid:

```text
LLM calculates distance
```

Avoid:

```text
LLM decides hotel availability
```

Avoid:

```text
one giant itinerary-generation prompt
```

Avoid:

```text
conversation history = application state
```

Avoid:

```text
regenerate entire itinerary after every small edit
```

Avoid:

```text
one tool per user sentence
```

---

# 39. Recommended Implementation Order

## Phase 1 — State foundation

Implement:

```text
trips
trip_preferences
itinerary_days
itinerary_items

TravelGraphState
state patches
validation
audit log
```

## Phase 2 — Conversational editing

Support:

```text
budget
dates
themes
daily themes
hotel preferences
```

## Phase 3 — Hotel

Implement:

```text
amenities
radius
price
rating
availability
hotel selection
reference resolution
```

## Phase 4 — Itinerary

Implement:

```text
POI search
ranking
route
schedule
budget validation
day-level regeneration
```

## Phase 5 — Interrupts

Implement:

```text
ambiguous date
missing required information
booking confirmation
price changes
```

## Phase 6 — Booking

Implement:

```text
availability
hold
confirmation
booking
release
handoff
```

## Phase 7 — Evaluation

Build a test suite for:

```text
intent
patch
reference resolution
constraints
hotel search
itinerary
budget
route
```

---

# 40. Final Architecture Decision

The recommended production architecture is:

```text
                         USER
                           |
                           v
                      Next.js UI
                           |
                           v
                        FastAPI
                           |
                           v
                     LangGraph
                           |
             +-------------+-------------+
             |                           |
       Conversation                  Workflow
          state                       state
             |                           |
             v                           v
       GPT / parsing              Domain services
             |                           |
             v                           v
       State Patch                  Deterministic
             |                       validation
             +-------------+-------------+
                           |
                           v
                      PostgreSQL
                           |
        +------------------+------------------+
        |                  |                  |
       Trips           Itinerary           Hotels
        |                  |                  |
        +------------------+------------------+
                           |
                           v
                    External APIs
              Hotels / Maps / Weather / Booking
```

The key architectural rule is:

> **LLM understands the user's language. LangGraph orchestrates the workflow. PostgreSQL stores the truth. Domain services enforce correctness. Tools interact with external systems.**

This design is intended to make the system robust against many natural-language variations without creating a separate hard-coded workflow for every possible user sentence.

---

# 41. References

1. LangGraph Persistence  
   https://docs.langchain.com/oss/python/langgraph/persistence

2. LangGraph Interrupts  
   https://docs.langchain.com/oss/python/langgraph/interrupts

3. LangChain Human-in-the-Loop  
   https://docs.langchain.com/oss/python/langchain/human-in-the-loop

4. Chen et al. — TravelAgent: An AI Assistant for Personalized Travel Planning  
   https://arxiv.org/abs/2409.08069

5. Liu et al. — Vaiage: A Multi-Agent Solution to Personalized Travel Planning  
   https://arxiv.org/abs/2505.10922

6. Choi et al. — ATLAS: Constraints-Aware Multi-Agent Collaboration for Real-World Travel Planning  
   https://arxiv.org/abs/2509.25586

7. Chen et al. — TravelEval: A Comprehensive Benchmarking Framework for Evaluating LLM-Powered Travel Planning Agents  
   https://arxiv.org/abs/2606.01046

8. Qi et al. — TREK: A Travel Reasoning and Evaluation Kit for LLM Agents in Complex Trip Planning  
   https://arxiv.org/abs/2607.26977
