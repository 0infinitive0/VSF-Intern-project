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

`PIPELINE_MANAGED_FIELDS_HOTEL` below is a second, separate source of truth
for B3 (phase-09-hotel-edit.md): which `hotels` columns the ETL pipeline
overwrites on its next crawl of a `source_platform != 'manual'` row. Copied
from `_HOTEL_UPDATE_COLUMNS` in
`backend/src/airflow/dags/data_pipeline/hotel_pipeline.py` (that list itself
excludes only `source_platform`/`source_hotel_id`, the upsert key -- every
other column the pipeline writes is here). Not the same list as
`EMBEDDING_FIELDS`: this one drives the 🔒 "will be overwritten" warning,
not the "needs re-embed" one -- most columns are in both, but e.g.
`star_rating`/`images`/`check_in_time` are pipeline-managed without being
RAG-relevant.
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

PIPELINE_MANAGED_FIELDS_HOTEL: tuple[str, ...] = (
    "destination_id",
    "source_url",
    "name",
    "accommodation_type",
    "description",
    "star_rating",
    "address",
    "city",
    "area_name",
    "location_highlight",
    "coordinates",
    "amenities",
    "amenity_groups",
    "awards",
    "warnings",
    "review_score",
    "review_count",
    "category_scores",
    "check_in_time",
    "check_in_until",
    "check_out_time",
    "reception_open_until",
    "image_url",
    "images",
    "image_count",
    "nearby_attractions",
    "nearby_essentials",
    "lowest_price",
    "currency",
    "price_check_in_date",
    "price_check_out_date",
    "rooms_available",
    "scraped_at",
)
