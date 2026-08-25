# Airflow 3.3.0 `/api/v2` — real response fixtures (Phase 13)

Captured 2026-08-25 against a locally-run `backend/src/airflow/docker-compose.yaml`
stack (FabAuthManager, default `airflow`/`airflow` admin), per phase-13's mandatory
"call real endpoints before writing the client" step. All requests actually hit
a live Airflow instance — nothing here is guessed from Airflow 2 docs.

## Files

| File | Endpoint | Notes |
|---|---|---|
| `auth_token_shape.json` | `POST /auth/token` | Body `{username,password}` → `{"access_token": "<jwt>"}`. Token `exp-iat` = 86400s (24h). |
| `version.json` | `GET /api/v2/version` | `{"version","git_version"}`. Used for `health()` instead of `/monitor/health` — a successful call already proves connectivity, and this gives the version string in the same request. |
| `health.json` | `GET /api/v2/monitor/health` | Component-level (`metadatabase`/`scheduler`/`triggerer`/`dag_processor`, each `{status}`). Kept as a fixture but not used by the client — see `version.json` note. |
| `dag_detail.json` | `GET /api/v2/dags/{dag_id}` | Large object; `is_paused` is the field this phase cares about. |
| `dagRuns_list.json` | `GET /api/v2/dags/{dag_id}/dagRuns?limit=&order_by=-start_date` | **Not a bare array** — `{"dag_runs":[...],"total_entries","next_cursor","previous_cursor"}`. |
| `trigger_response.json` | `POST /api/v2/dags/{dag_id}/dagRuns` (first attempt) | 422 — `logical_date` is **required**, not optional as the plan assumed. |
| `trigger_response_2.json` | same, retried with `logical_date` | 200, full `DAGRun` object, `dag_run_id` = `manual__<ISO8601>`. |
| `taskInstances.json` / `taskInstances_success.json` | `GET .../dagRuns/{id}/taskInstances` | `{"task_instances":[...]}`, each with `map_index` (`-1` = not mapped). |
| `task_log_fetch_pending_hotels.json` | log fetch against a run whose worker container no longer exists | Shows the "served logs unreachable" failure shape — useful for the *Airflow-side* error case, not a real task log. |
| `task_log_real_failure.json` | log fetch, real task that raised `ValueError` | `{"content":[{...,"error_detail":[{"exc_type","exc_value","frames":[...]}]}], "continuation_token"}`. **Log content is a list of structured JSON events, not a plain string.** |
| `task_log_success.json` | log fetch, real successful task | Same structured-event shape; plain `event` strings, no `error_detail`. |
| `dag_patch_response.json` | `PATCH /api/v2/dags/{dag_id}` `{"is_paused": true}` | Full `DAGDetail` object, same shape as a GET. Confirms `DAGPatchBody` (`{is_paused}`, `additionalProperties: false`) against a real call, not just the saved OpenAPI spec. Captured with `is_paused: true` to leave the DAG re-paused after testing -- the dev stack's `embed_supabase_tables_pipeline` should stay paused between sessions like a fresh init would leave it. |
| `openapi_v2_full.json` | `GET /openapi.json` | The full Airflow 3.3.0 OpenAPI spec -- used to confirm `map_index` is `in: query` (not a path segment) and that `TriggerDAGRunPostBody.logical_date`/`DAGPatchBody.is_paused` are both `required`, without guessing from partial curl output. |

## Findings that changed the plan's assumed client shape

1. **`get_task_log` returns structured events, not `str`.** Every `content[]` item is
   `{event, timestamp?, level?, logger?, ..., error_detail?}`. The client flattens
   `event` strings (plus a formatted line for `error_detail` when present) into a
   single string for the phase-13 signature (`-> str`) to hold, but the raw JSON is
   worth keeping if Phase 16 wants structured rendering later.
2. **`POST .../dagRuns` requires `logical_date`.** The client always supplies
   `datetime.now(UTC)` when the caller doesn't pass one.
3. **A manually-triggered run on a *paused* DAG stays `queued` forever** — the
   scheduler never dispatches it. Every DAG here is paused by default
   (`AIRFLOW__CORE__DAGS_ARE_PAUSED_AT_CREATION: true`). `trigger_dag_run` unpauses
   the target DAG (`PATCH /api/v2/dags/{dag_id}` `{"is_paused": false}`) before
   triggering, so a portal admin (who has no direct Airflow access, decision #4)
   never hits this silently.
4. **`dagRuns` list responses are envelopes, not arrays** (`total_entries` etc.) —
   same pattern Airflow 3 uses everywhere else in `/api/v2`.
5. Could not capture a real **mapped-task** (`map_index >= 0`) example: the live
   dataset had zero rows with `embedding IS NULL` in `hotels`/`rooms`/`attractions`
   at capture time, so `embed_hotels`/`embed_rooms`/`embed_attractions` (the
   `.expand()`-mapped tasks) were `skipped` with no expansion in both runs
   triggered here. Confirmed from Airflow's own `openapi_v2_full.json` (saved
   here) that `map_index` on the log-fetch endpoint is a **query parameter**
   (default `-1`), not a path segment as an Airflow-2-era guess might assume —
   `GET .../taskInstances/{task_id}/logs/{try_number}?map_index=N`. The mapping
   itself (which `map_index` values exist for a given mapped task) is **not
   verified against a real mapped run**. Flagged as a residual risk for Phase 16
   (run-detail/log screen) to confirm on its own first real backlog run.
6. `POST .../dagRuns`'s own schema (`TriggerDAGRunPostBody` in the saved OpenAPI
   spec) marks `logical_date` `required` even though its type is nullable --
   the client always supplies an explicit `datetime.now(UTC)` rather than
   relying on `null` being accepted, since that combination wasn't tested live.

## Post-review fixes (not shape findings, but changed the client after a
   code-review pass caught them against this same real environment)

7. `_TokenCache.get()` originally held its lock across the blocking
   `httpx.post` call to `/auth/token`. Sync `def` routes share one anyio
   threadpool -- a slow/dead Airflow would have serialized every concurrent
   admin request behind that one lock, not just Airflow-related ones.
   Re-verified live after the fix: 5 concurrent `health()` calls against a
   1.0s-per-fetch mock complete in ~1.0s wall time (was ~5.0s before). The
   lock now only ever guards the in-memory cache read/write; the network
   call happens outside it.
8. `trigger_dag_run` originally PATCHed `is_paused: false` unconditionally on
   every call. Changed to `get_dag` first and PATCH only when actually
   paused -- avoids depending on DAG-edit permission for the common case
   (every trigger after the first, when the DAG is already unpaused) and
   avoids silently converting a `@daily`-scheduled DAG permanently live on
   its very first manual trigger without that being visible anywhere. The
   underlying trade-off (once unpaused, this client has no way to re-pause
   it, since portal admins have no Airflow access) is unchanged and belongs
   on Phase 15's confirm dialog as a disclosure, not solved here.
