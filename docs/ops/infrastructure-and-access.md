# Infrastructure & Access Inventory

Every system the project depends on, who owns it, and how ownership transfers at handoff.

> **This file lists account names, roles, and locations only — never passwords, keys, or
> tokens.** Secret *values* live in `backend/.env` on the host and in each provider's
> dashboard. This inventory says *which* secret, *where* it lives, and *who* can rotate it.

Status: **template — fill the `⟨…⟩` fields.** Ask the outgoing owners.

---

## 1. Accounts & services

| Service | Used for | Account / project id | Current owner | Plan / cost | Transfer method |
|---|---|---|---|---|---|
| **AWS (EC2)** | Prod/staging host | `⟨account id, region, instance id⟩` | `⟨name⟩` | `⟨instance type, ~$/mo⟩` | Add new IAM user / transfer root |
| **Supabase** | Postgres + pgvector + Auth + Storage | `⟨project ref⟩` | `⟨name⟩` | `⟨free / pro⟩` | Org → add member → transfer ownership |
| **DuckDNS** (or DNS provider) | `⟨CADDY_DOMAIN⟩` | `⟨account⟩` | `⟨name⟩` | free | Share account / move domain |
| **GitHub** | Repo `0infinitive0/VSF-Intern-project`, Actions, secrets | org/user `0infinitive0` | `⟨name⟩` | — | Add maintainers; transfer repo |
| **Cloudflare** | Workers AI (LLM + embeddings) | `⟨account id⟩` | `⟨name⟩` | `⟨free quota / paid⟩` | Add member |
| **VNPay** | Payment gateway | `⟨sandbox merchant / prod merchant code⟩` | `⟨name⟩` | sandbox free | Merchant portal → users; prod needs a contract |
| **Brevo** | Confirmation emails | `⟨account, verified sender⟩` | `⟨name⟩` | free tier | Add user / transfer |
| **Mapbox** | Maps (routing + tiles) | `⟨account⟩` | `⟨name⟩` | free tier | Add member |
| **Qdrant** | Hotel/attraction vectors | `⟨self-hosted where? or Qdrant Cloud cluster id⟩` | `⟨name⟩` | `⟨…⟩` | `⟨…⟩` |
| **LangSmith** (optional) | LLM tracing | project `⟨LANGCHAIN_PROJECT⟩` | `⟨name⟩` | `⟨…⟩` | Org → members |
| **OpenAI / OpenRouter** (optional) | Alt LLM / eval judge | `⟨account⟩` | `⟨name⟩` | pay-as-you-go | Add member / rotate key |
| **Ollama** | Local models only | n/a (per-machine) | — | free | — |

## 2. Secrets register (names & locations only)

| Secret (env var) | Lives in | Issued by | Who can rotate | Last rotated |
|---|---|---|---|---|
| `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` | host `backend/.env` | Supabase dashboard → Settings → API | `⟨name⟩` | `⟨date⟩` |
| `CLOUDFLARE_ACCOUNT_ID` / `CLOUDFLARE_API_TOKEN` | host `backend/.env` + root `.env` | Cloudflare dashboard → AI → Workers AI | `⟨name⟩` | `⟨date⟩` |
| `LLM_API_KEY` / `OPENAI_API_KEY` / `OPENROUTER_API_KEY` | host `backend/.env` | respective provider console | `⟨name⟩` | `⟨date⟩` |
| `MAPBOX_ACCESS_TOKEN` (secret) | host `backend/.env` | Mapbox → Access tokens | `⟨name⟩` | `⟨date⟩` |
| `VITE_MAPBOX_TOKEN` (public, restricted) | host root `.env` | Mapbox → Access tokens (public) | `⟨name⟩` | `⟨date⟩` |
| `VNPAY_TMN_CODE` / `VNPAY_HASH_SECRET` | host `backend/.env` | VNPay merchant portal | `⟨name⟩` | `⟨date⟩` |
| `BREVO_API_KEY` | host `backend/.env` | Brevo → Settings → SMTP & API | `⟨name⟩` | `⟨date⟩` |
| `SUPABASE_JWT_SECRET` | *unset for this project* | — | — | — |
| `AIRFLOW_USERNAME` / `AIRFLOW_PASSWORD` | host `backend/.env` + Airflow stack | set at Airflow init | `⟨name⟩` | `⟨date⟩` |
| Airflow `FERNET_KEY` | host `backend/src/airflow/.env` | generated once at init | `⟨name⟩` | `⟨date⟩` |
| `LANGCHAIN_API_KEY` (optional) | host `backend/.env` | smith.langchain.com | `⟨name⟩` | `⟨date⟩` |
| GitHub Actions: `EC2_HOST`, `EC2_USER`, `EC2_SSH_KEY`, `CADDY_DOMAIN` | repo → Settings → Secrets and variables → Actions | — | `⟨name⟩` | `⟨date⟩` |
| EC2 SSH private key | `⟨where is the authoritative copy kept?⟩` | AWS EC2 key pair `⟨name⟩` | `⟨name⟩` | `⟨date⟩` |

**Handoff:** rotate every row above at transfer, and re-issue the EC2 key pair.

## 3. Host access

| | |
|---|---|
| SSH | `ssh ⟨EC2_USER⟩@⟨EC2_HOST⟩` with key `⟨key pair name⟩` |
| Who has access today | `⟨names⟩` |
| Bastion / VPN | `⟨none? or details⟩` |
| App directory | `/home/ubuntu/app` |
| Sudo | `⟨who⟩` |

## 4. Admin (application) users

| Email | `app_role` | Set by | Notes |
|---|---|---|---|
| `⟨admin email⟩` | `admin` | Supabase dashboard → Auth → Users → `app_metadata` | |

## 5. Domains & endpoints

| | |
|---|---|
| Public app | `https://⟨CADDY_DOMAIN⟩` |
| Backend health (direct) | `http://⟨EC2_HOST⟩:8000/health` |
| VNPay IPN (registered in merchant portal) | `https://⟨CADDY_DOMAIN or backend domain⟩/api/v1/payments/vnpay/ipn` |
| Airflow UI | `http://⟨host⟩:8088` |

## 6. Billing

| Service | Payment method owner | Approx monthly | Alerts configured? |
|---|---|---|---|
| AWS | `⟨name⟩` | `⟨$⟩` | `⟨y/n⟩` |
| Supabase | `⟨name⟩` | `⟨$⟩` | `⟨y/n⟩` |
| Cloudflare | `⟨name⟩` | `⟨$ / free⟩` | `⟨y/n⟩` |
| Others | `⟨…⟩` | | |

## 7. Key contacts / bus factor

| Area | Who built / knows it | Reachable at |
|---|---|---|
| Data pipeline (Airflow, crawlers) | `⟨name⟩` | `⟨…⟩` |
| LangGraph agent / graph | `⟨name⟩` | `⟨…⟩` |
| Frontend (chat + admin SPA) | `⟨name⟩` | `⟨…⟩` |
| Booking / VNPay / email | `⟨name⟩` | `⟨…⟩` |
| Infra / deploy / Supabase | `⟨name⟩` | `⟨…⟩` |
| Mentor / stakeholder | `⟨name⟩` | `⟨…⟩` |
| Post-handoff support window | `⟨until when, through whom⟩` | |
