# VSF Project Documentation Index

Documentation for the **VSF Trip Planner AI Agent** (a.k.a. V-OTA AI Chat).
Files tagged **(vi)** are written in Vietnamese.

Some documents live outside this folder:

| Document | Location | Use for |
|---|---|---|
| System architecture overview | [`../ARCHITECTURE.md`](../ARCHITECTURE.md) | Infrastructure outside the LangGraph layer — React, FastAPI, Supabase, Qdrant, Airflow |
| Repository README | [`../README.md`](../README.md) | Project pitch, quick start, top-level layout |
| Agent/contributor guide | [`../AGENTS.md`](../AGENTS.md) | Conventions for automated contributors |
| RAG evaluation harness | [`../eval/README.md`](../eval/README.md) | RAGAS retrieval-quality and end-to-end grounding measurement |
| Implementation plans | [`../plans/`](../plans/) | Dated, phase-by-phase work plans and decision records |

---

## 🚀 Setup & operations — `setup/`

* **[Setup Guide](setup/SETUP_GUIDE.md)** — running the full stack (FastAPI backend, React + Vite frontend, Qdrant, Ollama) via Docker Compose, plus Airflow / PostgreSQL / Adminer.

## 📐 Architecture & specifications — `architecture/`

* **[Agent Workflow & Semantic Search Stack](architecture/agent_workflow_and_semantic_search_stack.md)** — source of truth for the agent loop: candidate hydration, deterministic scheduling policies, input/output contracts, proposed 5-agent LangGraph extension. ([vi](architecture/agent_workflow_and_semantic_search_stack_vi.md))
* **[LangGraph Orchestrator — Tổng thể](architecture/langgraph_orchestrator_vi.md)** (vi) — the 14-node graph: `TravelGraphState` vs `TravelState`, checkpointer, quick-reference tables for edges / counters / writers.
* **[LangGraph Orchestrator — Chi tiết](architecture/langgraph_orchestrator_detail_vi.md)** (vi) — patch pipeline, supervisor & delegation, worker nodes, subgraphs, node contracts, `respond`, `interrupt()`, streaming.
* **[Chatbot Capabilities & Happy Path](architecture/chatbot-capabilities-and-happy-path-vi.md)** (vi) — exactly what the chatbot can and cannot do per the code on `main`, with an end-to-end happy-case walkthrough.
* **[Đặt phòng & Thanh toán VNPay](architecture/booking_and_payment_workflow_vi.md)** (vi) — room-hold → VNPay payment → confirmation → email flow, data model, Mermaid diagrams, and an incident log.
* **[Data Dictionary](architecture/data_dictionary.md)** (vi) — column-level schema for every PostgreSQL table and the Qdrant collections.
* **[Database ERD](architecture/database_erd.md)** (vi) — full entity-relationship diagram, all fields of all 10 application tables plus the Supabase-managed `auth.users`.
* **[Data Pipeline Flow](architecture/data_pipeline_flow.md)** (vi) — Airflow ETL Mermaid diagram for the Booking.com, Agoda, and Google Places producers.

## 🔌 API contract

* **[Chat API Contract](chat_api_contract.md)** — frozen public contract for the chat/planner endpoints (REST + SSE streaming). Referenced directly from backend and frontend code, so it stays at the docs root.

## 🎨 Product & UI design — `design/` and `brd/`

* **[BRD V-OTA AI Chat 2026](brd/BRD_V-OTA_AI-Chat_VSF2026_2.pdf)** — original Business Requirements Document (PDF, v1.2, 2026-07-20).
* **[BRD Requirements & Wireframe Prompts](design/brd-requirements-and-wireframe-prompts.md)** (vi) — traceable BR/FR requirement table distilled from the BRD, with wireframe-generation prompts.
* **[Design Proposal](design/design_proposal.md)** (vi) — proposed tech stack, processing flow, and wireframe rationale.
* Diagrams & wireframes: [Workflow & Tech Stack](design/WORKFLOW_TECHSTACK.png) · [Mobile wireframe](design/wireframe.png) · [Web wireframe](design/wireframe_web.png)

## 💡 Proposals & RFCs — `proposals/`

* **[Itinerary Embedding Reuse (v2)](proposals/itinerary-embedding-reuse-v2.md)** — BGE-M3 fingerprint matching and finalized-itinerary template reuse. Status: proposed for review.

## 📚 Guides — `guide/`

* **[Eval Harness — Hướng dẫn kiểm thử](guide/eval-harness-testing-guide.md)** (vi) — how to run the `eval/` RAGAS harness (Layer 1 retrieval, Layer 2 end-to-end), embedding-provider notes.

## 🧪 QA test reports — `test-report/`

OTA customer-journey QA runs (persona-based end-to-end tests of the deployed app):

* [2026-08-18 — Family persona, Nha Trang](test-report/ota-customer-tester-report-2026-08-18-family-nhatrang.md)
* [2026-08-18 — Post-rebuild pass](test-report/ota-customer-tester-report-2026-08-18-post-rebuild.md)
* [2026-08-21 — Honeymoon persona, Nha Trang](test-report/ota-customer-tester-report-2026-08-21-honeymoon-nhatrang.md) *(not yet committed)*

## 🖥️ Presentation — `slide/`

* **[index.html](slide/index.html)** — the defense/pitch slide deck (`script.js`, `styles.css`); `variant-*.html` are alternative visual treatments.
* **[ANSWERS.md](slide/ANSWERS.md)** (vi) — Q&A pairs covering the technical-appendix slides (13–42) for quick reference during the defense.

## 📦 Archive — `archive/`

Historical documents, kept for reference only — not maintained.

* **[Sprint 1 Weekly Plan](archive/sprint1_weekly_plan.md)** (vi) — task breakdown for the initial data-pipeline sprint.
