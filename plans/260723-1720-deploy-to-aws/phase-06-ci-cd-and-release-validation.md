---
phase: 6
title: "CI CD and release validation"
status: pending
priority: P1
dependencies: [4, 5]
---

# Phase 6: CI CD And Release Validation

## Overview

Automate and validate the AWS release path after manual deployment succeeds. Output is a CI/CD workflow, smoke-test checklist, rollback runbook, and deployment documentation.

## Requirements

- Functional: test, build, push, deploy, smoke check, and rollback path from a clean checkout.
- Non-functional: no long-lived AWS keys where GitHub OIDC is possible, no deploy on failing tests, minimal permissions, clear production runbook.

## Architecture

```text
GitHub Actions
  -> pytest/ruff
  -> docker build
  -> ECR push
  -> App Runner service update
  -> smoke checks
  -> deployment summary

Manual emergency path
  -> AWS CLI/console
  -> redeploy previous image tag
  -> smoke checks
```

There is currently no `.github/` directory in the repo, so CI/CD is a new project surface. Keep it narrow: API deploy first, optional ECS deploy only after Phase 5 is accepted.

## Related Code Files

- Create: `.github/workflows/deploy-aws.yml` - CI/CD workflow.
- Create or modify: `docs/aws-deployment.md` - operator runbook.
- Modify: `.env.example` - AWS production variable notes, no real values.
- Read: `Makefile` - existing `test`, `lint`, `check` commands.
- Read: `tests/` - current API/agent test coverage.

## Implementation Steps

1. Define branch and environment policy:
   - `main` deploys to dev/demo AWS environment.
   - manual approval or protected environment for production if used.
2. Create GitHub OIDC role in AWS with scoped permissions:
   - ECR push for relevant repos.
   - App Runner update/read.
   - ECS update only if Phase 5 cloud deploy is accepted.
   - no broad admin policy.
3. Add workflow:
   - install Python dependencies.
   - run `ruff check src/ tests/`.
   - run `pytest tests/ -v`.
   - build Docker image.
   - push git-SHA tag to ECR.
   - update App Runner image/service.
   - run `/health` and `/api/v1/status` smoke checks.
4. Add release notes template:
   - image tag.
   - service URL.
   - smoke result.
   - migration/data action performed.
5. Add rollback runbook:
   - find previous successful image tag.
   - update App Runner service back to previous image.
   - verify `/health`.
   - restore RDS snapshot only for data-corruption incidents.
6. Add post-deploy monitoring checklist:
   - CloudWatch error logs.
   - HTTP 5xx count.
   - API latency for demo endpoints.
   - RDS connection errors.

## Success Criteria

- [ ] CI refuses deployment when lint/tests fail.
- [ ] CI pushes immutable ECR image tags.
- [ ] App Runner update is automated or documented with exact manual command.
- [ ] Smoke checks run after deploy and fail the workflow on non-200 responses.
- [ ] `docs/aws-deployment.md` documents deploy, rollback, secrets, data init, and known deferrals.
- [ ] Final live URL and operational owner are recorded for Demo Day handoff.

## Risk Assessment

Main risk is adding CI/CD before a manual path is stable. Mitigation: run the first AWS deployment manually or semi-manually, then automate the proven commands and keep optional ECS deployment out of the first CI workflow until stable.
