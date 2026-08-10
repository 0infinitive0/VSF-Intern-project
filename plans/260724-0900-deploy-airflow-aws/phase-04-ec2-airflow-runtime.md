---
phase: 4
title: "EC2 Airflow runtime"
status: pending
priority: P1
dependencies: [2, 3]
---

# Phase 4: EC2 Airflow Runtime

## Overview

Run the Compose-derived Airflow stack on a right-sized EC2 instance with private service networking and an operator-only access path.

## Implementation steps

1. Launch an EC2 instance with Docker, Compose plugin, SSM agent and an encrypted EBS volume sized for logs/cache.
2. Pull the pinned Airflow and dashboard images from ECR.
3. Create a production Compose override that:
   - removes Adminer and host database/Redis port mappings;
   - uses RDS connection strings instead of the local Postgres service;
   - uses secret references/materialized runtime env from SSM/Secrets Manager;
   - persists only required logs/config on encrypted EBS;
   - adds restart policies and resource limits.
4. Start services in dependency order: metadata migration/init, Redis, Airflow API, scheduler, DAG processor, worker, triggerer, dashboard.
5. Use an SSM port-forwarding tunnel for first UI validation. Add an internal ALB/auth layer only when multiple operators need access.
6. Configure CloudWatch agent or Docker log driver for Airflow component logs.
7. Run a controlled DAG and monitor CPU, memory, disk, worker queue and database connections.

## Services

| Service | First-stage location | Public? |
|---|---|---|
| Airflow API server | EC2 container | No |
| Scheduler/DAG processor/worker/triggerer | EC2 containers | No |
| Redis | EC2 private network | No |
| Airflow metadata DB | RDS PostgreSQL | No |
| V-OTA data DB | RDS PostgreSQL | No |
| Dashboard | EC2 container | No, unless protected gateway exists |
| Adminer | Not deployed | No |

## Success criteria

- [ ] All required Airflow services become healthy.
- [ ] UI works through SSM tunnel or approved private gateway.
- [ ] One hotel/attraction DAG completes and writes expected records.
- [ ] No default credentials or public admin ports remain.

## Risks

EC2 is operationally simple for this Compose stack but creates a single-host failure boundary. Document restart and replacement steps; do not call it highly available until ECS or a multi-host design exists.
