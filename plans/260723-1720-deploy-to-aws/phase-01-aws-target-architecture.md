---
phase: 1
title: "AWS target architecture"
status: pending
priority: P1
dependencies: []
---

# Phase 1: AWS Target Architecture

## Overview

Select the smallest AWS architecture that can host the current system without application rewrites. Output is an approved topology, resource list, naming convention, and deployment boundary.

## Requirements

- Functional: decide AWS region, runtime services, public URLs, internal-only admin surfaces, and rollback boundary.
- Non-functional: keep costs bounded, avoid public database access, minimize first-deploy moving parts, keep Demo Day live URL reliable.

## Architecture

Recommended baseline:

```text
Public internet
  -> App Runner default/custom domain
  -> FastAPI API container from ECR
  -> RDS PostgreSQL in private subnets
  -> Secrets Manager or SSM Parameter Store

Operator/admin path
  -> AWS Console/CLI/GitHub Actions
  -> ECS Fargate tasks/services for Airflow/dashboard only if needed
```

Use App Runner for the API because the root app is one web container with `/health` and no container-to-container runtime dependency. Use ECS Fargate for Airflow/dashboard because `src/airflow/docker-compose.yaml` has multiple long-running services, Redis, scheduler/worker roles, and local volume assumptions.

## Related Code Files

- Read: `Dockerfile` - current API container contract.
- Read: `railway.json` - existing health-check path.
- Read: `src/main.py` - `/health` endpoint and CORS setup.
- Read: `src/config.py` - runtime settings and env variable names.
- Read: `src/airflow/docker-compose.yaml` - local Airflow stack shape.
- Modify later: `ARCHITECTURE.md` or `docs/SETUP_GUIDE.md` only if AWS deployment becomes maintained project workflow.

## Implementation Steps

1. Pick AWS region. Default recommendation: one region near users/team, e.g. `ap-southeast-1` if latency from Vietnam matters, otherwise cheapest/available team region.
2. Define AWS naming convention: `v-ota-{env}-{component}`, with `dev` and optional `prod`.
3. Decide account boundary: single AWS account for demo, least-privilege IAM roles, no long-lived user access keys in repo.
4. Confirm which surfaces must be public:
   - Public: FastAPI API and later frontend.
   - Private/restricted: RDS, Airflow UI, Adminer-equivalent tooling, dashboard if it exposes operational data.
5. Choose baseline services:
   - ECR for images.
   - App Runner for API.
   - RDS PostgreSQL for `vsf_database`.
   - Secrets Manager or SSM Parameter Store for secrets.
   - CloudWatch Logs for app/runtime logs.
6. Choose optional services only if needed:
   - ECS Fargate for Airflow/dashboard.
   - ElastiCache Redis only if keeping CeleryExecutor in AWS; otherwise simplify Airflow executor before deploy.
   - S3 for raw data files and backups.
7. Write a cost ceiling and shutdown plan before provisioning non-free-tier resources.

## Success Criteria

- [ ] Architecture decision records public/private surfaces and why.
- [ ] AWS service list is approved before implementation.
- [ ] No plan requires EKS, Kubernetes, or application rewrite for first AWS deployment.
- [ ] Airflow/dashboard is explicitly marked optional or restricted-admin, not silently public.
- [ ] Cost controls are listed: budget alert, right-sized RDS, right-sized App Runner/ECS, cleanup steps.

## Risk Assessment

Main risk is overbuilding AWS infrastructure before the app is ready. Mitigation: deploy API and database first; add Airflow/dashboard only when demo requirements need cloud pipeline operation.
