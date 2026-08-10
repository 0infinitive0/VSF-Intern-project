---
phase: 2
title: "Images, secrets and storage"
status: pending
priority: P1
dependencies: [1]
---

# Phase 2: Images, Secrets And Storage

## Overview

Make the local Airflow stack reproducible on AWS. Build immutable images and move credentials, DAG artifacts and raw files to managed or versioned locations.

## Related files

- Read/modify: `src/airflow/docker-compose.yaml`
- Read: `src/airflow/Dockerfile`, `src/airflow/dashboard/Dockerfile`
- Read: `src/airflow/requirements.txt`
- Create: AWS deployment env template and redacted operator runbook

## Implementation steps

1. Build images from a clean checkout:
   - `v-ota-airflow:<git-sha>`
   - `v-ota-dashboard:<git-sha>`
2. Push images to private ECR repositories with scan-on-push where available.
3. Store secrets in Secrets Manager or SSM:
   - Airflow Fernet key.
   - Airflow JWT secret and admin credential.
   - RDS metadata connection string.
   - `vsf_database` application connection string.
   - external API keys used by DAGs.
4. Create an S3 bucket with block-public-access enabled and prefixes for raw inputs, exports and optional task artifacts.
5. Enable S3 encryption, lifecycle retention and versioning where recovery matters.
6. Replace local `../../data` bind mounts with an explicit sync/download step or S3-aware DAG input path.
7. Do not deploy the `adminer` service from Compose.

## Success criteria

- [ ] Both images build and are retrievable by the EC2 role.
- [ ] Secrets are referenced at runtime and absent from image layers/logs.
- [ ] S3 bucket is private and lifecycle policy is documented.
- [ ] DAG image contains all Python and Playwright dependencies without startup pip installs.

## Risks

Local bind mounts can hide undeclared runtime dependencies. Run the image with an empty local data directory before deployment and list every required file explicitly.
