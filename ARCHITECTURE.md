# Architecture Document

## System Overview

[Tóm tắt 2-3 câu về kiến trúc hệ thống]

## Architecture Diagram

```mermaid
graph TB
    subgraph Frontend
        UI[React/Next.js UI]
    end

    subgraph Backend[FastAPI Backend]
        API[API Routes]
        Agent[LangGraph Agent]
        LLM[LLM Service]
        Tools[Agent Tools]
    end

    subgraph Data[Data Layer]
        DB[(Database)]
        Vector[Vector Store]
    end

    UI -->|HTTP/REST| API
    API --> Agent
    Agent --> LLM
    Agent --> Tools
    Agent --> Vector
    Tools --> DB
    API --> DB
```

## Components

### 1. Frontend (React/Next.js)
- **Purpose:** [mô tả]
- **Key Features:** [danh sách]
- **State Management:** [approach]

### 2. Backend (FastAPI)
- **Purpose:** [mô tả]
- **API Design:** RESTful
- **Authentication:** [JWT/None]

### 3. AI Agent (LangGraph)
- **Agent Type:** [ReAct / Plan-and-Execute / Custom]
- **State:** [mô tả state schema]
- **Nodes:** [danh sách nodes]
- **Tools:** [danh sách tools]
- **Flow:**

```mermaid
graph LR
    START --> A[Node A]
    A --> B{Decision}
    B -->|Yes| C[Node C]
    B -->|No| D[Node D]
    C --> E[END]
    D --> E
```

### 4. Database
- **Type:** PostgreSQL
- **Tables:** `destinations`, `hotels`, `rooms`, `room_prices`, `attractions`, `events`, `sessions`, `chat_messages`, `itineraries`, `itinerary_items`
- **Schema management:** Hand-written SQL in `scripts/database_schema.sql`

### 4.1. Data Pipelines
- **Airflow stack:** `src/airflow/docker-compose.yaml`
- **Attraction producers:** `osm_dag.py`, `ota_dag.py`, `google_maps_dag.py`, `hotel_nearby_dag.py`
- **Hotel producer:** `hotel_dag.py` orchestrates `hotel_pipeline.py` stages: extract, validate, normalize, dedupe, load, quality check
- **Hotel input data:** `data/agoda.json` and `data/booking.json`, mounted read-only into Airflow at `/opt/airflow/data`
- **Hotel schema convention:** one `hotels` row per `(source_platform, source_hotel_id)` OTA listing; cross-OTA physical-property merge is deferred

### 5. Vector Store
- **Type:** [ChromaDB / FAISS / Pinecone]
- **Embeddings:** [model]
- **Purpose:** [RAG / similarity search]

## Data Flow

1. User gửi request từ Frontend
2. API route nhận và validate input
3. Agent xử lý qua LangGraph pipeline
4. LLM generate response
5. Tools thực thi actions (nếu cần)
6. Response trả về Frontend

## Deployment Architecture

```mermaid
graph LR
    subgraph Docker
        FE[Frontend Container]
        BE[Backend Container]
        DB_C[Database Container]
    end
    FE --> BE --> DB_C
```

## Security

- API keys stored in `.env` (never commit)
- Input validation via Pydantic
- Rate limiting on API endpoints
- CORS configured for frontend domain

## Design Decisions

| Decision | Choice | Reason |
|----------|--------|--------|
| Framework | FastAPI | Async, auto-docs, type-safe |
| Agent | LangGraph | Flexible state management |
| Database | [choice] | [reason] |
| Frontend | Next.js | [reason] |
