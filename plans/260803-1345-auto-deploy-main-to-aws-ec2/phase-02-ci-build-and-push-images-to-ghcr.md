---
phase: 2
title: "CI: build and push images to GHCR on main"
status: pending
priority: P1
effort: "3-4h"
dependencies: [1]
---

# Phase 2: CI build and push images to GHCR on main

## Overview

Create the repo's first GitHub Actions workflow: on push to `main`, run lint + tests, then (only if they pass) build the `backend` and `frontend` Docker images and push both to GHCR tagged `sha-<short>` plus a branch-scoped mutable pointer (`main-latest`). This is the first half of the pipeline; Phase 3 adds the deploy job (to staging) that consumes these images.

## Requirements

- Functional: workflow triggers on `push` to `main` only (not every branch — feature branches don't build/push images).
- Functional: `ruff check` and `pytest` must both pass before any image build starts (single `test` job that `build-push` depends on via `needs:`).
- Functional: both images are pushed with **two tags each**: `sha-<short-sha>` (always, immutable, used for rollback and as the exact value every deploy pins) and `main-latest` (mutable, human-debugging convenience only — never used by the deploy job itself). No bare `:latest` tag is ever pushed.
- Non-functional: uses `docker/build-push-action` + `docker/login-action` with `${{ secrets.GITHUB_TOKEN }}` — no new secret needed for the push side (only the box-side pull in Phase 3 needs a separate PAT).

## Architecture

```text
.github/workflows/deploy.yml
  on: push: branches: [main]

  job: test
    - ruff check src/ tests/
    - pytest tests/ -v

  job: build-push (needs: test)
    - derive short_sha and branch_tag ("main-latest")
    - docker/login-action → ghcr.io (GITHUB_TOKEN)
    - build-push backend:  context .        dockerfile Dockerfile
      tags: ghcr.io/0infinitive0/vsf-intern-project-backend:sha-<short_sha>
            ghcr.io/0infinitive0/vsf-intern-project-backend:<branch_tag>
    - build-push frontend: context ./frontend dockerfile Dockerfile
      tags: ghcr.io/0infinitive0/vsf-intern-project-frontend:sha-<short_sha>
            ghcr.io/0infinitive0/vsf-intern-project-frontend:<branch_tag>

  job: deploy-staging (needs: build-push)    ← built in Phase 3
```

Use `docker/metadata-action` or a small shell step to derive `short_sha` from `github.sha` and `branch_tag` from `github.ref_name`, so both the image-tag step and Phase 3's deploy/rollback steps agree on the exact same values.

## Related Code Files

- Create: `.github/workflows/deploy.yml`
- Modify: none

## Implementation Steps

1. Create `.github/workflows/deploy.yml` with `on: push: branches: [main]` and a `test` job running `ruff check src/ tests/` then `pytest tests/ -v` (mirrors `Makefile`'s `check` target — reuse it: `make check` could replace both steps if `mypy` isn't wanted as a hard gate yet; keep it simple and call `ruff` + `pytest` directly to match what CI is documented to require in `docs/guide/devops/docker-cicd.md`).
2. Add `build-push` job with `needs: test`, `permissions: {contents: read, packages: write}`. Add a step that sets `short_sha` (first 7 chars of `github.sha`) and `branch_tag` (`main-latest`) as job outputs.
3. `docker/login-action@v3`: `registry: ghcr.io`, `username: ${{ github.actor }}`, `password: ${{ secrets.GITHUB_TOKEN }}`.
4. Two `docker/build-push-action@v6` steps (backend, frontend), each with `push: true` and both tags from step 2's outputs.
5. Push a throwaway commit to a scratch branch first (not `main`) to sanity-check the `test` job syntax before wiring the real trigger; confirm the final workflow only fires image push on `main`, and that a `main` push produces `main-latest` (never any other `-latest` pointer).

## Success Criteria

- [ ] `.github/workflows/deploy.yml` exists, `test` job runs `ruff check` + `pytest` on every push to `main`.
- [ ] A failing test blocks `build-push` (verified with a deliberately broken test on a scratch branch/PR before merging this phase).
- [ ] A push to `main` produces `sha-<short>` + `main-latest` tags for both images.
- [ ] No bare `:latest` tag exists in either GHCR package after this phase ships.
- [ ] No image is pushed for pushes to branches other than `main`.

## Risk Assessment

- **Risk:** default `GITHUB_TOKEN` permissions might not include `packages: write` depending on repo/org Actions settings. **Mitigation:** the job-level `permissions:` block declares it explicitly; if push still 403s, the fallback is enabling "Read and write permissions" under repo Settings → Actions → General → Workflow permissions (manual, one-time, called out in Phase 4).
- **Risk:** private-repo GHCR images default to private, invisible outside Actions unless the box authenticates. **Mitigation:** handled in Phase 3 (one-time `docker login ghcr.io` on the box with a PAT), not this phase's concern.
- **Risk:** because `main` is the only trigger, pushing broken code directly to `main` (no PR gate) means staging gets no image at all rather than a bad one — arguably the right failure mode, but worth confirming that's acceptable (it blocks staging deploys until fixed).
