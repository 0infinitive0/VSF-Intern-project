---
phase: 4
title: "Docs and manual prerequisites checklist for staging"
status: pending
priority: P2
effort: "1.5-2h"
dependencies: [1, 2, 3]
---

# Phase 4: Docs and manual prerequisites checklist for staging

## Overview

Update the one doc that already (incorrectly) claims CI/CD exists, and give the user an explicit checklist of the manual, one-time, human-only steps this pipeline needs for the staging box before it can work. None of these are automatable with current credentials or from within a GitHub Actions job.

## Requirements

- Functional: `docs/guide/devops/docker-cicd.md` accurately describes the real pipeline (test → build/push GHCR with branch-scoped tags → SSH deploy to staging → health check), not the aspirational placeholder text it has today.
- Functional: a single checklist exists (in the doc or the rollback runbook from Phase 3) enumerating every manual prerequisite for staging, in the order they must be done.
- Functional: the shared-Supabase risk (staging and prod share one database — user's explicit decision) is written down somewhere a future contributor will see before running a destructive test against staging.

## Related Code Files

- Modify: `docs/guide/devops/docker-cicd.md`
- Modify or reference: `docs/guide/devops/rollback-runbook.md` (created in Phase 3)

## Implementation Steps

1. Rewrite the "CI/CD (GitHub Actions)" section of `docs/guide/devops/docker-cicd.md` to describe the actual jobs (`test`, `build-push`, `deploy-staging`), the branch→host mapping (`main`→staging `54.151.243.201`), the GHCR image tag scheme (`sha-<short>` + `main-latest`), and where secrets live (GitHub Environment `staging`).
2. Add a "Manual prerequisites" checklist (numbered, in the order they block the pipeline), covering the staging box explicitly:
   - [ ] Open port 80 (and confirm 22/8000) in the security group for **staging** (`54.151.243.201`) — AWS console, local AWS creds lack EC2 permissions, must be done by the user.
   - [ ] Create GitHub Environment `staging`; add `EC2_HOST`/`EC2_USER`/`EC2_SSH_KEY` with the box's values.
   - [ ] Generate a `read:packages`-scoped PAT and run `docker login ghcr.io` once on the box.
   - [ ] Confirm the app root on the box is a git working tree tracking `origin/main` — Phase 1 step 5's finding; if staging needed a fresh `git clone` + `.env`, confirm that `.env` has real (not placeholder) Cloudflare/OpenAI/Supabase values before relying on staging deploys.
   - [ ] If GHCR push 403s despite job-level `permissions:`, enable "Read and write permissions" under repo Settings → Actions → General → Workflow permissions.
3. Cross-link this checklist from `plan.md`'s Overview so a future reader doesn't have to hunt for it.
4. Add a short, explicit note: **staging and production share one Supabase database.** Do not run destructive migrations, bulk deletes, or seed/reset scripts against staging without taking a Supabase backup first — "staging" here means a separate compute environment, not separate data.
5. Note in the doc, briefly, that `plans/260723-1720-deploy-to-aws` and `plans/260724-0900-deploy-airflow-aws` describe a different (never-executed) target architecture (ECR/App Runner/RDS/ECS) and should not be treated as current.

## Success Criteria

- [ ] `docs/guide/devops/docker-cicd.md` matches what's actually running, verified by re-reading it against the merged `.github/workflows/deploy.yml`.
- [ ] Every manual prerequisite from Phases 1-3 appears exactly once in the checklist, with no step assumed-but-unwritten.
- [ ] The shared-Supabase warning is visible in the doc, not just in `plan.md`.

## Risk Assessment

- **Risk:** docs drift again the next time the pipeline changes. **Mitigation:** none needed beyond normal review discipline — this is a low-blast-radius doc-only phase; not gating further engineering work.
