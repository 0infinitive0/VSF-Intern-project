---
title: "Deploy V-OTA to AWS"
description: "Deploy the V-OTA backend, data store, and optional Airflow/dashboard stack to AWS with a small production-ready footprint."
status: pending
priority: P1
branch: "main"
tags: [infra, aws, backend, database, deploy]
blockedBy: []
blocks: []
created: "2026-07-23"
createdBy: "ck:plan"
source: skill
---

# Deploy V-OTA to AWS

## Overview

Deploy V-OTA to AWS without rebuilding the application. Use the existing root `Dockerfile` for the FastAPI API, provision a managed PostgreSQL database, move secrets into AWS-managed secret storage, and deploy Airflow/dashboard only after the API/data layer is stable.

Recommended first production topology:

```text
GitHub Actions/manual CLI
  -> Amazon ECR
  -> AWS App Runner: FastAPI API container
  -> Amazon RDS PostgreSQL: vsf_database
  -> AWS Secrets Manager or SSM Parameter Store: API keys, DB URL, LangSmith

Optional data operations tier:
  Amazon ECR images
  -> Amazon ECS Fargate services/tasks
  -> Airflow webserver/scheduler/worker + dashboard
  -> RDS PostgreSQL + optional ElastiCache Redis
```

Scope challenge:

- Existing code: root `Dockerfile` already starts `uvicorn src.main:app`, binds `${PORT:-8000}`, runs as non-root, and has `/health`; `railway.json` proves the API has already been deployed once with health checks. `src/airflow/docker-compose.yaml` is explicitly local-development-oriented and multi-container.
- Minimum change set: create AWS deployment configuration, push images to ECR, configure secrets, provision RDS, deploy API, then decide whether Airflow/dashboard need AWS runtime for Demo Day or can remain local/admin-only.
- Complexity: expect 5-8 files touched if implemented (`.github/workflows/`, deployment IaC/config, docs/env examples), no application rewrite, no new service abstractions.
- Selected scope: hold core AWS deployment scope, but split optional Airflow/dashboard from the API path so the API can ship first.

## Cross-Plan Dependencies

| Relationship | Plan | Status | Note |
|-------------|------|--------|------|
| Builds on | `260723-1223-deploy-api-to-railway` | completed | Reuses the API deployment readiness work: Dockerfile, `/health`, port binding, env discipline. Target changes from Railway to AWS. |
| Supports | `260723-1015-v-ota-poc-master-roadmap` | in-progress | Provides AWS live URL and managed data services for M2/M3 demo-readiness. Does not block current local data-pipeline work. |

## Phases

| Phase | Name | Status |
|-------|------|--------|
| 1 | [AWS target architecture](./phase-01-aws-target-architecture.md) | Pending |
| 2 | [Container registry and secrets](./phase-02-container-registry-and-secrets.md) | Pending |
| 3 | [Data layer deployment](./phase-03-data-layer-deployment.md) | Pending |
| 4 | [API service deployment](./phase-04-api-service-deployment.md) | Pending |
| 5 | [Airflow and dashboard deployment](./phase-05-airflow-and-dashboard-deployment.md) | Pending |
| 6 | [CI CD and release validation](./phase-06-ci-cd-and-release-validation.md) | Pending |

## Acceptance Criteria

- [ ] AWS account, region, IAM boundary, and cost ceiling are documented before resources are created.
- [ ] API image builds from the existing root `Dockerfile` and is pushed to ECR with immutable release tags.
- [ ] Secrets are referenced from AWS Secrets Manager or SSM Parameter Store; no real secret values are committed.
- [ ] RDS PostgreSQL contains `vsf_database` schema and loaded data needed by API/demo flows.
- [ ] App Runner serves the FastAPI API publicly or behind the selected domain, and `/health` returns HTTP 200.
- [ ] Airflow/dashboard deployment is either completed on ECS Fargate or explicitly deferred with a documented local/admin fallback.
- [ ] CI/CD can build, test, push, deploy, and run smoke checks from a clean checkout.
- [ ] Rollback instructions exist for image rollback, App Runner service rollback/redeploy, and database snapshot restore.

## Explicitly Out Of Scope

- Rewriting application behavior, LangGraph agent logic, bilingual search, or itinerary planning.
- Migrating to Kubernetes/EKS.
- Replacing Airflow with MWAA in the first pass.
- Adding authentication unless AWS exposure requires a minimal access-control gate for admin surfaces.
- Hardcoding AWS account IDs, ARNs, credentials, or private endpoint values in git.

## AWS Docs Checked

- App Runner can run services from source images in ECR and manages runtime/load balancing: https://docs.aws.amazon.com/apprunner/latest/dg/service-source-image.html
- App Runner supports secret references through Secrets Manager/SSM; `PORT` is reserved: https://docs.aws.amazon.com/apprunner/latest/dg/env-variable.html
- ECR push flow requires an existing repository and Docker auth via `aws ecr get-login-password`: https://docs.aws.amazon.com/AmazonECR/latest/userguide/docker-push-ecr-image.html
- ECS Fargate task definitions support environment variables and secrets, but plaintext env vars are not recommended for sensitive data: https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task_definition_parameters.html
- App Runner HTTP health checks can target a configured path such as `/health`: https://docs.aws.amazon.com/apprunner/latest/dg/manage-configure-healthcheck.html

## Risks

| Risk | Mitigation |
|------|------------|
| Airflow stack is treated like a simple web app | Keep API on App Runner; deploy Airflow/dashboard separately on ECS Fargate only if needed. |
| Cost creep from always-on multi-container services | Start with App Runner + RDS only; make Airflow scheduled/on-demand where possible; set AWS Budgets before deploy. |
| Public admin surfaces expose Airflow/Adminer/dashboard | Do not expose Adminer publicly; restrict Airflow/dashboard by VPN, IP allowlist, Cognito/ALB auth, or skip cloud deployment. |
| Data migration succeeds once but is not reproducible | Codify schema import, loader runbook, and smoke SQL checks before declaring deployment complete. |
| Secrets leak through plain env, logs, or docs | Use Secrets Manager/SSM references and redact all local `.env` values from docs, CI logs, and issue bodies. |

## Next Step

Recommended gate before implementation:

```text
/ck:plan red-team /Users/takiet/Documents/projects/ai_thuc_chien_2026/thuc tap/VSF-Intern-project/plans/260723-1720-deploy-to-aws
```

Implementation handoff after review:

```text
/ck:cook /Users/takiet/Documents/projects/ai_thuc_chien_2026/thuc tap/VSF-Intern-project/plans/260723-1720-deploy-to-aws/plan.md
```
