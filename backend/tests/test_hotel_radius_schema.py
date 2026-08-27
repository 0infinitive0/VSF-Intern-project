"""Guards that `match_hotels_with_rooms` actually USES its radius parameters.

The function accepted `root_latitude`/`root_longitude`/`max_radius_km` for a long
time while its body referenced none of them, so every radius search silently
returned hotels at any distance. `test_supabase_search.py` only proves the Python
side forwards the triple, which stayed green throughout — nothing checked the SQL
that consumes it. These tests close that gap: the parameters have to appear in
both scoring CTEs, not merely in the signature.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
_SCHEMA = ROOT / "scripts" / "database_schema.sql"
_MIGRATION = (
    ROOT / "scripts" / "migrations"
    / "20260827_add_radius_filter_to_match_hotels_with_rooms.sql"
)


def _match_hotels_body(sql: str) -> str:
    """The body of the last `match_hotels_with_rooms` definition in `sql`, with the
    parameter list stripped so a mention in the signature cannot satisfy a test."""
    # The name also appears in the trailing ALTER/GRANT statements, which carry no
    # body -- take the one chunk that does.
    bodies = [
        chunk.split("LANGUAGE sql", 1)[1].split("$$;", 1)[0]
        for chunk in sql.split("FUNCTION public.match_hotels_with_rooms(")[1:]
        if "LANGUAGE sql" in chunk
    ]
    assert len(bodies) == 1, f"expected exactly one definition, found {len(bodies)}"
    return bodies[0]


def test_schema_radius_filter_runs_in_both_scoring_ctes():
    body = _match_hotels_body(_SCHEMA.read_text(encoding="utf-8"))

    # One occurrence per CTE: hotel_scores and room_scores. Filtering only in the
    # final WHERE would still be correct but would forfeit both the index and the
    # pruning of the availability subqueries.
    assert body.count("extensions.earth_box(") == 2
    assert body.count("extensions.earth_distance(") == 2
    assert body.count("public.coordinates_to_earth(h.coordinates)") == 4
    assert body.count("max_radius_km * 1000.0") == 4

    # earth_box alone admits rows in the bounding cube's corners; the exact
    # great-circle check is what makes the radius a radius.
    assert "OPERATOR(extensions.<@)" in body


def test_schema_radius_filter_is_inert_when_unrequested():
    body = _match_hotels_body(_SCHEMA.read_text(encoding="utf-8"))

    # Every existing caller passes no radius at all; those searches must behave
    # exactly as before rather than losing hotels that have no coordinates.
    assert (
        body.count(
            "root_latitude IS NULL OR root_longitude IS NULL OR max_radius_km IS NULL"
        )
        == 2
    )


def test_coordinates_to_earth_is_indexable_and_total():
    schema = _SCHEMA.read_text(encoding="utf-8")

    # IMMUTABLE is what makes the expression index legal; the regex guard is what
    # keeps a malformed row from breaking the index build or a live search.
    assert "CREATE FUNCTION public.coordinates_to_earth(coordinates TEXT)" in schema
    assert "IMMUTABLE" in schema
    assert r"'^\s*-?\d+(\.\d+)?\s*,\s*-?\d+(\.\d+)?\s*$'" in schema
    assert (
        "USING gist (public.coordinates_to_earth(coordinates))" in schema
    )
    assert "CREATE EXTENSION IF NOT EXISTS earthdistance WITH SCHEMA extensions;" in schema


def test_migration_matches_schema_definition():
    migration = _MIGRATION.read_text(encoding="utf-8")

    assert _match_hotels_body(migration).count("extensions.earth_box(") == 2
    assert "CREATE INDEX IF NOT EXISTS idx_hotels_coordinates_earth" in migration
    # CREATE OR REPLACE with the identical 13-parameter list replaces the live
    # function in place; a changed list would silently create a second overload.
    assert "CREATE OR REPLACE FUNCTION public.match_hotels_with_rooms(" in migration
    assert migration.count("filter_min_guests INTEGER DEFAULT NULL::integer") == 1
