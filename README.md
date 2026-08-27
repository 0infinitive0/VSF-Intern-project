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
- **Đặt phòng & thanh toán** — giữ chỗ phòng (room hold), thanh toán qua **VNPay**, xác nhận và **gửi email** (Brevo). Xem [`docs/architecture/booking_and_payment_workflow_vi.md`](./docs/architecture/booking_and_payment_workflow_vi.md).
- **Xác thực người dùng** — Supabase Auth (khách vãng lai dùng anonymous JWT), lịch sử chat theo từng user.
- **Web UI đầy đủ** — ChatPanel + ItineraryPanel, chọn khách sạn, suggestion chips.
- **Admin console** — quản lý khách sạn/phòng/giá, đơn đặt phòng, danh mục tiện nghi, embedding & pipeline (`/api/v1/admin/*`, `frontend/src/admin/`).

## 🧱 Cấu trúc dự án

```
├── backend/              # 🐍 FastAPI + LangGraph + AI Agent
│   ├── src/
│   │   ├── agents/       #    LangGraph: graph, state, routing, supervisor
│   │   │   └── graph/
│   │   │       ├── nodes/  #    Node functions (14 nodes: load_context, …, respond)
│   │   │       └── tools/  #    Agent tools (select_hotel, recommend_hotels, …)
│   │   ├── api/          #    Public endpoints (routes.py, streaming.py) + admin/ (console API)
│   │   ├── services/     #    Business logic (LLM, supabase_search, vector_store,
│   │   │                 #      trip_scheduler, trip_intake, itinerary_reuse,
│   │   │                 #      booking_service, payment_service, vnpay_service, email_service, …)
│   │   ├── domain/       #    Pure state / validation / constraints (imports nothing above)
│   │   ├── auth/         #    Supabase JWT verification (anonymous + permanent)
│   │   ├── guardrails/   #    Deterministic pre-model guards (jailbreak detection)
│   │   ├── clients/      #    Supabase client
│   │   ├── models/       #    Pydantic schemas
│   │   ├── i18n/         #    Translation catalog loader (catalogs in backend/locales/)
│   │   ├── airflow/      #    Airflow ETL (attraction + hotel pipelines)
│   │   ├── config.py     #    Settings
│   │   └── main.py       #    App entry point
│   ├── tests/            #    pytest suite (~100 files)
│   ├── scripts/          #    poc_trip_planner CLI, database_schema.sql, migrations/, sync/embedding utils
│   ├── locales/          #    gettext .po/.mo catalogs (vi, en)
│   ├── requirements.txt
│   ├── Makefile          #    run / test / lint / format / typecheck
│   └── Dockerfile
├── frontend/             # ⚛️ React 19 + Vite 8 + Tailwind 4 (+ i18next)
│   ├── src/              #    UI components, chat session logic, API client
│   ├── src/admin/        #    Admin console SPA (login, hotels, orders, pipelines, overview)
│   ├── mock/             #    Mock server (npm run mock)
│   ├── nginx.conf        #    Serving built assets
│   └── Dockerfile
├── data/                 # 📦 Dữ liệu thô nguồn (agoda, booking, …) — git-ignored
├── docs/                 # 📚 Tài liệu: architecture, setup, design, BRD, proposals
├── eval/                 # 📊 RAGAS evaluation harness
├── plans/                # 🗂️ Implementation plans (dated, phase-by-phase)
├── .github/workflows/    # ⚡ CI/CD
├── docker-compose.yml    # 🐙 Backend + frontend (+ profile local-llm)
├── docker-compose.staging.yml
├── Caddyfile             # Proxy cho production (Caddyfile.swagger-debug: deploy toggle)
└── babel.cfg             # pybabel message extraction (backend/src/**.py)
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
| `POST` | `/api/v1/planner_chat` · `/planner_chat/stream` | Lượt chat chính (JSON hoặc SSE), trả `PlannerChatResponse` |
| `POST` | `/api/v1/hotels/select` · `/hotels/change` | Chọn / đổi khách sạn |
| `GET` | `/api/v1/chat/{session_id}/plan` · `/restore` | Lấy lịch trình / khôi phục hội thoại |
| `DELETE` | `/api/v1/chat/{session_id}` | Reset / kết thúc session |
| `POST` | `/api/v1/bookings` · `/bookings/{id}/confirm` · `/cancel` | Giữ chỗ / xác nhận / huỷ đặt phòng |
| `GET`/`POST` | `/api/v1/payments/vnpay` · `/payments/vnpay/ipn` | Tạo phiên thanh toán VNPay & nhận IPN |
| `*` | `/api/v1/admin/*` | Admin console (yêu cầu quyền admin) |

Toàn bộ hợp đồng (kèm SSE, auth, các endpoint chi tiết): [`docs/chat_api_contract.md`](./docs/chat_api_contract.md).

## 🧪 Kiểm thử

```bash
cd backend
# Full suite
pytest tests -q

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

> ⚠️ **Hiện đang lỗi:** `src/cli/terminal_chat.py` vẫn import `process_chat_turn` đã bị xoá
> sau khi chuyển sang LangGraph — chạy sẽ `ImportError`. Xem `ARCHITECTURE.md` § Known debt.
> Dùng Web UI cho tới khi CLI được port sang `build_graph`.

Lệnh ví dụ (khi CLI hoạt động):
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