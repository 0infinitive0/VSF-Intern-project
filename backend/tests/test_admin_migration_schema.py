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
    schema = _schema_text()

    function_body = schema.split(
        "CREATE FUNCTION public.match_hotels_with_rooms(", 1
    )[1].split("$$;", 1)[0]

    # Bug fix: a night with more than one room_prices row (e.g. an admin price
    # and a stale OTA crawl) must not overshoot the requested night count.
    assert function_body.count("count(DISTINCT rp.check_in_date)") == 2
    assert "count(*)" not in function_body.split("hotel_capacity AS (", 1)[0]


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
