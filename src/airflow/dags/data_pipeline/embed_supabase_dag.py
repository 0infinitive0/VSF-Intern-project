"""Embed hotels/rooms/attractions text straight into their Supabase pgvector
`embedding` column via Ollama.

Airflow Variable `embed_supabase_only_null` (default "true") limits each run
to rows where `embedding IS NULL`, so scheduled runs only backfill new data.
Set it to "false" to force a full re-embed of every row.
Airflow Variable `embed_supabase_batch_limit` (default "200") caps how many
pending rows per table a single run maps over, so a large backlog doesn't
spawn an unbounded number of task instances in one run — schedule reruns
drain the rest incrementally.
"""

import json
import os
import sys
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from airflow import DAG
from airflow.decorators import task
from airflow.models import Variable

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DEFAULT_ARGS = {
    "owner": "data_team",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 1,
}

EMBEDDING_DIMENSION = 1024

# table -> select columns needed to build its embedding text
TABLE_COLUMNS = {
    "hotels": "id,name,accommodation_type,area_name,description,amenities",
    "rooms": "id,name,bed_description,view,room_facilities",
    "attractions": "id,name,description,category",
}


def _joined(value):
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value or "")


def _build_text(table, row):
    if table == "hotels":
        return (
            f"Tên: {row.get('name') or ''}\n"
            f"Loại hình: {row.get('accommodation_type') or ''}\n"
            f"Khu vực: {row.get('area_name') or ''}\n"
            f"Mô tả: {row.get('description') or ''}\n"
            f"Tiện ích: {_joined(row.get('amenities'))}"
        )
    if table == "rooms":
        return (
            f"Tên phòng: {row.get('name') or ''}\n"
            f"Giường: {row.get('bed_description') or ''}\n"
            f"Hướng nhìn: {row.get('view') or ''}\n"
            f"Tiện ích phòng: {_joined(row.get('room_facilities'))}"
        )
    return (
        f"Tên: {row.get('name') or ''}\n"
        f"Mô tả: {row.get('description') or ''}\n"
        f"Thể loại: {row.get('category') or ''}"
    )


def _supabase_headers(supabase_key):
    return {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json",
    }


def _require_supabase_creds():
    supabase_url = os.environ.get("SUPABASE_URL") or Variable.get("SUPABASE_URL", default_var=None)
    supabase_key = os.environ.get("SUPABASE_SERVICE_KEY") or Variable.get("SUPABASE_SERVICE_KEY", default_var=None)
    if not supabase_url or not supabase_key:
        raise ValueError("Missing SUPABASE_URL or SUPABASE_SERVICE_KEY in environment or variables.")
    return supabase_url, supabase_key


def _embed_text(base_url, model, text):
    # Ollama's single-prompt embeddings endpoint — stable across Ollama
    # versions, unlike the newer batch /api/embed endpoint.
    request = Request(
        f"{base_url}/api/embeddings",
        data=json.dumps({"model": model, "prompt": text}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=60) as response:
        payload = json.load(response)
    return payload["embedding"]


@task
def fetch_pending_rows_task(table):
    import requests

    supabase_url, supabase_key = _require_supabase_creds()
    only_null = Variable.get("embed_supabase_only_null", default_var="true").strip().lower() != "false"
    batch_limit = int(Variable.get("embed_supabase_batch_limit", default_var="200"))

    headers = _supabase_headers(supabase_key)
    columns = TABLE_COLUMNS[table]
    url = f"{supabase_url}/rest/v1/{table}?select={columns}&limit={batch_limit}"
    if only_null:
        url += "&embedding=is.null"

    response = requests.get(url, headers=headers)
    response.raise_for_status()
    rows = response.json()
    print(f"[{table}] fetched {len(rows)} pending rows (only_null={only_null})")
    return [{"table": table, "row": row} for row in rows]


@task(max_active_tis_per_dag=4)
def embed_row_task(item):
    import requests

    table = item["table"]
    row = item["row"]
    row_id = row.get("id")

    supabase_url, supabase_key = _require_supabase_creds()
    ollama_base_url = os.environ.get("OLLAMA_BASE_URL", "http://host.docker.internal:11434").rstrip("/")
    embedding_model = os.environ.get("EMBEDDING_MODEL", "bge-m3")

    text = _build_text(table, row)
    try:
        vector = _embed_text(ollama_base_url, embedding_model, text)
    except (URLError, HTTPError, KeyError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"[{table}/{row_id}] embedding failed: {exc}")
        return None

    if len(vector) != EMBEDDING_DIMENSION:
        print(f"[{table}/{row_id}] unexpected embedding dimension {len(vector)} != {EMBEDDING_DIMENSION}")
        return None

    headers = _supabase_headers(supabase_key)
    headers["Prefer"] = "return=minimal"
    patch_response = requests.patch(
        f"{supabase_url}/rest/v1/{table}?id=eq.{row_id}",
        headers=headers,
        json={"embedding": vector},
    )
    patch_response.raise_for_status()
    print(f"[{table}/{row_id}] embedded")
    return row_id


@task
def summarize_task(table, results):
    completed = len([r for r in results if r])
    print(f"[{table}] completed={completed} failed={len(results) - completed}")


with DAG(
    dag_id="embed_supabase_tables_pipeline",
    default_args=DEFAULT_ARGS,
    description=(
        "Embed hotels/rooms/attractions text into their Supabase pgvector "
        "`embedding` column. Variable embed_supabase_only_null (default true) "
        "limits runs to NULL embeddings only."
    ),
    schedule="@daily",
    start_date=datetime(2026, 7, 30),
    catchup=False,
    max_active_runs=1,
    tags=["vsf", "embedding", "supabase"],
) as dag:
    for table_name in TABLE_COLUMNS:
        pending = fetch_pending_rows_task.override(task_id=f"fetch_pending_{table_name}")(table_name)
        embedded = embed_row_task.override(task_id=f"embed_{table_name}").expand(item=pending)
        summarize_task.override(task_id=f"summarize_{table_name}")(table_name, embedded)
