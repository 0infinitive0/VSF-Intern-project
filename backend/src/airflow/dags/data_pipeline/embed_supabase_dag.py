"""Embed hotels/rooms/attractions text straight into their Supabase pgvector
`embedding` column.

Embedding provider is read from EMBEDDING_PROVIDER/EMBEDDING_MODEL/
EMBEDDING_API_BASE/EMBEDDING_API_KEY, defaulting to Cloudflare Workers AI
`@cf/baai/bge-m3`, with local Ollama as the fallback path. The model must stay
bge-m3: every vector already stored was produced by it, and pgvector compares
them all in one space.

Airflow Variables:
- `embed_supabase_only_null` (default "true") limits each run to rows where
  `embedding IS NULL`, so scheduled runs only backfill new data. Set "false" to
  force a full re-embed of every row in every table. Deliberately NOT widened
  to include `embedding_stale` rows: a stale row is still searchable (with
  pre-edit text), so re-embedding it is a paid call the admin should be the
  one to ask for, via the "Chạy embedding" trigger conf below. The scheduled
  sweep stays cheap and only closes real coverage gaps.
- `embed_supabase_force_tables` (default "") — comma-separated table names that
  ignore the switch above and always re-embed in full, e.g. "hotels". Use this
  after changing one table's embedding text, so the other tables aren't
  re-embedded needlessly.
- `embed_supabase_batch_limit` (default "1000") caps how many pending rows per
  table a single run maps over, so a large backlog doesn't spawn an unbounded
  number of task instances in one run — reruns drain the rest incrementally.
  Set "0" for no cap, to finish a table in a single trigger. Note Supabase REST
  returns at most 1000 rows per request, so the fetch below pages through.
- `embed_supabase_chunk_size` (default "25") — rows handled per mapped task. Each
  task embeds its rows in ONE batched API call, so this is both the unit of
  parallelism and the batch size. Keep it high enough that
  ceil(rows / chunk_size) stays under Airflow's `max_map_length` (default 1024);
  too high and the embedding endpoint rejects the request for size (handled by
  splitting, at the cost of a wasted round trip).

Trigger conf (admin "Chạy embedding" button, `POST /hotels/reembed` ->
`src/api/admin/embedding.py`): `{"hotel_ids": [...], "include_rooms": bool}`.
When `hotel_ids` is present the run is scoped to exactly those hotels (and
their rooms, only if `include_rooms`) instead of the Variables above --
`attractions` is skipped entirely (that table isn't hotel-edit scoped) and the
`only_null`/`force_tables`/`batch_limit` Variables are bypassed, since an
admin who explicitly asked to re-embed these specific rows wants them redone
now, not gated by a global scheduler switch. This is the only path that picks
up `embedding_stale` rows, and every successful write clears that flag (see
`STALE_FLAG_TABLES`). The unscheduled trigger from the
Pipelines page still sends `conf: {}`, which falls through to the normal
Variable-driven full/incremental behavior unchanged.
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
    "hotels": "id,name,accommodation_type,area_name,address,location_highlight,description,amenities",
    "rooms": "id,name,bed_description,view,room_facilities",
    "attractions": "id,name,description,category",
}

# Tables whose rows an admin can edit, and which therefore carry the
# `embedding_stale` flag this DAG clears when it writes a fresh vector
# (backend/scripts/migrations/20260827_add_embedding_stale.sql).
# `attractions` is ETL-only and has no such column.
STALE_FLAG_TABLES = {"hotels", "rooms"}


def _joined(value):
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value or "")


def _build_text(table, row):
    if table == "hotels":
        # `address` (100% coverage) and `location_highlight` (38.6%, values like
        # "Cách bãi biển 350 mét" / "trong nội thành") carry the location signal that
        # answers "gần biển"/"gần trung tâm" queries — neither was embedded before.
        # Empty fields are dropped rather than emitted as a bare "Mô tả:" label:
        # description is only 45% populated, so blank labels were pure noise.
        # NOTE: only the hotels branch may change shape. The rooms/attractions text
        # below must stay byte-identical — their stored vectors were produced from it,
        # and a reworded template would leave two incompatible clusters in one column.
        fields = (
            ("Tên", row.get("name")),
            ("Loại hình", row.get("accommodation_type")),
            ("Khu vực", row.get("area_name")),
            ("Địa chỉ", row.get("address")),
            ("Vị trí nổi bật", row.get("location_highlight")),
            ("Mô tả", row.get("description")),
            ("Tiện ích", _joined(row.get("amenities"))),
        )
        return "\n".join(
            f"{label}: {value}" for label, value in fields if str(value or "").strip()
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


def _post_embeddings_splitting(texts, url, headers, model):
    """POST one batch, halving it and recursing if the endpoint rejects it.

    Cloudflare's limit is on total request SIZE, not item count: 100 short strings
    are fine, but 50 hotel descriptions (~192KB) return HTTP 400 while 25 (~108KB)
    succeed. Any fixed chunk size is therefore wrong as soon as the text gets
    longer, so the batch adapts itself instead. A single text that still fails is a
    real error and propagates to the caller.
    """
    body = json.dumps({"model": model, "input": texts}).encode("utf-8")
    request = Request(url, data=body, headers=headers)
    try:
        # Timeout scales with batch size: ~3s per 25 hotel-sized items, plus headroom.
        with urlopen(request, timeout=60 + 2 * len(texts)) as response:
            payload = json.load(response)
        items = sorted(payload["data"], key=lambda item: item.get("index", 0))
        if len(items) != len(texts):
            raise ValueError(f"embedding count {len(items)} != input count {len(texts)}")
        return [item["embedding"] for item in items]
    except (HTTPError, URLError, KeyError, ValueError, TimeoutError, json.JSONDecodeError):
        if len(texts) == 1:
            raise
        middle = len(texts) // 2
        print(f"batch of {len(texts)} rejected; splitting into {middle} + {len(texts) - middle}")
        return (
            _post_embeddings_splitting(texts[:middle], url, headers, model)
            + _post_embeddings_splitting(texts[middle:], url, headers, model)
        )


def _embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch in one request. The OpenAI-compatible endpoint accepts a list
    for `input` and returns one object per item carrying its own `index`; results
    are reordered by that index rather than trusting response order. Ollama's
    /api/embeddings has no batch form, so that path loops."""
    provider = (
        os.environ.get("EMBEDDING_PROVIDER")
        or Variable.get("EMBEDDING_PROVIDER", default_var="openai")
    ).strip().casefold()

    model = (
        os.environ.get("EMBEDDING_MODEL")
        or Variable.get("EMBEDDING_MODEL", default_var="@cf/baai/bge-m3")
    ).strip()

    api_base = (
        os.environ.get("EMBEDDING_API_BASE")
        or Variable.get("EMBEDDING_API_BASE", default_var="")
    ).strip().rstrip("/")

    api_key = (
        os.environ.get("EMBEDDING_API_KEY")
        or os.environ.get("CLOUDFLARE_API_TOKEN")
        or Variable.get("EMBEDDING_API_KEY", default_var="")
    ).strip()

    # Cloudflare Workers AI / OpenAI-compatible API
    if provider in {"openai", "cloudflare", "cloudflare_workers", "cloudflare_ai"} or api_base:
        if not api_base:
            cf_account = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
            if cf_account:
                api_base = f"https://api.cloudflare.com/client/v4/accounts/{cf_account}/ai/v1"
            else:
                api_base = "https://api.cloudflare.com/client/v4/accounts/e8045479a2ef8992d1258b748ac5f4c0/ai/v1"

        url = f"{api_base}/embeddings"
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        return _post_embeddings_splitting(texts, url, headers, model)

    # Local Ollama fallback — no batch endpoint, so one request per text.
    ollama_base_url = os.environ.get("OLLAMA_BASE_URL", "http://host.docker.internal:11434").rstrip("/")
    url = f"{ollama_base_url}/api/embeddings"
    vectors = []
    for text in texts:
        body = json.dumps({"model": model, "prompt": text}).encode("utf-8")
        request = Request(url, data=body, headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=60) as response:
            payload = json.load(response)
        vectors.append(payload["embedding"])
    return vectors


@task
def fetch_pending_rows_task(table, dag_run=None):
    import requests

    # `dag_run` is Airflow-context-injected (TaskFlow auto-fills any param
    # named after a known context key) -- `None` covers unit-style calls with
    # no real DagRun, same as every `default_var=` fallback below.
    conf = (dag_run.conf if dag_run is not None else None) or {}
    hotel_ids = [str(v) for v in conf.get("hotel_ids") or []]
    include_rooms = bool(conf.get("include_rooms"))

    if hotel_ids and table == "attractions":
        print(f"[{table}] skipped -- hotel-scoped run (conf.hotel_ids) never touches attractions")
        return []
    if hotel_ids and table == "rooms" and not include_rooms:
        print(f"[{table}] skipped -- hotel-scoped run without include_rooms")
        return []

    supabase_url, supabase_key = _require_supabase_creds()
    headers = _supabase_headers(supabase_key)
    columns = TABLE_COLUMNS[table]

    if hotel_ids:
        # Explicit re-embed of specific hotels -- bypass `only_null`/
        # `force_tables`/`batch_limit` entirely. An admin who just cleared
        # exactly these rows' `embedding` and asked to run now wants exactly
        # these rows redone, not gated by a Variable meant for the global
        # scheduled sweep.
        only_null = False
        id_column = "id" if table == "hotels" else "hotel_id"
        id_filter = f"&{id_column}=in.({','.join(hotel_ids)})"
        batch_limit = 0  # unlimited -- bounded by hotel_ids count already, never a real backlog
        unlimited = True
    else:
        only_null = Variable.get("embed_supabase_only_null", default_var="true").strip().lower() != "false"
        # Per-table force list. Changing one table's embedding text invalidates only that
        # table's stored vectors, so it needs a full re-embed while the others stay on
        # cheap NULL-only backfill — the global switch above can't express that.
        force_tables = {
            name.strip().casefold()
            for name in Variable.get("embed_supabase_force_tables", default_var="").split(",")
            if name.strip()
        }
        if table.casefold() in force_tables:
            only_null = False
        id_filter = ""
        # 0 (or any non-positive value) means "no cap — take every pending row in one
        # run", for when you want a table fully done in a single trigger instead of
        # draining it across several scheduled runs.
        batch_limit = int(Variable.get("embed_supabase_batch_limit", default_var="1000"))
        unlimited = batch_limit <= 0

    # Supabase REST caps ANY single response at 1000 rows and silently truncates
    # past it — a bare `limit=1200` comes back with 1000 and no error. Page through
    # instead, or batch_limit above 1000 is a lie. `order=id` keeps offset paging
    # stable; without an explicit order PostgREST may repeat or skip rows.
    rows = []
    while unlimited or len(rows) < batch_limit:
        want = 1000 if unlimited else min(1000, batch_limit - len(rows))
        url = (
            f"{supabase_url}/rest/v1/{table}?select={columns}"
            f"&order=id&limit={want}&offset={len(rows)}"
        )
        if only_null:
            url += "&embedding=is.null"
        url += id_filter

        response = requests.get(url, headers=headers)
        response.raise_for_status()
        page = response.json()
        rows.extend(page)
        if len(page) < want:
            break

    # Map over CHUNKS, not individual rows. One mapped task per row hits Airflow's
    # `max_map_length` (default 1024) once a table exceeds it — the whole fetch then
    # fails with "unmappable_return_value_length" and nothing is embedded. Chunking
    # also lets each task embed its rows in a single batched API call.
    # 25 is what hotel-sized rows fit into one request (~108KB); larger batches get
    # rejected and _post_embeddings_splitting has to bisect, which wastes a round trip.
    chunk_size = max(1, int(Variable.get("embed_supabase_chunk_size", default_var="25")))
    chunks = [
        {"table": table, "rows": rows[start:start + chunk_size]}
        for start in range(0, len(rows), chunk_size)
    ]
    print(
        f"[{table}] fetched {len(rows)} pending rows -> {len(chunks)} chunks of {chunk_size} "
        f"(only_null={only_null}, batch_limit={batch_limit})"
    )
    return chunks


_EMBED_ERRORS = (URLError, HTTPError, KeyError, ValueError, TimeoutError, json.JSONDecodeError)


@task(max_active_tis_per_dag=4)
def embed_chunk_task(item):
    import requests

    table = item["table"]
    rows = item["rows"]

    supabase_url, supabase_key = _require_supabase_creds()
    texts = [_build_text(table, row) for row in rows]

    try:
        vectors = _embed_texts(texts)
    except _EMBED_ERRORS as exc:
        # One bad row must not cost the whole chunk — retry the batch item by item
        # so the rest still land. Failures become None and are counted below.
        print(f"[{table}] batch of {len(texts)} failed ({exc}); retrying individually")
        vectors = []
        for row, text in zip(rows, texts):
            try:
                vectors.append(_embed_texts([text])[0])
            except _EMBED_ERRORS as row_exc:
                print(f"[{table}/{row.get('id')}] embedding failed: {row_exc}")
                vectors.append(None)

    headers = _supabase_headers(supabase_key)
    headers["Prefer"] = "return=minimal"

    embedded = 0
    for row, vector in zip(rows, vectors):
        row_id = row.get("id")
        if vector is None:
            continue
        if len(vector) != EMBEDDING_DIMENSION:
            print(f"[{table}/{row_id}] unexpected embedding dimension {len(vector)} != {EMBEDDING_DIMENSION}")
            continue
        payload: dict = {"embedding": vector}
        if table in STALE_FLAG_TABLES:
            # The vector now matches the row's current text, so the admin's
            # "Cần chạy lại" flag is satisfied. Written in the same PATCH as
            # the vector so the two can never disagree
            # (scripts/migrations/20260827_add_embedding_stale.sql).
            payload["embedding_stale"] = False
        patch_response = requests.patch(
            f"{supabase_url}/rest/v1/{table}?id=eq.{row_id}",
            headers=headers,
            json=payload,
        )
        patch_response.raise_for_status()
        embedded += 1

    print(f"[{table}] chunk done: {embedded}/{len(rows)} embedded")
    return {"embedded": embedded, "total": len(rows)}


@task
def summarize_task(table, results):
    completed = sum(r["embedded"] for r in results if r)
    total = sum(r["total"] for r in results if r)
    print(f"[{table}] completed={completed} failed={total - completed} (over {len(results)} chunks)")
    if total > 0 and completed == 0:
        # `embed_chunk_task` swallows per-row embedding failures (a bad row
        # must not cost the whole chunk) and always returns normally, so a
        # systemic failure -- bad/missing embedding provider credentials,
        # the provider unreachable, wrong dimension -- would otherwise mark
        # this DAG run `success` with 0 rows actually embedded. The admin's
        # "Chạy embedding" banner (and the hotel's embedding dot) trusts the
        # DAG run's own state, so a run that embedded nothing must fail it
        # instead of lying.
        raise RuntimeError(f"[{table}] embedding failed for all {total} pending row(s) -- check embedding provider config")


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
        embedded = embed_chunk_task.override(task_id=f"embed_{table_name}").expand(item=pending)
        summarize_task.override(task_id=f"summarize_{table_name}")(table_name, embedded)
