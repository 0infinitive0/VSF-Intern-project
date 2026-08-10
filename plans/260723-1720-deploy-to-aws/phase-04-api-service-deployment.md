---
phase: 4
title: "API service deployment"
status: pending
priority: P1
dependencies: [2, 3]
---

# Phase 4: API Service Deployment

## Overview

Deploy the FastAPI container to AWS App Runner and verify it starts, reads production configuration, connects to the data layer, and passes smoke checks.

## Requirements

- Functional: App Runner service from ECR image, `/health` HTTP health check, env/secrets configured, public service URL or custom domain.
- Non-functional: repeatable deployment, no secret leakage, observable logs, quick rollback to previous image.

## Architecture

```text
ECR v-ota-api:<git-sha>
  -> App Runner service
  -> HTTP health check /health
  -> CloudWatch Logs
  -> RDS PostgreSQL via secure network path
```

The current root `Dockerfile` already supports AWS-style dynamic ports by running `uvicorn` through `/bin/sh -c` with `${PORT:-8000}`. Keep App Runner's runtime port aligned with the service configuration and do not override reserved `PORT` manually.

## Related Code Files

- Read: `Dockerfile` - API image start command and health check.
- Read: `src/main.py` - `/health` and CORS middleware.
- Read: `src/api/routes.py` - smoke endpoints.
- Read: `src/config.py` - settings loaded from env.
- Modify later: `railway.json` not required for AWS; leave it unless removing Railway support is explicitly requested.
- Create later: AWS App Runner service config/IaC if the team chooses CLI-managed deploys over console setup.

## Implementation Steps

1. Create App Runner service from private ECR image `v-ota-api:<git-sha>`.
2. Configure service:
   - port: app container port expected by App Runner.
   - health check: HTTP `/health`.
   - CPU/memory: smallest tier that handles demo latency.
   - auto deploy: enable only after CI tagging strategy is stable.
3. Configure runtime env:
   - plain: `APP_ENV=production`, `LOG_LEVEL=INFO`, `CORS_ORIGINS`.
   - secrets: `OPENAI_API_KEY`, `DATABASE_URL`, LangSmith variables.
4. Configure VPC/network path to RDS if the database is private.
5. Deploy and monitor logs until service is healthy.
6. Smoke test:
   ```bash
   curl -fsS https://<api-url>/health
   curl -fsS https://<api-url>/api/v1/status
   ```
7. Record rollback:
   - previous ECR image tag.
   - App Runner redeploy/update command or console path.
   - post-rollback smoke checks.

## Success Criteria

- [ ] App Runner deployment reaches running/healthy state.
- [ ] `/health` returns HTTP 200.
- [ ] `/api/v1/status` returns expected response.
- [ ] Production service logs are visible in CloudWatch.
- [ ] API can reach RDS or clearly documents data-dependent endpoint limitations.
- [ ] Rollback to previous image tag is documented and tested once if possible.

## Risk Assessment

Main risk is hidden runtime config mismatch between Railway/local and App Runner. Mitigation: keep the existing Dockerfile contract, use the same smoke endpoints, and fail deployment on missing required secret references.
