"""Text-assertion pins on the guest-single-hotel-hold-guard migration and
database_schema.sql (plan 260818-vnpay-payment-and-email-confirmation's
addendum 2) — same style as test_room_availability_schema.py, no live DB
needed."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _migration_text() -> str:
    return (
        ROOT / "scripts" / "migrations" / "20260819_add_guest_single_hotel_hold_guard.sql"
    ).read_text(encoding="utf-8")


def _schema_text() -> str:
    return (ROOT / "scripts" / "database_schema.sql").read_text(encoding="utf-8")


def test_bookings_table_has_session_id_column_in_schema():
    schema = _schema_text()
    bookings_definition = schema.split("CREATE TABLE bookings (", 1)[1].split(");", 1)[0]

    assert "session_id VARCHAR(255)" in bookings_definition
    assert "REFERENCES sessions(session_id) ON DELETE SET NULL" in bookings_definition


def test_migration_adds_session_id_column():
    migration = _migration_text()

    assert "ALTER TABLE bookings" in migration
    assert "ADD COLUMN session_id VARCHAR(255)" in migration
    assert "REFERENCES sessions(session_id) ON DELETE SET NULL" in migration


def test_migration_drops_old_signature_before_replacing():
    """CREATE OR REPLACE FUNCTION cannot change a function's argument-type
    list — adding p_session_id would otherwise silently create a second,
    overloaded create_booking_reservation and leave the old 10-arg one
    live with none of the new guard logic (see the migration's own doc
    comment)."""
    migration = _migration_text()

    assert "DROP FUNCTION IF EXISTS public.create_booking_reservation(" in migration
    drop_clause = migration.split("DROP FUNCTION IF EXISTS public.create_booking_reservation(", 1)[1]
    drop_args = drop_clause.split(");", 1)[0]
    # The OLD (10-arg) signature, exactly as it existed before this migration.
    assert drop_args.strip().replace("\n", " ").split() == [
        "UUID,", "TEXT,", "DATE,", "TIME,", "DATE,", "TIME,",
        "INTEGER,", "NUMERIC,", "TEXT,", "INTEGER",
    ]


def test_migration_adds_guest_scoped_advisory_lock_and_cross_hotel_guard():
    migration = _migration_text()

    assert "pg_advisory_xact_lock(hashtextextended(p_room_id::text, 0))" in migration
    assert "pg_advisory_xact_lock(hashtextextended(v_guest_ref, 1))" in migration
    assert "guest_already_holding_elsewhere" in migration
    assert "br.hotel_id IS DISTINCT FROM v_hotel_id" in migration
    assert "b.status = 'RESERVED'" in migration
    assert "b.expires_at > now()" in migration


def test_migration_adds_session_id_param_and_writes_it_through():
    migration = _migration_text()

    assert "p_session_id TEXT DEFAULT NULL" in migration
    assert "nullif(btrim(p_session_id), '')" in migration


def test_migration_grants_new_signature_to_service_role_only():
    migration = _migration_text()

    assert "REVOKE ALL ON FUNCTION public.create_booking_reservation(" in migration
    assert "GRANT EXECUTE ON FUNCTION public.create_booking_reservation(" in migration
    assert "TO service_role;" in migration
