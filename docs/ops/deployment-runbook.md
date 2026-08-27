# Deployment & Operations Runbook

How the app reaches production, how to operate it, and how to roll back.

> **Fill-in markers** `⟨…⟩` are facts only the current owners have. Complete them
> before handoff. Nothing secret goes in this file.

---

## 1. Topology

Single EC2 host, everything in Docker Compose behind Caddy (auto-HTTPS).

```
Internet ──443──▶ Caddy (caddy:2) ──▶ frontend (Vite preview :5173)
                        │
                        └──(/docs,/redoc,/openapi.json only when EXPOSE_SWAGGER)──▶ backend :8000
Internet ──8000──▶ backend (FastAPI)   [also exposed directly for health checks]
```

- **Compose file:** `docker-compose.staging.yml` (repo root). Services: `backend`,
  `frontend`, `caddy`.
- **Backend** builds from `./backend/Dockerfile`, reads `./backend/.env`, mounts
  `./backend/data:/app/data`, healthcheck on `http://localhost:8000/health`.
- **Frontend** builds from `./frontend/Dockerfile` with build arg `VITE_MAPBOX_TOKEN`
  (from root `.env` or shell), serves on `:5173`.
- **Caddy** terminates TLS on `:80`/`:443`, proxies to `frontend:5173`, `DOMAIN` from
  `CADDY_DOMAIN` (default `staging-app.duckdns.org`). Config: `./Caddyfile`
  (`Caddyfile.swagger-debug` is the toggled variant).
- **Airflow** runs as a **separate** compose stack in `backend/src/airflow/`
  (`docker-compose.staging.yml` there), on an external Docker network `airflow_net`
  (`docker network create airflow_net` once on the host). The backend joins it to reach
  `airflow-apiserver:8080`.

| Thing | Value |
|---|---|
| EC2 host / IP | `⟨EC2_HOST⟩` |
| SSH user | `⟨EC2_USER, e.g. ubuntu⟩` |
| App directory on host | `/home/ubuntu/app` (per `deploy.yml`) |
| Public domain | `⟨CADDY_DOMAIN⟩` (DuckDNS: `⟨duckdns account / token owner⟩`) |
| Region / instance type | `⟨fill in⟩` |
| Cloud account owner | `⟨fill in⟩` |

## 2. CI/CD

Two GitHub Actions workflows (`.github/workflows/`):

### `deploy.yml` — Deploy Staging (main)
- **Trigger:** push to `main`, or manual `workflow_dispatch` (with an
  `expose_swagger` boolean input).
- **What it does:** SSH to the EC2 host (`appleboy/ssh-action`) and run:
  1. `cd /home/ubuntu/app`
  2. `git fetch origin main && git checkout main && git reset --hard origin/main`
     — **the working tree is discarded every deploy**; anything not in git is lost.
  3. If `EXPOSE_SWAGGER=true`: `cp Caddyfile.swagger-debug Caddyfile` (temporary; the
     next normal deploy's `git reset` restores the plain one).
  4. `docker compose -f docker-compose.staging.yml build backend`
  5. `docker compose -f docker-compose.staging.yml build frontend`
  6. `docker compose -f docker-compose.staging.yml up -d --wait --wait-timeout 300`
  7. `docker compose -f docker-compose.staging.yml exec -T caddy caddy reload --config /etc/caddy/Caddyfile`
  8. `docker image prune -f`
- **Post-deploy health check** (in the workflow): polls
  `http://⟨EC2_HOST⟩:8000/health` and `https://⟨CADDY_DOMAIN⟩/` up to 12× / 5s; fails
  the run if neither comes up.
- **Required GitHub secrets:** `EC2_HOST`, `EC2_USER`, `EC2_SSH_KEY`, `CADDY_DOMAIN`.
  **Variable:** `EXPOSE_SWAGGER` (repo or environment variable; the dispatch input
  overrides it).

### `agent-pr-review.yml` — automated PR reviewer
- Runs an AI reviewer on PRs touching `backend/`, `eval/`, `src/airflow/`, `tests/`.
  Does **not** run tests or build, does **not** deploy. Informational only.

There is **no** test/build gate before deploy — `main` goes straight to staging. Run
`cd backend && make check` locally before merging.

## 3. Manual deploy / operations (on the host)

```bash
ssh ⟨EC2_USER⟩@⟨EC2_HOST⟩
cd /home/ubuntu/app

# Pull + rebuild + restart (same as CI)
git fetch origin main && git reset --hard origin/main
docker compose -f docker-compose.staging.yml up -d --build --wait

# Status / logs
docker compose -f docker-compose.staging.yml ps
docker compose -f docker-compose.staging.yml logs -f backend
docker compose -f docker-compose.staging.yml logs --tail=200 caddy

# Restart one service
docker compose -f docker-compose.staging.yml restart backend

# Shell into the backend
docker compose -f docker-compose.staging.yml exec backend sh
```

Health: `curl -sf http://localhost:8000/health` on the host;
`curl -sfk https://⟨CADDY_DOMAIN⟩/` from anywhere.

## 4. Rollback

The working tree is git-driven, so rollback = deploy an older commit.

```bash
ssh ⟨EC2_USER⟩@⟨EC2_HOST⟩ && cd /home/ubuntu/app
git fetch origin
git reset --hard ⟨last-known-good-SHA⟩          # or origin/main~1
docker compose -f docker-compose.staging.yml up -d --build --wait
docker compose -f docker-compose.staging.yml exec -T caddy caddy reload --config /etc/caddy/Caddyfile
```

Then, so the next push doesn't re-deploy the bad commit, either revert it on `main`
(`git revert <SHA>` + PR) or hold merges until fixed.

**Rollback triggers (agree these with the team):**
- `/health` down after deploy, or the CI health check fails.
- Error rate / 5xx spike on `POST /planner_chat` or `/payments/vnpay/ipn`.
- Booking confirmation emails not sending (check `backend` logs for `EmailError`).
- A DB migration in the release turns out to be destructive/incompatible.

**Database is not rolled back by the above.** If a release included a migration in
`backend/scripts/migrations/`, decide separately whether to apply a down-migration or a
forward fix. See § 6.

## 5. Configuration & secrets on the host

- `⟨/home/ubuntu/app⟩/backend/.env` — all backend secrets. **Not in git.** Populate from
  [`../setup/environment-variables.md`](../setup/environment-variables.md).
- `⟨/home/ubuntu/app⟩/.env` — `VITE_MAPBOX_TOKEN` for the frontend build.
- `backend/src/airflow/.env` — `AIRFLOW_UID` + `FERNET_KEY` for the Airflow stack.
- GitHub Actions secrets — repo Settings → Secrets and variables → Actions.
- **Rotation:** `⟨document who rotates each and how — Supabase keys, VNPay hash secret,
  Brevo key, Cloudflare token, EC2 SSH key⟩`. See
  [`infrastructure-and-access.md`](infrastructure-and-access.md).

## 6. Database (Supabase)

- **Schema source of truth:** `backend/scripts/database_schema.sql` +
  `backend/scripts/migrations/*.sql` (dated `YYYYMMDD_*.sql`).
- **Applying a migration:** run the SQL against the Supabase project (SQL editor, or
  `psql` with the session-pooler DSN). There is no automated migration runner — apply in
  filename order. Some historical migrations were applied directly on Supabase and never
  committed (e.g. `20260814_move_available_room_count_to_rooms.sql`, referenced by a test
  but absent from the repo) — reconcile before trusting the folder as complete.
- **Backups / PITR:** `⟨is Point-in-Time Recovery enabled on the Supabase project? plan
  tier? retention window?⟩`. Supabase dashboard → Database → Backups.
- **Restoring a fresh project:** create the project, run `database_schema.sql`, then every
  migration in order, then re-run the data pipeline (§7) to repopulate `hotels` /
  `attractions` / vectors. `data/agoda.json` + `data/booking.json` are the raw inputs and
  are git-ignored — `⟨where are they archived?⟩`.

## 7. Data pipeline (Airflow)

- Separate stack: `cd backend/src/airflow && docker compose up -d` (see
  [`../setup/SETUP_GUIDE.md`](../setup/SETUP_GUIDE.md) § Airflow).
- UI: `http://⟨host⟩:8088` (`airflow` / `airflow` by default — change for anything
  internet-reachable).
- DAGs start **paused**; the admin `POST /pipelines/{dag_id}/runs` endpoint unpauses
  automatically, a raw trigger does not.
- Scheduled jobs inventory: `⟨list each DAG, its schedule, and what "it failed" looks
  like — currently DAGs appear to be manual-trigger only⟩`.

## 8. Monitoring & logging

**Current state: no external monitoring or alerting.** Observability is:
- `GET /health` (liveness) — polled by the CI deploy step and Caddy's `depends_on`.
- Container logs: `docker compose ... logs` on the host (no centralised log store,
  no retention policy — logs rotate with Docker defaults).
- Optional LangSmith tracing if `LANGCHAIN_TRACING_V2=true` (project
  `⟨LANGCHAIN_PROJECT⟩`, owner `⟨fill in⟩`).

Gaps to close if this becomes more than a PoC: uptime check on `https://⟨domain⟩/`,
error alerting on the backend, disk-space alert on the EC2 host (Docker images +
`backend/data` grow), a cron to release expired booking holds (today it's the manual
`POST /admin/orders/holds/release-expired`).

## 9. Routine operational tasks

| Task | How |
|---|---|
| Expose Swagger temporarily | `workflow_dispatch` on `deploy.yml` with `expose_swagger=true`; unset and re-deploy to hide. |
| Release expired room holds | `POST /api/v1/admin/orders/holds/release-expired` (no cron). |
| Re-embed hotels after data changes | `POST /api/v1/admin/hotels/reembed`; check `GET /api/v1/admin/embedding/summary`. |
| Grant someone admin | Set `app_metadata.app_role = "admin"` on their Supabase user. |
| Rotate a secret | Update `backend/.env` on the host + the source system, `docker compose ... up -d` to restart. |
| Free disk on the host | `docker image prune -f`; check `backend/data/` size. |
