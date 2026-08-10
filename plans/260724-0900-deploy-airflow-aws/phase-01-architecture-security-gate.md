---
phase: 1
title: "Architecture, account and security gate"
status: pending
priority: P1
dependencies: []
---

# Phase 1: Architecture, Account And Security Gate

## Overview

Approve the AWS target before provisioning. This phase fixes the region, network boundary, compute choice, public/private surfaces, budget and operator access method.

## Requirements

- Functional: choose EC2-first deployment and define the ECS migration boundary.
- Non-functional: no public SSH, database, Redis, Airflow UI or Adminer by default.

## Architecture

```text
Operator -> SSM Session Manager -> private EC2 -> Docker Compose Airflow stack
                                      |-> RDS PostgreSQL
                                      |-> Redis (first stage)
                                      |-> S3 raw files / artifacts
                                      |-> CloudWatch logs
```

## Implementation steps

1. Choose region, initially `ap-southeast-1` unless the AWS account/cost policy requires another region.
2. Confirm account identity and create an AWS Budget alert before provisioning.
3. Create or reuse a VPC with private subnets for RDS and EC2; add a controlled egress path for image pulls and external data APIs.
4. Create security groups:
   - EC2 inbound: SSM only; no `22` from the internet.
   - RDS inbound: PostgreSQL only from EC2 security group and approved migration path.
   - No public Redis/Adminer ports.
5. Create IAM roles for EC2: SSM, read-only secret access, S3 prefix access, ECR pull and CloudWatch logs.
6. Record public/private URL decisions: Airflow and dashboard private; no Adminer deployment.

## Success criteria

- [ ] Account and region are confirmed.
- [ ] Budget alert exists.
- [ ] EC2, RDS, S3 and secret access follows least privilege.
- [ ] Operator can reach EC2 through SSM without opening public SSH.

## Risks

The main risk is creating a publicly reachable admin/data platform. Mitigate with private subnets, security groups, SSM and an explicit gateway decision.
