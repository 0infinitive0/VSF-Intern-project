from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _schema_text() -> str:
    return (ROOT / "scripts" / "database_schema.sql").read_text(encoding="utf-8")


def test_hotels_is_active_soft_delete_column_and_index():
    schema = _schema_text()

    hotels_definition = schema.split("CREATE TABLE hotels (", 1)[1].split(");", 1)[0]

    assert "is_active BOOLEAN NOT NULL DEFAULT true" in hotels_definition
    assert (
        "CREATE INDEX hotels_is_active_idx ON hotels (is_active) WHERE is_active = false"
        in schema
    )


def test_match_hotels_with_rooms_counts_distinct_nights_not_rows():
    """Bug fix (F4): a night with more than one room_prices row (e.g. an
    admin price and a stale OTA crawl) must not overshoot the requested
    night count. Superseded by count_priced_open_nights()
    (20260824_fix_sold_out_freshest_row_precedence.sql), which counts
    distinct nights via `DISTINCT ON (rp.check_in_date)` instead of
    `count(DISTINCT rp.check_in_date)` -- same invariant (one count per
    night, not per row), different SQL shape because that function also had
    to start picking the freshest row per night before checking sold_out
    (see test_match_hotels_with_rooms_checks_sold_out_on_the_freshest_row_per_night
    in test_room_availability_schema.py)."""
    schema = _schema_text()

    function_body = schema.split(
        "CREATE FUNCTION public.match_hotels_with_rooms(", 1
    )[1].split("$$;", 1)[0]
    helper_body = schema.split(
        "CREATE OR REPLACE FUNCTION public.count_priced_open_nights(", 1
    )[1].split("$$;", 1)[0]

    assert function_body.count("public.count_priced_open_nights(") == 2
    assert "count(*)" not in function_body.split("hotel_capacity AS (", 1)[0]
    assert "DISTINCT ON (rp.check_in_date)" in helper_body


def test_match_hotels_with_rooms_excludes_deactivated_hotels():
    schema = _schema_text()

    function_body = schema.split(
        "CREATE FUNCTION public.match_hotels_with_rooms(", 1
    )[1].split("$$;", 1)[0]

    assert function_body.count("AND h.is_active") == 2


def test_manual_source_id_sequences_have_no_column_default():
    schema = _schema_text()

    hotels_definition = schema.split("CREATE TABLE hotels (", 1)[1].split(");", 1)[0]
    rooms_definition = schema.split("CREATE TABLE rooms (", 1)[1].split(");", 1)[0]

    assert "CREATE SEQUENCE manual_hotel_source_id_seq" in schema
    assert "CREATE SEQUENCE manual_room_source_id_seq" in schema
    # ETL must keep writing the OTA's original id untouched.
    assert "nextval" not in hotels_definition
    assert "nextval" not in rooms_definition


def test_manual_room_source_id_seq_starts_above_plausible_ota_ids():
    schema = _schema_text()

    # rooms has no source_platform discriminator in its unique key, so a
    # manual room id colliding with a future OTA room_id would be silently
    # overwritten on re-crawl (ON CONFLICT ... DO UPDATE). Starting the
    # sequence at a high offset keeps that from happening in practice.
    assert "CREATE SEQUENCE manual_room_source_id_seq START 9000000000" in schema


def test_admin_audit_log_is_append_only_and_service_role_only():
    schema = _schema_text()

    assert "CREATE TABLE admin_audit_log" in schema
    assert "ALTER TABLE admin_audit_log ENABLE ROW LEVEL SECURITY" in schema
    assert "REVOKE ALL ON TABLE admin_audit_log FROM anon, authenticated, PUBLIC" in schema
    assert "GRANT SELECT, INSERT ON TABLE admin_audit_log TO service_role" in schema
    # No UPDATE/DELETE grant anywhere for this table -- audit rows are append-only.
    assert "UPDATE" not in schema.split("CREATE TABLE admin_audit_log", 1)[1].split(
        "CREATE SEQUENCE manual_hotel_source_id_seq", 1
    )[0]


def test_admin_hotel_rows_view_is_one_row_per_hotel_and_locked_down():
    schema = _schema_text()

    view_definition = schema.split("CREATE OR REPLACE VIEW public.admin_hotel_rows AS", 1)[1].split(
        "GRANT  SELECT ON public.admin_hotel_rows TO service_role;", 1
    )[0]

    # LEFT JOIN + GROUP BY h.id -- one row per hotel regardless of room
    # count (0 or many), matching Phase 7's Success Criteria: count(*) FROM
    # admin_hotel_rows == count(*) FROM hotels.
    assert "FROM public.hotels h" in view_definition
    assert "LEFT JOIN public.rooms r ON r.hotel_id = h.id" in view_definition
    assert "GROUP BY h.id" in view_definition
    assert "(h.source_platform = 'manual')" in view_definition
    assert "(h.embedding IS NOT NULL)" in view_definition
    assert "count(r.id) FILTER (WHERE r.embedding IS NULL)" in view_definition
    assert "REVOKE ALL ON public.admin_hotel_rows FROM anon, authenticated, PUBLIC;" in schema
    assert "GRANT  SELECT ON public.admin_hotel_rows TO service_role;" in schema
