---
phase: 3
title: "Data layer deployment"
status: pending
priority: P1
dependencies: [1, 2]
---

# Phase 3: Data Layer Deployment

## Overview

Provision managed PostgreSQL and load the V-OTA schema/data needed for the deployed API and demo flows. Output is a private RDS database with tested connectivity, backups, and repeatable seed/load commands.

## Requirements

- Functional: create `vsf_database`, apply `scripts/database_schema.sql`, load needed hotel/attraction/destination data, and expose a `DATABASE_URL` only to trusted runtimes.
- Non-functional: private network access, backups enabled, no public DB endpoint unless explicitly accepted for demo constraints, reproducible migration/load process.

## Architecture

```text
RDS PostgreSQL
  database: vsf_database
  private subnets/security group
  backups/snapshots

API App Runner service
  -> VPC connector if private RDS access is required
  -> DATABASE_URL from Secrets Manager/SSM

Loader path
  -> one-off admin host/ECS task/local VPN path
  -> psql -f scripts/database_schema.sql
  -> Airflow hotel/attraction loaders or controlled SQL/data import
```

Use RDS PostgreSQL instead of containerized Postgres for production durability. Keep Postgres private; only runtime services and operator migration paths should connect.

## Related Code Files

- Read/execute later: `scripts/database_schema.sql` - schema source of truth.
- Read: `src/airflow/dags/data_pipeline/hotel_pipeline.py` - hotel loader behavior.
- Read: `src/airflow/dags/data_pipeline/osm_pipeline.py` - destinations/attractions write pattern.
- Read: `data/agoda.json`, `data/booking.json` - hotel source data.
- Modify later: `.env.example` - production DB URL documentation only.
- Create later: `scripts/aws-db-init.md` or `docs/aws-deployment.md` - exact runbook if accepted.

## Implementation Steps

1. Provision RDS PostgreSQL:
   - smallest acceptable instance for demo/dev.
   - encrypted storage.
   - automated backups.
   - private subnet/security group when VPC is configured.
2. Create database/user:
   - `vsf_database`
   - least-privilege app user
   - separate admin/migration credentials if needed
3. Apply schema from `scripts/database_schema.sql`.
4. Load data:
   - run hotel loader against `data/agoda.json` and `data/booking.json`.
   - run or import attraction/destination data needed for demo flows.
5. Validate record counts:
   - hotels from both OTA sources.
   - rooms and room_prices.
   - attractions and destinations with valid coordinates.
6. Store the final app connection string in Secrets Manager/SSM as `DATABASE_URL`.
7. Capture backup and restore steps:
   - manual snapshot before destructive loader changes.
   - restore validation against a throwaway database if time allows.

## Success Criteria

- [ ] RDS is reachable only from approved runtime/operator paths.
- [ ] `scripts/database_schema.sql` applies cleanly.
- [ ] Required demo data exists and row counts are documented.
- [ ] API runtime can connect using secret-managed `DATABASE_URL`.
- [ ] Backup/snapshot and restore procedure is written.

## Risk Assessment

Main risk is spending time on cloud networking before proving the data import path. Mitigation: first validate schema/load against a temporary reachable database, then lock down security groups and App Runner/ECS connectivity.
