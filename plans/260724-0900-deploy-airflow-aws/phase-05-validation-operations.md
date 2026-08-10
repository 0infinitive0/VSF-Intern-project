---
phase: 5
title: "Validation, operations and ECS migration gate"
status: pending
priority: P1
dependencies: [4]
---

# Phase 5: Validation, Operations And ECS Migration Gate

## Overview

Prove the deployed pipeline works, is recoverable and can be operated safely. Decide whether the single-EC2 runtime is sufficient or should move to ECS Fargate.

## Smoke and acceptance checks

1. Confirm EC2, RDS and S3 are in the intended region/account.
2. Confirm Airflow UI is not internet-public and Adminer is absent.
3. Trigger one representative DAG manually and verify:
   - task state reaches success;
   - expected rows exist in `vsf_database`;
   - logs are available after task completion;
   - retries do not duplicate rows unexpectedly.
4. Validate dashboard queries using read-only credentials.
5. Restart one worker and then the full Compose stack; verify scheduler recovery.
6. Test image rollback to the previous Git-SHA tag.
7. Rehearse RDS snapshot restore into a non-production target.
8. Record CPU, memory, disk, worker concurrency and monthly cost estimate.

## ECS migration gate

Move to ECS Fargate only when at least one of these is true:

- EC2 uptime or capacity is insufficient.
- Airflow components need independent scaling or replacement.
- Multiple operators need a managed private service endpoint.
- The team can provide task definitions, EFS/S3 logging strategy, managed Redis and a secure ALB/auth boundary.

## Success criteria

- [ ] Representative DAG and dashboard validation pass.
- [ ] Rollback and restore procedures are documented and rehearsed.
- [ ] Cost and operational ownership are accepted.
- [ ] ECS decision is recorded as proceed or defer with reasons.

## Failure handling

If the DAG fails, preserve task logs and the failing image tag, stop repeated destructive retries, restore the last known-good database snapshot when required, and fix the cause before re-running.
