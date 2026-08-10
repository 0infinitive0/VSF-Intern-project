---
title: "Auto Deploy Staging (main) to AWS EC2"
description: "GitHub Actions CI/CD: on push to main, test, build+push backend/frontend images to GHCR, SSH-deploy to the staging EC2 box, health-check, and support rollback."
status: pending
priority: P1
effort: "1.5-2.5d"
tags: [infra, ci-cd, aws, ec2, deploy, github-actions, ghcr, staging]
branch: "main"
blockedBy: []
blocks: []
created: "2026-08-03"
createdBy: "ak:plan"
source: user
---

# Auto Deploy Staging (main) to AWS EC2

## Overview

One environment, one EC2 box, one pipeline:

| Environment | Branch | EC2 host | Status |
|---|---|---|---|
| Staging | `main` | `54.151.243.201` | Already provisioned (user-confirmed) |

Staging deployment is currently 100% manual — there's no deploy process at all. This plan replaces that with one GitHub Actions pipeline: **test → build & push Docker images to GHCR → SSH into the staging EC2 box → pull the new images → restart → health-check**, triggered only by pushes to `main`, with a documented rollback path. Production (`13.229.93.102`) is **out of scope**.

**Key existing-state findings that shape this plan:**

- `docker-compose.prod.yml` is **not on `main`** — it only exists on the stale `deployment-plan` branch, and that version bundles `qdrant` + `ollama` alongside `backend`. It must be ported to `main` as part of this work, but rebuilt to drop both.
- The repo has **no CI/CD workflow files at all** in any branch (`.github/workflows/` is empty everywhere), despite `docs/guide/devops/docker-cicd.md` describing one as if it already existed. This plan creates the first real workflow, and it's the first time staging gets a deploy path of any kind.
- The GitHub repo (`0infinitive0/VSF-Intern-project`) is **private**, so GHCR-pushed images default to private — the staging box needs one-time registry auth to pull them (Phase 3).
- Local AWS CLI creds have **no EC2 permissions** ([[ec2-deployment]]) — this plan does not call any AWS API. Everything is SSH + Docker + GHCR. The AWS-console step required (opening port 80 in the staging security group) must be done manually by the user.
- **`qdrant` and `ollama` are dropped from the deployed stack entirely** (user decision, verified safe): the live `.env` already has `LLM_PROVIDER=cloudflare` and `EMBEDDING_PROVIDER=cloudflare` with `EMBEDDING_MODEL=@cf/baai/bge-m3` — the app already calls Cloudflare Workers AI for both chat and embeddings, not local Ollama. `src/services/llm.py` reads the provider generically from env vars; no code depends on `OLLAMA_URL`/`QDRANT_URL` being set. Per [[ec2-deployment]], Qdrant was already off the serving path (only `scripts/sync_*.py`/Airflow DAGs read it) and the embedding model/dims are unchanged (still bge-m3, 1024-dim, just hosted remotely) — so this is not a re-index risk, just removing two idle-on-prod containers that were eating ~2.25GB of the box's already-tight RAM budget. Same applies to staging: never runs `qdrant`/`ollama` either.
- **GHCR image tags are branch-scoped, not a single mutable `latest`.** With a single environment here, a bare `latest` would work today but sets a foot-gun for when prod joins later. Tags are therefore `sha-<short>` (immutable, always pushed) plus `main-latest` (mutable, human-debugging convenience only). The deploy job always pins the exact `sha-<short>` it just built — it never relies on a mutable tag at runtime.

**User decisions confirmed for this plan (do not re-litigate without new evidence):**

1. **Build strategy:** build in GitHub Actions, push to GHCR, EC2 only pulls. Rejected alternative: building on the box via SSH (matches current manual process but risks OOM/CPU contention with live containers on a 908Mi-RAM box).
2. **Deploy scope:** backend **and** frontend only — no `qdrant`, no `ollama`. Frontend is new production surface — `frontend/Dockerfile` + `frontend/nginx.conf` already proxy `/api/` → `backend:8000` and are otherwise production-ready as-is; no frontend code changes are needed, just adding it to the topology. Chat/embeddings run entirely against the Cloudflare Workers AI API key already configured in `.env`.
3. **Environment topology:** a single pre-existing EC2 instance for staging (`54.151.243.201`), not provisioned by this plan — instance creation/AMI/security-group setup is out of scope since the box already exists; only the deploy pipeline and one-time box-side setup (GHCR login, `.env`, security-group port 80) are in scope. The prod box (`13.229.93.102`) is untouched by this plan.
4. **Database isolation:** staging **shares the same Supabase project as production** (user's explicit choice, not this plan's recommendation). Accepted risk: a write/migration exercised on staging mutates the same rows prod serves. See Risk Assessment in Phase 3 and the checklist in Phase 4 — no schema migration or destructive script should be tested against staging without a fresh Supabase backup first, since "staging" here is not an isolated data copy.

## Cross-Plan Relationship

Two older AWS plans exist and are **stale relative to reality**, not blocking this one:

- `plans/260723-1720-deploy-to-aws` (all 6 phases still `pending`) proposed ECR + App Runner + RDS. That never happened — the boxes actually live today are raw EC2 instances running `docker compose`, with Supabase (not RDS) as the database.
- `plans/260724-0900-deploy-airflow-aws` proposed ECS Fargate for Airflow. Out of scope here — this plan only touches the `backend`/`frontend` API/UI path, not Airflow.

No `blockedBy`/`blocks` edge is set because this plan does not depend on either and does not change their scope. Recommend the user archive or explicitly supersede those two once this plan ships, so future readers aren't misled about the actual deployment topology.

## Goals

| # | Goal | Priority |
|---|------|----------|
| 1 | Push to `main` triggers lint+test, then builds/pushes `backend` and `frontend` images to GHCR | P1 |
| 2 | A passing `main` build auto-deploys to the staging EC2 box | P1 |
| 3 | Deploy verifies success with a health check; a failed check is visible in the Actions run (not silently green) | P1 |
| 4 | A documented, low-effort rollback path exists for staging (previous image tag) | P2 |
| 5 | Manual one-time prerequisites (SSH key secrets, GHCR box auth, security group port 80) are enumerated for the staging box so the pipeline doesn't silently fail on first run | P1 |

## Phases

| # | Phase | Status |
|---|-------|--------|
| 1 | [Compose & GHCR image tagging for staging](./phase-01-start.md) | Pending |
| 2 | [CI: build and push images to GHCR on main](./phase-02-ci-build-and-push-images-to-ghcr.md) | Pending |
| 3 | [CD: SSH deploy to staging EC2 with health check and rollback](./phase-03-cd-ssh-deploy-to-ec2-with-health-check-and-rollback.md) | Pending |
| 4 | [Docs and manual prerequisites checklist for staging](./phase-04-docs-and-manual-prerequisites-checklist.md) | Pending |

## Success Criteria

- [ ] Pushing a commit to `main` runs the GitHub Actions workflow with no manual trigger needed, deploying to the staging box only.
- [ ] `ruff check` + `pytest` gate the pipeline — a failing test blocks image build/push/deploy.
- [ ] `backend` and `frontend` images land in GHCR tagged `sha-<short>` plus the `main-latest` pointer — no bare mutable `latest` tag exists.
- [ ] The staging EC2 box ends up running the new images without a full `docker compose build` on the box.
- [ ] Post-deploy health check hits the box's `:8000/health` and frontend root, and fails the job (not just logs a warning) if either doesn't return 2xx within a bounded retry window.
- [ ] `docker-compose.prod.yml` on `main` defines only `backend` and `frontend` — no `qdrant`, no `ollama` service block.
- [ ] Rollback runbook exists and has been dry-run at least once on the staging box (redeploy previous `sha-<short>` tag successfully).
- [ ] `.env` on the box is never overwritten or committed by the pipeline.
- [ ] The shared-Supabase risk (staging and prod hitting the same database) is written down where a future contributor will see it before running a destructive test against staging.

## Open Questions

- Is `/home/ubuntu/app` (or an equivalent path) on the **staging** box (`54.151.243.201`) already a git working tree tracking `origin/main`, or a fresh instance with nothing deployed yet? Only the IP was confirmed — Phase 1 must SSH in and check before Phase 3's `git pull`-based deploy job can target it.

<!-- slug: auto-deploy-main-to-aws-ec2 -->
