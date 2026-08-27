# VSF Trip Planner — Local Development Setup

**This guide is for running the stack locally to develop against it.** The live
application is deployed at `⟨PRODUCTION_URL⟩` (EC2 + Docker Compose behind Caddy) —
to deploy, roll back, read logs, or operate that system, use
[`../ops/deployment-runbook.md`](../ops/deployment-runbook.md), not this guide.

Local stack: FastAPI backend (`backend/`), React + Vite frontend (`frontend/`),
Supabase (Postgres + pgvector — shared with the deployed app), Qdrant
(hotel/attraction vectors), and an LLM + embedding provider.

> **Backend paths:** all backend commands run from `backend/`. The repo is split
> `backend/` · `frontend/` · `eval/` · `docs/` · `plans/` since the reorg — there is
> no importable `src/` at the repo root.

---

## Prerequisites

- **Git** (to clone the repository)
- **Python 3.11+** with `pip`
- **Node.js 20+** and `npm`
- **Docker Desktop** (or Docker Engine + Docker Compose) — for the full stack, Qdrant, and (optionally) local Ollama
- **An LLM + embedding provider.** Default is **Cloudflare Workers AI** (`LLM_PROVIDER=cloudflare`,
  `EMBEDDING_PROVIDER=cloudflare`, `EMBEDDING_MODEL=@cf/baai/bge-m3`) — see `backend/.env.example`.
  Local **Ollama** (`llama3.1` + `bge-m3`) also works; OpenAI / OpenRouter / Google are supported too.
  The embedding **model** is locked to `bge-m3` (1024-dim) — only *where* it runs is swappable.
- **Resources:** if you run Ollama locally, allocate **≥ 8 GB RAM** to Docker (`llama3.1` ≈ 4.7 GB, `bge-m3` ≈ 0.55 GB).

---

## Quick Start (Recommended for Development)

### Step 1 — Clone the repository

```bash
git clone https://github.com/0infinitive0/VSF-Intern-project.git
cd VSF-Intern-project
```

### Step 2 — Configure environment variables

```bash
cd backend
cp .env.example .env
# Open backend/.env and fill in:
#   SUPABASE_URL and SUPABASE_SERVICE_KEY   (required for hotel/attraction search)
#   SUPABASE_JWT_SECRET                     (required to verify auth tokens; AUTH_REQUIRED defaults false)
#   LLM_PROVIDER / LLM_MODEL / LLM_API_KEY  (default: cloudflare — see backend/.env.example)
#   EMBEDDING_PROVIDER / EMBEDDING_MODEL    (default: cloudflare / @cf/baai/bge-m3; model locked to bge-m3)
#   LLM_USE_RESPONSES_API / LLM_REASONING_SUMMARY — both off by default; leave them
#     off unless you want the OpenAI Responses API transport. Rationale is in .env.example.
#   VNPAY_* / BREVO_API_KEY / BREVO_FROM_EMAIL — only for the booking + payment + email flow
```

### Step 3 — Start the backend

```bash
cd backend        # all backend commands run from here

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

### Step 5 — (Optional) Start local Ollama

Only if you set `LLM_PROVIDER=ollama` / `EMBEDDING_PROVIDER=ollama` instead of the
Cloudflare default. Ollama must be running with the models pulled:

```bash
ollama pull bge-m3    # Embedding model (~550 MB)
ollama pull llama3.1  # Chat model (~4.7 GB)
```

> `EMBEDDING_MODEL` stays `bge-m3` (1024-dim) whatever the provider — switching the
> model, not the host, breaks similarity search against the existing vectors.
> Note: an `EMBEDDING_PROVIDER` value exported in your OS shell overrides `backend/.env`
> (pydantic-settings precedence) — `unset EMBEDDING_PROVIDER` if that surprises you.

---

## Full Stack via Docker Compose

```bash
# From the repo root. Cloud LLM (default): backend + frontend only.
docker compose up

# With local Ollama (adds ollama + a one-shot model pull of llama3.1 + bge-m3):
docker compose --profile local-llm up
```

Services after `docker compose up`:

| Service | URL | Notes |
|---------|-----|-------|
| FastAPI backend | http://localhost:8000 | |
| React frontend | http://localhost:5173 | in compose since the reorg |
| Ollama API | http://localhost:11434 | only with `--profile local-llm` |

Qdrant is **not** in `docker-compose.yml` — it is an external/managed instance
addressed by `QDRANT_URL` (default `http://localhost:6333`); run it yourself if you
need local hotel-vector search.

---

## Environment Matrix

| Setting | Local dev (default) | Local dev (Ollama) | Deployed (cloud) |
|---------|--------------------|--------------------|------------------|
| `LLM_PROVIDER` | `cloudflare` | `ollama` | `cloudflare` / `openai` / `openrouter` |
| `LLM_MODEL` | Cloudflare 70B/8B two-tier | `llama3.1` | per provider |
| `EMBEDDING_PROVIDER` | `cloudflare` | `ollama` | `cloudflare` |
| `EMBEDDING_MODEL` | `@cf/baai/bge-m3` | `bge-m3` | `@cf/baai/bge-m3` (⚠️ model locked, 1024-dim) |
| Frontend | Vite dev (5173) or compose | same | built assets behind Caddy |
| Ollama required? | No | Yes (both models) | No |

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
cd backend

# Full test suite (~100 files)
pytest tests -q

# API-layer tests only
pytest tests/test_api/ -q

# Lint on source files
ruff check src/
```

---

## Terminal CLI (Alternative to Web UI)

```bash
cd backend        # with the virtual environment active
python -m scripts.poc_trip_planner
```

> ⚠️ **Currently broken.** `src/cli/terminal_chat.py` still imports `process_chat_turn`,
> which was deleted in the LangGraph cutover, so the CLI raises `ImportError` on start.
> Use the Web UI until it is ported onto `build_graph`. See `ARCHITECTURE.md` § Known debt.

Conversation commands (once the CLI works again):
- **New trip:** *"Tôi muốn đi Đà Nẵng 3 ngày 2 người thích lịch sử"*
- **Modify plan:** *"Đổi khách sạn sang Caravelle Saigon"*
- **Finalize:** *"Chốt lịch trình"*
- **Exit:** `exit`, `quit`, or `q`

---

## Airflow Data Pipeline (Advanced)

```bash
cd backend/src/airflow
echo -e "AIRFLOW_UID=$(id -u)\nFERNET_KEY=$(python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')" > .env
docker compose up airflow-init   # First-time init
docker compose up -d
```

`.env` isn't checked in (it's a local secret, git-ignored) and `env_file: .env`
in `docker-compose.yaml` fails to start if it's missing -- the line above
generates one. The DAG containers only get real Supabase credentials if you
run with `ENV_FILE_PATH=../../.env docker compose up -d` instead (pointing
`env_file` at this repo's own `backend/.env`, which already has them) --
without that, DAG tasks that touch Supabase fail with
`Missing SUPABASE_URL or SUPABASE_SERVICE_KEY` (verified live).

Access Airflow UI (and its REST API) at **http://localhost:8088** (user:
`airflow`, password: `airflow`) -- the compose file maps the api-server's
container port 8080 to host port **8088**, not 8080.

Airflow runs in its own compose stack, on its own Docker network, separate
from the main app's `docker-compose.yml`. The admin backend (Phase 13,
`src/services/airflow_client.py`) reaches it via `AIRFLOW_API_BASE` in
`backend/.env` -- see that file's own comments for the dev/staging/prod
options; the default (`http://host.docker.internal:8088`) works out of the
box for both stacks running on the same macOS/Windows dev machine.

Every DAG starts **paused** on first parse
(`AIRFLOW__CORE__DAGS_ARE_PAUSED_AT_CREATION: true`) -- a manually triggered
run on a paused DAG stays `queued` forever until it's unpaused (verified
live). The admin trigger endpoint (Phase 15) unpauses automatically; a raw
`curl`/UI trigger during manual testing needs an explicit unpause first.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `POST /api/v1/chat/session` returns CORS error | Check `CORS_ORIGINS` in `.env` includes `http://localhost:5173` |
| LLM call times out after ~30 s | Raise proxy timeout to 120 s; or switch to `LLM_PROVIDER=openai` |
| `ollama pull` fails (disk full) | `llama3.1` needs ~4.7 GB free; use the Cloudflare/cloud provider instead |
| Qdrant connection refused | Qdrant is not in `docker-compose.yml` — start your own at `QDRANT_URL` (default `http://localhost:6333`) |
| Embedding provider isn't what `backend/.env` says | An OS-shell `EMBEDDING_PROVIDER` overrides the file — `unset EMBEDDING_PROVIDER` |
| `pip install -r requirements.txt` fails | Ensure Python 3.11+ and a fresh venv |
