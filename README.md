# 🧳 VSF Trip Planner — AI Agent

AI Agent lập kế hoạch du lịch **đa lượt (multi-turn)** cho khách du lịch Việt Nam. Người dùng trò chuyện bằng tiếng Việt tự nhiên; hệ thống thu thập nhu cầu, tìm kiếm địa điểm một cách ngữ nghĩa (RAG), lập lịch trình tối ưu khoảng cách/thời gian, và tái sử dụng lịch trình mẫu (Tier 1 Cache).

Kiến trúc gồm **LangGraph Orchestrator**, **FastAPI Backend**, **Supabase (PostgreSQL + pgvector)**, **React + Vite Frontend** và **Airflow Data Pipeline**.

> 📐 Xem thêm: [ARCHITECTURE.md](./ARCHITECTURE.md) · [Setup Guide](./docs/setup/SETUP_GUIDE.md) · [Docs Index](./docs/README.md)

---

## ✨ Tính năng

- **Trò chuyện đa lượt tiếng Việt** — thu thập nhu cầu (điểm đến, số ngày, số người, sở thích) bằng câu hỏi làm rõ tự động.
- **Tìm kiếm ngữ nghĩa (RAG)** — retriever điểm tham quan & khách sạn qua Supabase `pgvector` và Qdrant.
- **Lập lịch tự động** — engine quyết định (`trip_scheduler`) phân bổ thời gian, cụm theo bán kính khoảng cách, chèn bữa ăn/nghỉ ngơi.
- **Tái sử dụng lịch trình (Tier 1 Cache)** — fingerprint BGE-M3 (`>88%` tương đồng) để lấy lại template gần giống.
- **Chỉnh sửa & chốt lịch** — đổi khách sạn, sửa itinerary, chốt lịch trình.
- **Web UI đầy đủ** — ChatPanel + ItineraryPanel, chọn khách sạn, suggestion chips.
- **CLI terminal** — dùng nhanh không cần UI.

## 🧱 Cấu trúc dự án

```
├── backend/              # 🐍 FastAPI + LangGraph + AI Agent
│   ├── src/
│   │   ├── agents/       #    LangGraph: graph, state, routing_decision, supervisor
│   │   │   ├── nodes/    #      Node functions (intake, …)
│   │   │   └── tools/    #      Agent tools (select_hotel, recommend_hotels, …)
│   │   ├── api/          #    API endpoints (routes.py)
│   │   ├── services/     #    Business logic (LLM, supabase_search, vector_store,
│   │   │                 #      trip_scheduler, trip_intake, itinerary_reuse, …)
│   │   ├── models/       #    Pydantic schemas
│   │   ├── i18n/         #    Translation catalogs
│   │   ├── airflow/      #    Airflow ETL (attraction + hotel pipelines)
│   │   ├── config.py     #    Settings
│   │   └── main.py       #    App entry point
│   ├── tests/            #    pytest suite
│   ├── scripts/          #    Sync/embedding utilities
│   ├── requirements.txt
│   ├── Makefile          #    run / test / lint / format / typecheck
│   └── Dockerfile
├── frontend/             # ⚛️ React 19 + Vite 8 + Tailwind 4 (+ i18next)
│   ├── src/              #    UI components, chat session logic, API client
│   ├── mock/             #    Mock server (npm run mock)
│   ├── nginx.conf        #    Serving built assets
│   └── Dockerfile
├── data/                 # 📦 Dữ liệu thô nguồn (agoda, booking, …)
├── docs/                 # 📚 Tài liệu: architecture, setup, design, BRD, proposals
├── supabase/             # 🗄️ SQL schema & queries
├── eval/                 # 📊 Kết quả đánh giá
├── tests/                # 🧪 Test cấp repo (kế thừa)
├── scripts/              # 🔌 Scripts cấp repo
├── .github/workflows/    # ⚡ CI/CD
├── docker-compose.yml    # 🐙 Backend + frontend (+ profile local-llm)
└── Caddyfile             # Proxy cho production
```

## 🚀 Quick Start

### Yêu cầu

- **Python 3.11+** · **Node.js 20+** & npm · **Docker Desktop** (Ollama/full stack)
- Tối thiểu ~8 GB RAM phân bổ cho Docker nếu dùng LLM local (llama3.1 ~4.7 GB)

### Bước 1 — Cấu hình backend

```bash
cp backend/.env.example backend/.env
# Mở backend/.env và điền:
#   SUPABASE_URL / SUPABASE_SERVICE_KEY   (bắt buộc để search khách sạn/điểm tham quan)
#   LLM_PROVIDER / LLM_MODEL / LLM_API_KEY (nếu dùng cloud LLM)
```

### Bước 2 — Chạy backend (FastAPI)

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate          # macOS/Linux
pip install -r requirements.txt
uvicorn src.main:app --reload --port 8000
# → API docs: http://localhost:8000/docs
# → Health:   http://localhost:8000/health
```

### Bước 3 — Chạy frontend (React + Vite)

Mở **terminal mới** (giữ backend chạy):

```bash
cd frontend
npm install
npm run dev
# → Chat UI: http://localhost:5173
cp .env.example .env.local        # để trống VITE_API_BASE khi dùng proxy dev
```

> Vite tự proxy `/api → http://localhost:8000` trong dev — không cần cấu hình CORS.

### Bước 4 — Ollama (nếu `LLM_PROVIDER=ollama` — mặc định)

```bash
ollama pull bge-m3    # Embedding ~550 MB — bắt buộc mọi môi trường
ollama pull llama3.1  # Chat ~4.7 GB — chỉ cần khi dùng LLM local
```

> **Mẹo:** Trên máy RAM thấp hoặc bản deploy cloud, chuyển sang cloud LLM trong `.env`:
> ```
> LLM_PROVIDER=openai
> LLM_MODEL=gpt-4o-mini
> LLM_API_KEY=sk-proj-...
> ```
> ⚠️ Embedding luôn dùng Ollama `bge-m3` bất kể `LLM_PROVIDER` — vector dùng cố định `1024-dim`.

### Chạy full stack bằng Docker Compose

```bash
# Cloud LLM (mặc định, backend + frontend):
docker compose up

# Local Ollama (kéo thêm bge-m3 + llama3.1):
docker compose --profile local-llm up
```

| Service | URL |
|---------|-----|
| FastAPI backend | http://localhost:8000 |
| React frontend | http://localhost:5173 |
| Ollama API | http://localhost:11434 |

## 🌐 Kịch bản môi trường

| Setting | Local dev | Deployed (cloud) |
|---------|-----------|------------------|
| `LLM_PROVIDER` | `ollama` | `openai` / `openrouter` |
| `LLM_MODEL` | `llama3.1` | `gpt-4o-mini` hoặc OpenRouter model id |
| `EMBEDDING_MODEL` | `bge-m3` | `bge-m3` (⚠️ cố định — đừng đổi) |
| Frontend | Vite dev server (5173) | Build assets qua Nginx |
| Ollama cần không? | Có (cả 2 model) | Có (chỉ bge-m3; chat model dùng cloud) |

## 🔌 API

| Method | Endpoint | Mô tả |
|--------|----------|-------|
| `POST` | `/api/v1/chat/session` | Tạo session, trả `{session_id, created_at}` |
| `POST` | `/api/v1/planner_chat` | Lượt chat chính, trả `PlannerChatResponse` |
| `GET` | `/api/v1/chat/{session_id}/plan` | Lấy lịch trình hiện tại |
| `DELETE` | `/api/v1/chat/{session_id}` | Reset / kết thúc session |

Tài liệu chi tiết: [`docs/chat_api_contract.md`](./docs/chat_api_contract.md).

## 🧪 Kiểm thử

```bash
cd backend
# Full suite (bỏ qua test live Qdrant schema)
pytest tests -q --ignore=tests/test_qdrant_schema.py

# Chỉ test API layer
pytest tests/test_api/ -q

# Lint
ruff check src/

# Hoặc dùng Makefile
make test lint
```

## 🖥 CLI (thay cho Web UI)

```bash
cd backend
python -m scripts.poc_trip_planner
```

Lệnh ví dụ:
- **Chuyến mới:** `"Tôi muốn đi Đà Nẵng 3 ngày 2 người thích lịch sử"`
- **Sửa kế hoạch:** `"Đổi khách sạn sang Caravelle Saigon"`
- **Chốt:** `"Chốt lịch trình"` · **Thoát:** `exit` / `quit` / `q`

## 📦 Data Pipeline (Airflow)

```bash
cd backend/src/airflow
docker compose up airflow-init   # Lần đầu khởi tạo
docker compose up -d
```

Airflow UI tại http://localhost:8080 (user/pass: `airflow` / `airflow`).

## 📚 Tài liệu liên quan

- [ARCHITECTURE.md](./ARCHITECTURE.md) — tổng quan kiến trúc & mermaid diagrams
- [docs/setup/SETUP_GUIDE.md](./docs/setup/SETUP_GUIDE.md) — hướng dẫn setup chi tiết
- [docs/README.md](./docs/README.md) — chỉ mục tài liệu (architecture, design, BRD, proposals)
- [docs/brd/BRD_V-OTA_AI-Chat_VSF2026_2.pdf](./docs/brd/BRD_V-OTA_AI-Chat_VSF2026_2.pdf) — Business Requirements Document

## 🤝 Đóng góp

Nếu muốn đóng góp: fork repo, tạo nhánh feature, gửi Pull Request. Tuân theo quy tắc import một chiều (`api → agents → services → models`) để tránh circular dependency.

## 📄 License

MIT — sử dụng tự do cho mục đích giáo dục.