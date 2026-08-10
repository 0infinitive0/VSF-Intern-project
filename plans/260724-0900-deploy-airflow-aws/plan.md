---
title: "Deploy Airflow to AWS"
description: "Deploy the V-OTA Airflow and dashboard stack to AWS with secure access, durable storage, and a staged EC2-first path."
status: pending
priority: P1
branch: "main"
tags: [infra, aws, airflow, data-pipeline, deploy]
blockedBy: []
blocks: []
created: "2026-07-24"
createdBy: "ck:plan"
source: user
---

# Deploy Airflow to AWS

## Outcome

Run the existing V-OTA Airflow data pipeline and dashboard on AWS without exposing development credentials or public database tools. The first delivery uses **EC2 + Docker Compose** because the repository already has a multi-container Compose topology; ECS Fargate remains the production migration path after the stack is stable.

## Current evidence

- `src/airflow/docker-compose.yaml` contains Airflow API server, scheduler, DAG processor, Celery worker, triggerer, Redis, Postgres, dashboard and Adminer.
- The Compose file is explicitly local-development-oriented: default `airflow/airflow` credentials, host port mappings, local bind mounts and a local Postgres metadata database.
- `src/airflow/Dockerfile` builds Airflow 3.3.0 with project requirements and Playwright Chromium.
- `src/airflow/dashboard/Dockerfile` runs the dashboard on port 8082.
- `docs/SETUP_GUIDE.md` documents local initialization and the split between Airflow metadata DB and `vsf_database`.
- AWS CLI identity check is currently blocked by STS connectivity; no AWS resource has been provisioned by this plan.

## Deployment decision

| Area | First deployment | Later hardening |
|---|---|---|
| Compute | EC2, private Docker network, Compose-derived services | ECS Fargate services/tasks |
| Airflow metadata | RDS PostgreSQL database/schema | Dedicated RDS database or schema with stricter isolation |
| Celery broker | Redis on EC2 for the first controlled deployment | ElastiCache/managed Redis |
| DAGs and raw files | Versioned image + S3 for large/raw files | S3 sync or EFS only where runtime write access is required |
| Dashboard | Internal EC2 port or private ALB | ECS service behind internal ALB/auth |
| Adminer | Not deployed | Keep private troubleshooting only |
| Access | SSM Session Manager; no SSH public exposure by default | VPN/ALB auth/Cognito or private access gateway |

## Scope

### Included

- Build and publish Airflow and dashboard images.
- Provision the minimum AWS network, EC2, RDS, S3 and secret/logging resources.
- Replace local credentials, bind mounts and public ports with AWS-safe configuration.
- Run one representative hotel or attraction DAG against the target database.
- Validate Airflow UI access, dashboard data reads, DAG logs, restart behavior and rollback.

### Excluded

- Rewriting DAG business logic or replacing Airflow with MWAA.
- Public exposure of Airflow, Adminer or the dashboard without an explicit auth boundary.
- Kubernetes/EKS.
- Automatic production autoscaling before the first successful controlled run.

## Phases

| Phase | Name | Status | Depends on |
|---|---|---|---|
| 1 | [Architecture, account and security gate](./phase-01-architecture-security-gate.md) | Pending | Existing AWS account/region decision |
| 2 | [Images, secrets and storage](./phase-02-images-secrets-storage.md) | Pending | Phase 1 |
| 3 | [Database and network integration](./phase-03-database-network-integration.md) | Pending | Phase 1, 2 |
| 4 | [EC2 Airflow runtime](./phase-04-ec2-airflow-runtime.md) | Pending | Phase 2, 3 |
| 5 | [Validation, operations and ECS migration gate](./phase-05-validation-operations.md) | Pending | Phase 4 |

## Acceptance criteria

- [ ] AWS region, account, budget ceiling, IAM roles and access boundary are recorded.
- [ ] Airflow and dashboard images build from a clean checkout and are tagged by Git SHA.
- [ ] No default Airflow password, DB password, Fernet key or API key is committed or printed in logs.
- [ ] Airflow metadata has durable PostgreSQL storage; application data is isolated in `vsf_database`.
- [ ] EC2 security group exposes no Postgres, Redis or Adminer ports to the public internet.
- [ ] Airflow UI and dashboard are private/restricted; access works through SSM tunnel or approved gateway.
- [ ] At least one DAG completes successfully and writes expected rows to the target database.
- [ ] Logs are available in CloudWatch or an explicitly documented first-stage log path.
- [ ] Restart, image rollback and database restore procedures are tested or documented with a safe rehearsal.
- [ ] ECS Fargate migration is either scheduled with prerequisites or explicitly deferred.

## Cross-plan dependency

This plan extends `plans/260723-1720-deploy-to-aws`. It assumes the AWS account/region and RDS/network decisions from that plan are approved. The API does not need to be migrated before local Airflow validation, but a shared production data store must be agreed before declaring the cloud pipeline complete.

## Rollback boundary

Rollback the EC2 Compose stack to the previous image tag and restore the last known-good database snapshot. Do not run destructive loaders against the production database without a snapshot and a row-count check. S3 objects are versioned or retained according to the selected lifecycle policy.
