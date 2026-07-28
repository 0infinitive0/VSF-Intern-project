# VSF Project Setup Guide

This guide provides step-by-step instructions to host the VSF Real-Time Dashboard, the Database, and the Apache Airflow data pipelines on a local machine or server.

## Prerequisites
- **Git** (to clone the repository)
- **Docker Desktop** or **Docker Engine & Docker Compose**
- **Resources**: Make sure Docker is allocated at least **4GB RAM** and **2 CPUs**, as Airflow can be resource-intensive.

## Step 1: Clone the Repository
Clone the project repository to your local machine and navigate to the project directory:
```bash
git clone <repository_url>
cd vsf-project
```

## Step 2: Start the Services
The project uses Docker Compose to manage all of its services, including Airflow, Postgres, and the custom Dashboard.

The root stack (`qdrant`, `ollama`) and the Airflow stack are two separate Compose
projects that share one external network so the Airflow scheduler/worker can
reach Qdrant/Ollama by service name. Create it once (idempotent — no-op if it
already exists):
```bash
docker network create vsf-shared
```

`airflow-scheduler` and `airflow-worker` also load the root `.env` (in
addition to `src/airflow/.env`) for `QDRANT_API_KEY`/`SUPABASE_URL`/
`SUPABASE_SERVICE_KEY` — make sure the root `.env` exists (see `.env.example`)
before starting the Airflow stack, or those two containers will fail to start.

**`QDRANT_API_KEY` is mandatory** (Phase 6) — the root `docker-compose.yml`'s
`qdrant` service has no unauthenticated fallback; `docker compose up` refuses
to start at all if it's unset. Any non-empty value works for local
development; see `.env.example`. The local Qdrant is bound to `127.0.0.1`
only (not reachable from outside the host) and has no TLS in front of it, so
the key travels as a cleartext header — acceptable only because it's
loopback-bound, not because the key alone secures it.

Navigate into the `src/airflow` directory. First, initialize the Airflow environment:
```bash
cd src/airflow
docker compose up airflow-init
```
Wait for the initialization to complete (you should see a `exited with code 0` message).

Next, build the custom dashboard image and start the entire stack:
```bash
docker compose build dashboard
docker compose up -d
```
*(This starts Airflow Webserver, Scheduler, Worker, Triggerer, Redis, Postgres, Adminer, and the Dashboard in the background).*

## Step 3: Initialize the Custom Database
The Postgres container spins up with a default `airflow` database for Airflow's internal state. However, the custom dashboard expects a database named `vsf_database` populated with your data schema.

You can initialize it by running these commands from the root `vsf-project` directory:

1. **Create the `vsf_database`:**
```bash
docker exec airflow-postgres-1 psql -U airflow -c "CREATE DATABASE vsf_database;"
```

2. **Import the Database Schema (and any data):**
```bash
docker exec -i airflow-postgres-1 psql -U airflow -d vsf_database < scripts/database_schema.sql
```

## Step 4: Access the Applications
Once all the containers are running and the database is populated, you can access the following services in your web browser:

- 🗺️ **Real-Time Dashboard**: http://localhost:8082
- 💾 **Database Manager (Adminer)**: http://localhost:8081
  - **System**: PostgreSQL
  - **Server**: postgres
  - **Username**: airflow
  - **Password**: airflow
  - **Database**: vsf_database
- 🌪️ **Apache Airflow UI**: http://localhost:8080
  - **Username**: airflow
  - **Password**: airflow

## Qdrant Snapshot & Restore

Before a change that rewrites a Qdrant collection (e.g. re-running a full
hotel sync), take a manual snapshot: `scripts/qdrant_snapshot.sh` is not
scheduled — the hotel corpus rebuilds from Supabase through `hotel_dag` in
minutes, so a manual pre-change snapshot is proportionate; scheduled backups
belong in a deployment plan.

```bash
# Create + download a snapshot of a collection
QDRANT_URL=http://localhost:6333 QDRANT_API_KEY=<your key> \
  scripts/qdrant_snapshot.sh create hotels_vector

# Restore into a NEW collection (verify before trusting the backup — an
# untested backup is not a backup):
QDRANT_URL=http://localhost:6333 QDRANT_API_KEY=<your key> \
  scripts/qdrant_snapshot.sh restore ./data/qdrant_snapshots/<snapshot_file> hotels_vector_restore_test
```

Restoring into `hotels_vector` directly would overwrite live data — always
restore into a scratch collection name first, verify the point count matches
(`GET /collections/<name>`), then decide whether to alias/rename it into
place.

## Useful Commands & Troubleshooting

- **Checking logs**: 
  If any service isn't working, check its logs. For example, for the dashboard or airflow webserver:
  ```bash
  docker logs airflow-dashboard-1
  docker logs airflow-airflow-apiserver-1
  ```
- **Updating Dashboard Code**: 
  If you modify `app.py` or `index.html` inside the `dashboard` folder, you must rebuild the image for changes to take effect:
  ```bash
  docker compose build dashboard && docker compose up -d dashboard
  ```
- **Adding Airflow DAGs**:
  Place your Python DAG scripts inside the `dags/` folder. Airflow will automatically detect and load them. You may need to enable them in the Airflow UI at `http://localhost:8080`.
- **Missing Data on Map**: 
  If the map is blank, ensure that the `attractions`, `destinations`, and `hotels` tables in the `vsf_database` actually have rows containing valid `coordinates`.
