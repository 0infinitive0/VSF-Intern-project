# VSF Trip Planner — Setup Guide

Complete setup guide for running the full VSF Trip Planner stack: FastAPI backend,
React+Vite frontend, Qdrant vector store, and Ollama (local LLM).

---

## Prerequisites

- **Git** (to clone the repository)
- **Python 3.11+** with `pip`
- **Node.js 20+** and `npm`
- **Docker Desktop** (or Docker Engine + Docker Compose) — for Qdrant, Ollama, and the full stack
- **Resources:** Allocate at least **8 GB RAM** to Docker (Ollama + llama3.1 model is ~4.7 GB).
  On cloud deployments, set `LLM_PROVIDER=openai` to skip local LLM entirely.

---

## Quick Start (Recommended for Development)

### Step 1 — Clone the repository

```bash
git clone https://github.com/0infinitive0/VSF-Intern-project.git
cd VSF-Intern-project
```

### Step 2 — Configure environment variables

```bash
cp .env.example .env
# Open .env and fill in:
#   SUPABASE_URL and SUPABASE_SERVICE_KEY (required for hotel/attraction search)
#   LLM_PROVIDER / LLM_MODEL / LLM_API_KEY (if using cloud LLM — see .env.example)
#   LLM_USE_RESPONSES_API / LLM_REASONING_SUMMARY — both off by default; leave them
#     off unless you specifically want the OpenAI Responses API transport. Rationale
#     and constraints are in .env.example next to each variable.
#   AI_LOG_API_KEY (from BTC invite link)
```

### Step 3 — Start the backend

```bash
# Create and activate a Python virtual environment
python3.11 -m venv .venv
source .venv/bin/activate        # Linux / macOS
# .\.venv\Scripts\activate       # Windows PowerShell

# Install dependencies
pip install -r requirements.txt

# Start the FastAPI backend
uvicorn src.main:app --reload --port 8000
# → API docs: http://localhost:8000/docs
# → Health:   http://localhost:8000/health
```

### Step 4 — Start the React frontend

Open a **new terminal** (the backend must keep running):

```bash
cd frontend
npm install
npm run dev
# → Chat UI: http://localhost:5173
```

Vite automatically proxies `/api → http://localhost:8000` in development — no CORS
configuration needed.

### Step 5 — Start local Ollama (for local LLM)

If `LLM_PROVIDER=ollama` (the default), Ollama must be running and the models pulled:

```bash
ollama pull bge-m3    # Embedding model (~550 MB) — required in all environments
ollama pull llama3.1  # Chat model (~4.7 GB) — only needed for local LLM
```

> **Tip:** On low-RAM machines or cloud deployments, switch to a cloud provider:
>
> ```bash
> # In .env:
> LLM_PROVIDER=openai
> LLM_MODEL=gpt-4o-mini
> LLM_API_KEY=sk-proj-...
> ```
>
> Embeddings always use local Ollama `bge-m3` regardless of `LLM_PROVIDER`.

---

## Full Stack via Docker Compose

For a one-command start (backend + Qdrant + Ollama + model pull):

```bash
docker compose up
# First run pulls llama3.1 (~4.7 GB) and bge-m3 (~550 MB) — this takes a while.
# Subsequent starts reuse the cached models in ./data/ollama/.
```

The `frontend/` is **not** included in docker-compose — run it separately with
`npm run dev` (Step 4 above) pointing at `http://localhost:8000`.

Services exposed after `docker compose up`:

| Service | URL |
|---------|-----|
| FastAPI backend | http://localhost:8000 |
| Qdrant vector store | http://localhost:6333 |
| Ollama API | http://localhost:11434 |

---

## Environment Matrix

| Setting | Local dev | Deployed (cloud) |
|---------|-----------|-----------------|
| `LLM_PROVIDER` | `ollama` | `openai` / `openrouter` |
| `LLM_MODEL` | `llama3.1` | `gpt-4o-mini` or an OpenRouter model id |
| `EMBEDDING_PROVIDER` | `ollama` | `ollama` |
| `EMBEDDING_MODEL` | `bge-m3` | `bge-m3` (⚠️ do **not** change — vectors are locked to 1024 dim) |
| Frontend | `npm run dev` (Vite, port 5173) | Built assets — host TBD |
| Ollama required? | Yes (both models) | Yes (bge-m3 only; chat model is cloud) |

---

## Proxy Timeout Note

LLM calls (especially first-turn plan generation with llama3.1) can take up to **120 seconds**.
If you put a reverse proxy (nginx, Railway, etc.) in front of the backend, raise its
read/proxy timeout to at least 120 s, otherwise long turns will result in a gateway error.

---

## Session Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `SESSION_TTL_SECONDS` | `7200` | How long an idle session stays in memory (seconds) |
| `MAX_SESSIONS` | `200` | Hard cap on concurrent in-memory sessions |
| `DEBUG_TRIP_PLAN_FILE` | `false` | Write trip plan JSON to `debug/{session_id}/` (dev only) |

---

## Running Tests

```bash
# Full test suite (excluding live Qdrant schema tests)
pytest tests -q --ignore=tests/test_qdrant_schema.py

# API-layer tests only
pytest tests/test_api/ -q

# Lint on source files
ruff check src/
```

---

## Terminal CLI (Alternative to Web UI)

```bash
# With virtual environment active
python -m scripts.poc_trip_planner
```

Conversation commands:
- **New trip:** *"Tôi muốn đi Đà Nẵng 3 ngày 2 người thích lịch sử"*
- **Modify plan:** *"Đổi khách sạn sang Caravelle Saigon"*
- **Finalize:** *"Chốt lịch trình"*
- **Exit:** `exit`, `quit`, or `q`

---

## Airflow Data Pipeline (Advanced)

```bash
cd src/airflow
docker compose up airflow-init   # First-time init
docker compose up -d
```

Access Airflow UI at http://localhost:8080 (user: `airflow`, password: `airflow`).

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `POST /api/v1/chat/session` returns CORS error | Check `CORS_ORIGINS` in `.env` includes `http://localhost:5173` |
| LLM call times out after ~30 s | Raise proxy timeout to 120 s; or switch to `LLM_PROVIDER=openai` |
| `ollama pull` fails (disk full) | `llama3.1` needs ~4.7 GB free; use cloud LLM instead |
| Qdrant connection refused | Run `docker compose up qdrant` or start Qdrant manually |
| `pip install -r requirements.txt` fails | Ensure Python 3.11+ and a fresh venv |
