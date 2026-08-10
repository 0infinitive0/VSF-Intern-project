---
phase: 1
title: "Compose & GHCR image tagging for staging"
status: pending
priority: P1
effort: "4-5h"
dependencies: []
---

# Phase 1: Compose & GHCR image tagging for staging

## Overview

Bring `docker-compose.prod.yml` onto `main` (it currently only exists on the stale `deployment-plan` branch, where it also bundles `qdrant`+`ollama`), rewrite `backend`'s image reference from `build:` to a required (not defaulted) GHCR tag, drop `qdrant` and `ollama` entirely, and add a new `frontend` service (also GHCR-pulled). This one file is deployed unmodified to the staging box (`54.151.243.201`) — the only deploy target in this plan.

## Requirements

- Functional: `docker-compose.prod.yml` on `main` defines exactly two services, `backend` and `frontend`, both as `image:` references (no `build:`).
- Functional: image tags use `${IMAGE_TAG:?IMAGE_TAG must be set explicitly}` (compose's required-variable syntax) — **no silent fallback to a bare `latest`**. Every deploy (CI or manual) must pass `IMAGE_TAG` explicitly. This also future-proofs the file for when prod joins and two environments would otherwise fight over a shared mutable `latest`.
- Functional: `frontend` service maps a public port (80) to the container's 5173, matching `frontend/nginx.conf`'s proxy setup (`/api/` → `backend:8000` — already correct, no nginx change needed).
- Functional: no `qdrant`, no `ollama` service block, no `OLLAMA_URL`/`QDRANT_URL` env vars on `backend` — the app talks to Cloudflare Workers AI via `LLM_PROVIDER`/`EMBEDDING_PROVIDER=cloudflare` already set in `.env`, confirmed config-driven in `src/services/llm.py` (no hardcoded Ollama/Qdrant dependency).
- Non-functional: `.env` on the box is never referenced as something this file writes to; it stays `env_file: .env`, read-only from the pipeline's perspective, and staging keeps its own `.env` (same Supabase creds as prod, per the shared-database decision, but potentially different Cloudflare/OpenAI keys/quotas — not this phase's concern to reconcile).

## Architecture

```text
docker-compose.prod.yml (on main, new — one file, one deploy target)
  backend:  image: ghcr.io/0infinitive0/vsf-intern-project-backend:${IMAGE_TAG:?set IMAGE_TAG}
            env_file: .env   (LLM_PROVIDER=cloudflare, EMBEDDING_PROVIDER=cloudflare already set)
  frontend: image: ghcr.io/0infinitive0/vsf-intern-project-frontend:${IMAGE_TAG:?set IMAGE_TAG}
            ports: "80:5173"

Deploy-time IMAGE_TAG value (set by Phase 3's SSH command, never by this file):
  staging box (54.151.243.201) → sha-<short> from a `main` build (mutable pointer: main-latest)
```

No `qdrant`, no `ollama` — dropped from the deployed stack entirely; staging never runs them. `backend`+`frontend` alone comfortably fit 908Mi RAM without swap tuning.

GHCR image names must be lowercase; use `vsf-intern-project-backend` / `vsf-intern-project-frontend` under the `0infinitive0` org/user namespace.

## Related Code Files

- Create: `docker-compose.prod.yml` (root, on `main` — new two-service file, not a straight port of the `deployment-plan` branch version)
- Modify: none (no application code changes; `frontend/Dockerfile`, `frontend/nginx.conf`, and `src/services/llm.py`'s provider handling are already production-ready as-is)

## Implementation Steps

1. Write a new `docker-compose.prod.yml` from scratch (don't `git show` the `deployment-plan` branch version wholesale — that one still has `qdrant`/`ollama`; use it only as a reference for `env_file`/`healthcheck`/`restart` conventions).
2. `backend` service: `image: ghcr.io/0infinitive0/vsf-intern-project-backend:${IMAGE_TAG:?set IMAGE_TAG}`, `ports: ["8000:8000"]`, `env_file: .env`, `volumes: ["./data:/app/data"]`, `restart: unless-stopped`, keep the existing `/health` healthcheck.
3. `frontend` service: `image: ghcr.io/0infinitive0/vsf-intern-project-frontend:${IMAGE_TAG:?set IMAGE_TAG}`, `ports: ["80:5173"]`, `depends_on: [backend]`, `restart: unless-stopped`, `mem_limit: 128m` (static nginx + small SPA — plenty).
4. Confirm the repo-root `.env` already has `LLM_PROVIDER=cloudflare` and `EMBEDDING_PROVIDER=cloudflare`/`EMBEDDING_MODEL=@cf/baai/bge-m3` (already verified) — no `.env` changes needed for this phase.
5. Over SSH to the **staging** box, verify its app root is a git working tree tracking `origin/main`. Run `git -C <app-root> remote -v` and `git rev-parse --abbrev-ref HEAD`. If the box is not a git checkout (staging is a pre-existing instance whose current state is unverified — see Open Questions in `plan.md`), `git clone` the repo into place there and create/populate a `.env` for it (copy structure from prod's `.env`, but point at whatever Cloudflare/OpenAI keys the user wants staging to use; Supabase creds are the same as prod per the shared-database decision). Record what you found — Phase 3's deploy job depends on it being a working git tree.
6. Confirm `docker-compose.prod.yml` parses: `IMAGE_TAG=test docker compose -f docker-compose.prod.yml config >/dev/null` locally (the `:?` required-var syntax means `config` fails without `IMAGE_TAG` set, which is the point).
7. Commit `docker-compose.prod.yml` to `main` (via normal PR/merge flow, not force-push).

## Success Criteria

- [ ] `docker-compose.prod.yml` exists on `main`, `IMAGE_TAG=x docker compose -f docker-compose.prod.yml config` passes, and it fails without `IMAGE_TAG` set.
- [ ] File defines exactly two services (`backend`, `frontend`), both referencing GHCR images via the required `IMAGE_TAG`, no `build:` block for either.
- [ ] No `qdrant`/`ollama` service block and no `OLLAMA_URL`/`QDRANT_URL` env var anywhere in the file.
- [ ] SSH check confirms (and records in the phase notes) whether the staging app root is a git working tree tracking `origin/main`; if it wasn't, it has been converted to one, with its own `.env` in place.

## Risk Assessment

- **Risk:** if the staging box's app root isn't actually a git checkout, Phase 3's `git pull`-based deploy job will fail on first run. **Mitigation:** step 5 verifies the box before Phase 3 is built, not after.
- **Risk:** dropping `ollama`/`qdrant` from the stack could break something if the box's `.env` doesn't actually match the repo-root `.env` inspected during planning (they could have drifted). **Mitigation:** re-verify `LLM_PROVIDER`/`EMBEDDING_PROVIDER` values on the box itself via SSH before the first deploy, not just locally.
- **Risk:** adding a public port 80 frontend changes the box's public attack surface for the first time. **Mitigation:** nginx serves static files + proxies only `/api/`; no new secrets exposed. Security-group changes are called out explicitly in Phase 4 as manual, user-only actions.
- **Risk:** staging's `.env` is unverified — it may not exist yet, or may point at stale/placeholder API keys from whenever the instance was provisioned. **Mitigation:** step 5 explicitly creates/checks it rather than assuming it mirrors prod.
