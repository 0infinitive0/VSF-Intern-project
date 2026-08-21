# VSF Project Documentation Index

Welcome to the **VSF Trip Planner AI Agent** documentation. This directory is organized into the following sections:

## 📐 Architecture & Specifications (`docs/architecture/`)
* **[Agent Workflow & Semantic Search Stack](file:///d:/Git%20repo/vsf-project/docs/architecture/agent_workflow_and_semantic_search_stack.md)**: Main technical specification for the agent loop, candidate hydration, deterministic scheduling policies, input/output contracts, and proposed 5-agent LangGraph extension.
* **[Data Dictionary](file:///d:/Git%20repo/vsf-project/docs/architecture/data_dictionary.md)**: Comprehensive schema definitions for all database tables (`destinations`, `hotels`, `rooms`, `attractions`, `itineraries`, `itinerary_items`, `events`).
* **[Database ERD](file:///d:/Git%20repo/vsf-project/docs/architecture/database_erd.md)**: Relational entity-relationship diagram and foreign key relationships.
* **[Data Pipeline Flow](file:///d:/Git%20repo/vsf-project/docs/architecture/data_pipeline_flow.md)**: Airflow ETL data pipeline specs for OSM, Booking.com, and Agoda producers.
* **[LangGraph Orchestrator — Tổng thể](architecture/langgraph_orchestrator_vi.md)** (tiếng Việt): Sơ đồ 14 node, `TravelGraphState` vs `TravelState`, checkpointer, bảng tra cứu nhanh (edge, counter, writer).
* **[LangGraph Orchestrator — Chi tiết](architecture/langgraph_orchestrator_detail_vi.md)** (tiếng Việt): Patch pipeline, supervisor & delegation, worker nodes, subgraph, node contracts, `respond`, `interrupt()`, streaming.
* **[Đặt phòng & Thanh toán VNPay](architecture/booking_and_payment_workflow_vi.md)** (tiếng Việt): Luồng giữ phòng → thanh toán VNPay → xác nhận → email, mô hình dữ liệu, sơ đồ Mermaid, và nhật ký các sự cố đã xử lý.

## 🚀 Setup & Operations (`docs/setup/`)
* **[Setup Guide](file:///d:/Git%20repo/vsf-project/docs/setup/SETUP_GUIDE.md)**: Step-by-step instructions for initializing Docker Compose, Airflow, PostgreSQL, Adminer, and the Real-Time Dashboard.

## 🎨 Product & UI Design (`docs/design/`)
* **[Design Proposal](file:///d:/Git%20repo/vsf-project/docs/design/design_proposal.md)**: Product features, UX wireframes, and design rationale.
* Visual Wireframes & Diagrams:
  * [Workflow & Tech Stack](file:///d:/Git%20repo/vsf-project/docs/design/WORKFLOW_TECHSTACK.png)
  * [Mobile Wireframe](file:///d:/Git%20repo/vsf-project/docs/design/wireframe.png)
  * [Web Wireframe](file:///d:/Git%20repo/vsf-project/docs/design/wireframe_web.png)

## 🧪 RAG Evaluation (`eval/`)
* **[RAGAS evaluation harness](../eval/README.md)**: Retrieval-quality and end-to-end grounding measurement for the trip-planner RAG pipeline, isolated from the backend runtime. See `eval/datasets/README.md` for the golden-set authoring log and `eval/results/` for the latest report.

## 💡 Feature Proposals & RFCs (`docs/proposals/`)
* **[Itinerary Embedding Reuse (v2)](file:///d:/Git%20repo/vsf-project/docs/proposals/itinerary-embedding-reuse-v2.md)**: Tier 1 BGE-M3 fingerprint matching and template reuse specification.

## 📄 Business Requirements (`docs/brd/`)
* **[BRD V-OTA AI Chat 2026](file:///d:/Git%20repo/vsf-project/docs/brd/BRD_V-OTA_AI-Chat_VSF2026_2.pdf)**: Original Business Requirements Document (PDF).

## 📚 Learning & Pattern Reference (`docs/guide/`)
* Hands-on course chapters, anti-patterns, DevOps, cost management, and LangGraph guides.

## 📦 Archive (`docs/archive/`)
* **[Sprint 1 Weekly Plan](file:///d:/Git%20repo/vsf-project/docs/archive/sprint1_weekly_plan.md)**: Historical task breakdown for initial data pipeline sprint.
