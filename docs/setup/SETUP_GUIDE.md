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

## Step 5: Start the Terminal OTA Chat CLI

The VSF Trip Planner provides an interactive, terminal-based AI Agent chat interface for creating, modifying, and finalizing trip itineraries.

### 1. Prerequisites
- **Environment**: Ensure `.env` is configured with `SUPABASE_URL` and `SUPABASE_SERVICE_KEY`.
- **Local Ollama**: Ensure Ollama is running and models are pulled:
  ```bash
  ollama pull llama3.1
  ollama pull bge-m3
  ```

### 2. Launching the Terminal Chat
Run the terminal interactive loop:
```bash
# Activate virtual environment first
source .venv/bin/activate        # Linux/macOS
# .\.venv\Scripts\activate       # Windows PowerShell

python -m scripts.poc_trip_planner
```

### 3. Model Configuration Options (Optional)
You can configure different LLM/Embedding providers via environment variables:
```bash
# Default: Local Ollama
python -m scripts.poc_trip_planner

# OpenAI Provider
LLM_PROVIDER=openai LLM_MODEL=gpt-4o-mini LLM_API_KEY=sk-... python -m scripts.poc_trip_planner

# Google Gemini Provider
LLM_PROVIDER=google LLM_MODEL=gemini-1.5-flash LLM_API_KEY=AIzaSy... python -m scripts.poc_trip_planner
```

### 4. Conversation Workflow & Commands
- **New Trip Intake**:
  > *"Tôi muốn đi du lịch Hồ Chí Minh 3 ngày 2 người thích lịch sử và ẩm thực"*
- **Fact Clarification**: If core facts (destination, duration, party size) are missing, the agent will prompt for clarification.
- **Modifying Saved Plan**:
  > *"Đổi khách sạn sang Caravelle Saigon"*
  > *"Thay điểm tham quan ngày 2 bằng Bảo tàng Mỹ thuật"*
- **Finalizing Itinerary**:
  > *"Chốt lịch trình"* (Saves finalized state for Tier 1 template reuse).
- **Exit**: Type `exit`, `quit`, or `q`.

---

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

