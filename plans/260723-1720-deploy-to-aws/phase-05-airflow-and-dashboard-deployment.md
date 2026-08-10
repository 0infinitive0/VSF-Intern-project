---
phase: 5
title: "Airflow and dashboard deployment"
status: pending
priority: P2
dependencies: [2, 3]
---

# Phase 5: Airflow And Dashboard Deployment

## Overview

Decide whether the Airflow/data dashboard stack must run on AWS for the demo. If yes, deploy it as restricted ECS Fargate services/tasks; if no, keep it local/admin-only and document the operational fallback.

## Requirements

- Functional: either deploy Airflow/dashboard cloud runtime or explicitly defer it with a local runbook.
- Non-functional: no public Adminer, no public default Airflow credentials, controlled scheduler/worker cost, logs available for failed DAGs.

## Architecture

Cloud option:

```text
ECR v-ota-airflow:<git-sha>
  -> ECS Fargate services/tasks
  -> Airflow apiserver/scheduler/dag-processor/worker
  -> RDS PostgreSQL
  -> Redis-compatible broker if CeleryExecutor remains
  -> CloudWatch Logs

ECR v-ota-dashboard:<git-sha>
  -> ECS Fargate service or internal ALB target
  -> RDS PostgreSQL
```

Deferral option:

```text
Local operator machine
  -> src/airflow/docker-compose.yaml
  -> local Postgres/Airflow/dashboard
  -> exported screenshots/data evidence for Demo Day
```

Do not run the local Docker Compose file unchanged as a public production stack. It has local-development warnings, default credentials, host port assumptions, and local volume mounts.

## Related Code Files

- Read/modify later: `src/airflow/docker-compose.yaml` - source for service roles, not production config.
- Read: `src/airflow/Dockerfile` - Airflow image.
- Read: `src/airflow/requirements.txt` - Airflow dependencies.
- Read: `src/airflow/dashboard/Dockerfile` - dashboard image.
- Read: `src/airflow/dashboard/app.py` - dashboard DB access and public-surface review.
- Create later: ECS task definitions/service config if cloud option is accepted.

## Implementation Steps

1. Make a go/no-go decision:
   - Deploy to AWS only if cloud-run DAGs or dashboard access are required for the demo.
   - Defer if the API live URL plus documented data evidence is sufficient.
2. If deploying:
   - Build/push `v-ota-airflow` and `v-ota-dashboard` images to ECR.
   - Convert Compose services into ECS task definitions or separate services.
   - Replace local volumes with S3/EFS only where needed.
   - Use RDS for metadata/data stores intentionally; avoid mixing Airflow metadata and app data unless accepted.
   - Provide Redis broker if keeping CeleryExecutor, or simplify executor for the first AWS deploy.
3. Lock down access:
   - no public Adminer.
   - Airflow UI behind VPN/IP allowlist/Cognito/ALB auth.
   - rotate default `airflow/airflow` credentials.
4. Configure DAG logs to CloudWatch.
5. Run one controlled DAG and verify RDS data output.
6. If deferring:
   - write local runbook commands from `docs/SETUP_GUIDE.md`.
   - capture data evidence and dashboard screenshots.
   - state that AWS production runtime is API + RDS only.

## Success Criteria

- [ ] Decision recorded: cloud deploy or defer.
- [ ] If deployed, Airflow UI is restricted and no default credentials remain.
- [ ] If deployed, at least one DAG run succeeds and logs are available.
- [ ] If deployed, dashboard can read expected RDS rows without exposing DB credentials.
- [ ] If deferred, local/admin runbook and demo evidence are documented.

## Risk Assessment

Main risk is turning a demo deployment into a full data-platform migration. Mitigation: require an explicit go/no-go, restrict admin surfaces, and treat ECS Airflow as optional Phase 5 rather than a prerequisite for the API.
