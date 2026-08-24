"""Single source of truth for which `hotels` columns feed the embedding text.

Copied from `TABLE_COLUMNS["hotels"]` in
`backend/src/airflow/dags/data_pipeline/embed_supabase_dag.py` (minus `id`,
which is a key, not text). Whenever an admin write touches one of these
columns, the row's `embedding` must be set back to NULL and the DAG re-run
before the bot can find it again -- every other column (`star_rating`,
`images`, `check_in_time`, `coordinates`, `city`, ...) has no effect on
search and needs no re-embed.

This list is not admin-editable and the frontend never decides membership in
it -- both would drift from the DAG the moment it changes. If the DAG's
column list changes, update it here to match, in the same commit.
"""

from __future__ import annotations

EMBEDDING_FIELDS: tuple[str, ...] = (
    "name",
    "accommodation_type",
    "area_name",
    "address",
    "location_highlight",
    "description",
    "amenities",
)
