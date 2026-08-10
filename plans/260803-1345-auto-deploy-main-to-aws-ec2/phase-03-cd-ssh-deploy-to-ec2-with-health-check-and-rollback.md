---
phase: 3
title: "CD: SSH deploy to staging EC2 with health check and rollback"
status: pending
priority: P1
effort: "5-7h"
dependencies: [1, 2]
---

# Phase 3: CD SSH deploy to staging EC2 with health check and rollback

## Overview

Add one deploy job that runs after `build-push` succeeds on `main`: `deploy-staging`, targeting `54.151.243.201`. It SSHes into the box, refreshes the git checkout, pulls the two new GHCR images pinned to the exact `sha-<short>` just built, restarts, and verifies with a health check. Use a GitHub Environment (`staging`) to scope the job's secrets cleanly. Also produce a rollback runbook. Production is not deployed by this pipeline.

## Requirements

- Functional: `deploy-staging` runs only after `build-push` succeeds on `main`.
- Functional: uses GitHub encrypted secrets, scoped per GitHub Environment — the `staging` environment holds `EC2_HOST`/`EC2_USER`/`EC2_SSH_KEY` for `54.151.243.201`.
- Functional: deploy command updates the git working tree on the target box, then `IMAGE_TAG=sha-<short> docker compose -f docker-compose.prod.yml pull && IMAGE_TAG=sha-<short> docker compose -f docker-compose.prod.yml up -d`, using the exact `short_sha` output from Phase 2's `build-push` job (never a mutable `-latest` pointer at deploy time — Phase 1's `${IMAGE_TAG:?...}` makes an unset value a hard failure, not a silent bad pull).
- Functional: post-deploy health check retries `http://<EC2_HOST>:8000/health` and `http://<EC2_HOST>/` for up to ~60s; the job fails (red X in Actions) if either never returns 2xx.
- Non-functional: deploy step never touches `.env` on the box, never runs `docker compose build`.

## Architecture

```text
job: deploy-staging (needs: build-push, if: github.ref == 'refs/heads/main', environment: staging)
  - webfactory/ssh-agent (or appleboy/ssh-action) with secrets.EC2_SSH_KEY (staging env)
  - ssh ${{ secrets.EC2_USER }}@${{ secrets.EC2_HOST }} <<'EOF'
      cd <staging-app-root>          # confirmed in Phase 1 step 5
      git fetch origin main
      git checkout main
      git pull --ff-only
      export IMAGE_TAG=sha-<short_sha from build-push>
      docker compose -f docker-compose.prod.yml pull
      docker compose -f docker-compose.prod.yml up -d
      docker image prune -f
    EOF
  - curl retry loop against http://54.151.243.201:8000/health and http://54.151.243.201/
```

One-time, manual, NOT part of the workflow (run once by a human over SSH on the staging box, before its first real automated deploy):

```bash
# On the EC2 box, authenticate Docker to pull private GHCR images:
echo "<PAT with read:packages>" | docker login ghcr.io -u <github-username> --password-stdin
```

This is a one-time step because `docker login` persists credentials in `~/.docker/config.json` locally; it does not need to run on every deploy, and a short-lived `GITHUB_TOKEN` from the Actions run can't be used here since it doesn't exist outside that run.

## Related Code Files

- Modify: `.github/workflows/deploy.yml` (add `deploy-staging` job)
- Create: `docs/guide/devops/rollback-runbook.md` (or fold into Phase 4's docs update — see Phase 4)

## Implementation Steps

1. In GitHub repo Settings → Environments, create the `staging` environment. Add `EC2_HOST`, `EC2_USER`, `EC2_SSH_KEY` as environment-scoped secrets: `54.151.243.201`/`ubuntu`/the staging box's private key.
2. One-time, manual, on the box: `docker login ghcr.io` with a personal access token scoped `read:packages`. Confirm with `IMAGE_TAG=main-latest docker compose -f docker-compose.prod.yml pull backend` succeeding once by hand.
3. Add the `deploy-staging` job to `.github/workflows/deploy.yml`, `needs: build-push`, gated by `if: github.ref == 'refs/heads/main'` and the `environment: staging` block, using an SSH action (e.g. `appleboy/ssh-action@v1`) fed the environment's three secrets, running the script block above with `IMAGE_TAG=sha-${{ needs.build-push.outputs.short_sha }}`.
4. Add a post-deploy health-check step (can run on `ubuntu-latest`, not over SSH) that polls `curl -sf http://54.151.243.201:8000/health` and `curl -sf http://54.151.243.201/` in a retry loop (e.g. 10 attempts, 5s apart), failing the job non-zero if either never succeeds.
5. Dry-run: push a trivial no-op commit to `main`, watch `deploy-staging` run end-to-end, confirm both containers on `54.151.243.201` show the new `sha-<short>` image via `docker compose -f docker-compose.prod.yml images`.
6. Write the rollback runbook: to roll back, SSH into the box, `IMAGE_TAG=sha-<previous-short> docker compose -f docker-compose.prod.yml up -d`. Note where to find the previous tag (GHCR package page filtered by `sha-` tags, or `git log --oneline main` cross-referenced with Actions run history).
7. Actually perform one rollback dry-run on staging (deploy current, then roll back to the prior tag, confirm health check passes on the rolled-back version) before marking this phase done.

## Success Criteria

- [ ] `staging` GitHub Environment exists with its own `EC2_HOST`/`EC2_USER`/`EC2_SSH_KEY`.
- [ ] One-time `docker login ghcr.io` completed on the box; `docker compose -f docker-compose.prod.yml pull` succeeds without a fresh CI-issued token.
- [ ] End-to-end dry run on `main`: Actions goes green → `54.151.243.201` is running the new `sha-<short>` image for both `backend` and `frontend`.
- [ ] Health check step fails the job when a deliberately-broken health endpoint is deployed to a scratch tag on staging (verified once, not left in place).
- [ ] Rollback has been performed once for real on staging, not just documented.

## Risk Assessment

- **Risk:** SSH from a GitHub-hosted runner to a specific IP could be blocked if the staging security group only allows a fixed IP range for port 22. **Mitigation:** verify the current SG rule for port 22 first; GitHub Actions runner IPs are not static, so the SG likely needs `0.0.0.0/0` on 22 restricted to key-based auth only, or a self-hosted runner as a fallback — flag to the user if the SG is IP-restricted.
- **Risk:** a bad image (crashes on start) passes `docker compose up -d` (container "up" but unhealthy) and the health check catches it late, or the job dies mid-SSH leaving the box on a half-updated state. Since the stack is just `backend`+`frontend`, a bad `backend` image means the whole API is down until rollback. **Mitigation:** the health check step catches this within ~60s of deploy; the rollback runbook is the recovery path.
- **Risk:** staging shares the same Supabase database as production (user's explicit decision, see `plan.md`). A deploy to staging that exercises a bad migration, seed script, or destructive endpoint mutates prod's live data — this is not a CI/CD bug, it's the inherent cost of the shared-database choice, and no amount of deploy-pipeline correctness fixes it. **Mitigation:** out of scope for this phase to change (would require the "separate Supabase project" option the user declined), but the checklist in Phase 4 must say, explicitly, "back up before any destructive staging test."
- **Risk:** concurrent pushes to `main` could race two deploy jobs for the same environment. **Mitigation:** add `concurrency: {group: deploy-${{ github.ref_name }}, cancel-in-progress: false}` to the workflow so runs for the same branch queue instead of interleaving.
