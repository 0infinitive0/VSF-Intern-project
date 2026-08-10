---
phase: 3
title: "Database and network integration"
status: pending
priority: P1
dependencies: [1, 2]
---

# Phase 3: Database And Network Integration

## Overview

Prepare durable database connectivity for both Airflow metadata and V-OTA application data without mixing schemas accidentally.

## Implementation steps

1. Provision or select RDS PostgreSQL with encryption, backups and a private endpoint.
2. Create separate databases or clearly separated schemas:
   - Airflow metadata database.
   - `vsf_database` for hotels, rooms, prices, destinations and attractions.
3. Apply `scripts/database_schema.sql` to `vsf_database` through a controlled migration path.
4. Create separate least-privilege users for Airflow metadata, pipeline writes and dashboard/API reads.
5. Load a staging dataset and record row counts before touching production data.
6. Test EC2 → RDS connectivity from the private network and reject public endpoint assumptions.
7. Configure backup/snapshot and restore rehearsal before the first destructive loader run.

## Validation

- [ ] Airflow can initialize metadata tables.
- [ ] A DAG can write to `vsf_database`.
- [ ] Dashboard can read expected rows with read-only credentials.
- [ ] Public network cannot reach RDS.
- [ ] Row counts and restore point are recorded.

## Risks

Using the same database/password for Airflow and application data makes failure impact larger. Keep credentials and access policies separate even when one RDS instance is used for cost reasons.
