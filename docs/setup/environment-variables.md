# Environment Variable Reference

**Authoritative source:** `backend/src/config.py` (`Settings`). `backend/.env.example`
and root `.env.example` are copy-me templates — where they disagree with `config.py`,
`config.py` wins (noted below).

**No secret values appear in this file.** Each row lists the variable, what it does, its
default, and where to obtain it. Fill real values only in `backend/.env` /
root `.env`, which are git-ignored.

- **`backend/.env`** — the backend service (FastAPI, graph, all integrations).
- **root `.env`** — only `VITE_MAPBOX_TOKEN`, read by `docker-compose.yml` for the
  frontend build. The frontend dev server otherwise needs no env.
- Precedence: a variable exported in your **OS shell overrides the `.env` file**
  (pydantic-settings behavior) — a common "why isn't it using my `.env`?" surprise.

---

## App

| Variable | Purpose | Default |
|---|---|---|
| `APP_ENV` | `development` \| `production` \| `test`. | `development` |
| `APP_PORT` / `APP_HOST` | Bind address for uvicorn. | `8000` / `0.0.0.0` |
| `LOG_LEVEL` | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR`. | `INFO` |
| `CORS_ORIGINS` | Comma-separated allowed browser origins. Add the deployed frontend origin in production. | `http://localhost:3000,http://localhost:8082,http://localhost:5173` |

## Supabase (required)

| Variable | Purpose | Where to get it |
|---|---|---|
| `SUPABASE_URL` | Project URL. Also the JWKS host for JWT verification. **Required.** | Supabase dashboard → Settings → API → Project URL |
| `SUPABASE_SERVICE_KEY` | Service-role key for the Postgres/PostgREST client (server-side only, never in a browser). **Required.** | Supabase dashboard → Settings → API → `service_role` secret |
| `SUPABASE_JWT_SECRET` | **Leave blank for this project.** Legacy HS256 fallback for JWT verification — only for an older Supabase project without asymmetric signing keys. See [`../architecture/authentication.md`](../architecture/authentication.md). | Dashboard → Settings → API → JWT Settings (legacy projects only) |

## Chat LLM

Default provider is **Cloudflare Workers AI** (two-tier: 70B reasoning, 8B fast).
`config.py` still defaults `llm_provider` to `"ollama"`; the `.env.example` files set
`cloudflare` — set it explicitly in `backend/.env`.

| Variable | Purpose | Default (`config.py`) |
|---|---|---|
| `LLM_PROVIDER` | `cloudflare` \| `ollama` \| `openai` \| `openrouter` \| `google` \| `anthropic`. | `ollama` |
| `LLM_MODEL` | Main/reasoning model id for the provider. | `llama3.1` |
| `LLM_FAST_MODEL` | Cheaper model for quick tasks (slot-question rewrites, etc.). | `llama3.1` |
| `LLM_API_KEY` | API key for the chosen provider. | — |
| `LLM_API_BASE` | OpenAI-compatible base URL (Cloudflare / Mistral / self-hosted). | — |
| `OPENAI_API_KEY` / `OPENROUTER_API_KEY` | Alternate key slots read directly by some paths. | — |
| `CLOUDFLARE_ACCOUNT_ID` / `CLOUDFLARE_API_TOKEN` | Cloudflare Workers AI credentials. | — |
| `LLM_TEMPERATURE` | 0.0–2.0. Ignored by OpenAI reasoning models. | `0.3` |
| `LLM_REASONING_EFFORT` | `minimal`\|`low`\|`medium`\|`high` — OpenAI gpt-5/o1/o3/o4 only. | `low` |
| `LLM_USE_RESPONSES_API` | Route OpenAI reasoning-family calls through the Responses API. Set `false` to roll back (env change, not a deploy). | `true` |
| `LLM_REASONING_SUMMARY` | `off`\|`auto` — emit model reasoning summaries as `reasoning` SSE frames. Needs `LLM_USE_RESPONSES_API=true`. Always English. | `auto` (`.env.example`: `off`) |

**Provider API keys — where to get:** OpenAI `platform.openai.com`; OpenRouter
`openrouter.ai/keys`; Cloudflare dashboard → AI → Workers AI (API token with Workers AI
permission) + Account ID; Google AI Studio; Anthropic Console. Ollama = local, no key
(`OLLAMA_URL`).

## Embeddings

| Variable | Purpose | Default |
|---|---|---|
| `EMBEDDING_PROVIDER` | `cloudflare` \| `ollama` \| `openai` \| `openrouter` \| `google`. | `ollama` (`.env.example` root: `cloudflare`) |
| `EMBEDDING_MODEL` | **Must stay a `bge-m3` variant** (`bge-m3` for Ollama, `@cf/baai/bge-m3` for Cloudflare, `baai/bge-m3` for OpenRouter). 1024-dim. Switching to any other model breaks similarity search against the stored vectors. | `bge-m3` |
| `EMBEDDING_API_KEY` / `EMBEDDING_API_BASE` | Key + OpenAI-compatible base for hosted providers. | — |
| `OLLAMA_URL` | Ollama server for local LLM/embeddings. | `http://localhost:11434` |

## Vector store (Qdrant)

| Variable | Purpose | Default |
|---|---|---|
| `QDRANT_URL` | Qdrant instance for hotel/attraction/room vectors. Not in `docker-compose.yml` — run/point it yourself. | `http://localhost:6333` |
| `QDRANT_API_KEY` | Qdrant API key (managed instances). | — |

## LangGraph checkpointer

| Variable | Purpose | Default |
|---|---|---|
| `CHECKPOINTER_BACKEND` | `memory` (non-durable, lost on restart) \| `postgres` (survives restart). CLI/scripts always use `memory`. | `memory` |
| `CHECKPOINTER_DATABASE_URL` | Full Postgres DSN, required when `postgres`. For Supabase use the **Supavisor session-pooler** DSN (Settings → Database → Connection string → Session pooler) — *not* `db.<ref>.supabase.co` (IPv6-only, unreachable from Docker/EC2). | — |

## Session registry

| Variable | Purpose | Default |
|---|---|---|
| `SESSION_TTL_SECONDS` | Idle in-memory session lifetime. | `7200` |
| `MAX_SESSIONS` | Hard cap on concurrent in-memory sessions. | `200` |
| `SESSION_PERSISTENCE_ENABLED` | Persist session state + history to Supabase and rehydrate after eviction. `config.py` default is `true`; `.env.example` sets `false`. | `true` |
| `DEBUG_TRIP_PLAN_FILE` | Write trip-plan JSON to `debug/{session_id}/`. Never enable in production. | `false` |

## Graph behavior

| Variable | Purpose | Default |
|---|---|---|
| `TRIP_SUPERVISOR_ROUTER` | LLM supervisor proposes the route before the deterministic fallback. `false` = pure-regex routing (rollback, no deploy). | `true` |
| `JAILBREAK_GUARD_MODE` | `block` \| `log` \| `off` — handling of high-confidence jailbreak attempts pre-LLM. | `block` |
| `QA_CONTEXT_TOKEN_BUDGET` | Token ceiling on the transcript `qa_node` sends per ReAct hop. Cost control, not window limit. | `30000` |
| `CONTRACT_ENFORCEMENT_MODE` | `strict` (raises `ContractViolation` — dev/CI default) \| `log` (log at ERROR, continue — **set in production**). | `strict` |
| `AUTH_REQUIRED` | Reject session-scoped endpoints with no/invalid Supabase JWT. Flip to `true` only after the frontend sends `Authorization` everywhere. | `false` |

## Maps

| Variable | Purpose | Where to get it |
|---|---|---|
| `MAPBOX_ACCESS_TOKEN` | Backend Mapbox token (route/geocode calls). Secret — `backend/.env`. | Mapbox account → Access tokens |
| `VITE_MAPBOX_TOKEN` (root `.env`) | **Public** token (`pk.*`, URL-restricted on the Mapbox dashboard) baked into the frontend build. Blank → map shows an honest "unavailable" placeholder. | Mapbox account → Access tokens (public, restricted) |

## VNPay (booking payment)

| Variable | Purpose | Where to get it |
|---|---|---|
| `VNPAY_TMN_CODE` / `VNPAY_HASH_SECRET` | Merchant code + HMAC secret. | Register a **sandbox** merchant at `sandbox.vnpayment.vn/devreg/`; production creds come from a real VNPay merchant contract. |
| `VNPAY_PAY_URL` | Hosted payment page. Sandbox by default; production `https://vnpayment.vn/paymentv2/vpcpay.html`. | — |
| `VNPAY_RETURN_URL` | Frontend page VNPay redirects the browser to (display only, never trusted). e.g. `https://<frontend-domain>/?payment_return=1`. | your deployment |
| `VNPAY_IPN_URL` | **Documentation only** — not sent as a request param. Register `https://<backend-public-domain>/api/v1/payments/vnpay/ipn` in the VNPay merchant portal. `localhost` cannot receive it (use a tunnel for local testing). | — |

## Email (Brevo)

| Variable | Purpose | Where to get it |
|---|---|---|
| `BREVO_API_KEY` | Transactional email API key. | brevo.com (free tier) → Settings → SMTP & API → API Keys |
| `BREVO_FROM_EMAIL` | Sender address — must be **single-sender verified** in Brevo (Settings → Senders; click the confirmation link Brevo emails once). Any inbox works; no domain/DNS needed for the free tier. | your choice |

If either is unset, `email_service` raises `EmailError("brevo_not_configured")` — the
booking/payment flow still completes; only the confirmation email is skipped (logged).

## Airflow admin client

| Variable | Purpose | Default |
|---|---|---|
| `AIRFLOW_API_BASE` | Base URL of the separate Airflow stack. **Empty = pipeline branch disabled** (health `connected:false`, other calls raise `AirflowUnavailable`, no network attempt). Dev on one machine: `http://host.docker.internal:8088`. Staging same-host: `http://airflow-apiserver:8080` with a shared external `airflow_net`. | — |
| `AIRFLOW_USERNAME` / `AIRFLOW_PASSWORD` | Airflow API basic-auth. Backend-only; never returned by any API. Local dev default `airflow`/`airflow`. | `airflow` / `airflow` |
| `AIRFLOW_REQUEST_TIMEOUT` | Seconds. | `10.0` |

## Observability (optional)

| Variable | Purpose |
|---|---|
| `LANGCHAIN_API_KEY` / `LANGCHAIN_PROJECT` / `LANGCHAIN_TRACING_V2` / `LANGSMITH_ENDPOINT` | LangSmith tracing. Optional; leave `LANGCHAIN_TRACING_V2` unset/false to disable. Key from `smith.langchain.com`. |

## Tests

| Variable | Purpose |
|---|---|
| `TEST_SKIP_LLM` | `true` skips the ~9 tests that open a live `api.openai.com` connection (report as skipped, no spend). Everything else, Supabase included, still runs. |

## Deploy-only (GitHub Actions secrets, not in `.env`)

Set in the repo's **Settings → Secrets and variables → Actions** — see
[`../ops/deployment-runbook.md`](../ops/deployment-runbook.md):
`EC2_HOST`, `EC2_USER`, `EC2_SSH_KEY`, `CADDY_DOMAIN`; variable `EXPOSE_SWAGGER`.

---

## Known staleness in `backend/.env.example`

The template still contains pre-reorg leftovers not read by `config.py`:
`DATABASE_URL` (SQLite / Railway), `CHROMA_PERSIST_DIR`, `PINECONE_*`, and Railway
deploy hints. The real deploy target is EC2 + Docker Compose (see the runbook). Trust
`config.py` for what the backend actually reads.
