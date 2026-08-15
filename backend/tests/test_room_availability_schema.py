from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_available_room_count_belongs_to_rooms_not_room_prices():
    schema = (ROOT / "scripts" / "database_schema.sql").read_text(encoding="utf-8")

    rooms_definition = schema.split("CREATE TABLE rooms (", 1)[1].split(");", 1)[0]
    room_prices_definition = schema.split("CREATE TABLE room_prices (", 1)[1].split(");", 1)[0]

    assert "available_room_count INTEGER" in rooms_definition
    assert "available_room_count" not in room_prices_definition


def test_availability_migration_moves_legacy_count_to_rooms():
    migration = (
        ROOT / "scripts" / "migrations" / "20260814_move_available_room_count_to_rooms.sql"
    ).read_text(encoding="utf-8")

    assert "ADD COLUMN IF NOT EXISTS available_room_count INTEGER" in migration
    assert "UPDATE rooms" in migration
    assert "DROP COLUMN available_room_count" in migration


def test_booking_schema_has_only_one_booking_table():
    schema = (ROOT / "scripts" / "database_schema.sql").read_text(encoding="utf-8")

    assert "CREATE TABLE bookings" in schema
    assert "CREATE TABLE room_inventory" not in schema
    assert "CREATE TABLE booking_room_nights" not in schema


def test_room_availability_counts_confirmed_and_active_reserved_bookings():
    schema = (ROOT / "scripts" / "database_schema.sql").read_text(encoding="utf-8")

    assert "CREATE FUNCTION public.get_room_availability" in schema
    assert "b.status = 'CONFIRMED'" in schema
    assert "b.status = 'RESERVED' AND b.expires_at > now()" in schema
    assert "b.check_in_date <= night.stay_date" in schema
    assert "b.check_out_date > night.stay_date" in schema
    assert "TO service_role;" in schema


def test_hotel_match_excludes_room_types_with_no_booking_availability():
    schema = (ROOT / "scripts" / "database_schema.sql").read_text(encoding="utf-8")

    assert schema.count("public.get_room_availability(") >= 3


def test_fast_hotel_match_uses_bounded_nearest_neighbor_candidates():
    migration = (
        ROOT / "scripts" / "migrations" / "20260814_create_fast_hotel_match.sql"
    ).read_text(encoding="utf-8")

    assert "CREATE FUNCTION public.match_hotels_with_rooms_fast" in migration
    assert "ORDER BY h.embedding <=> query_embedding" in migration
    assert "ORDER BY r.embedding <=> query_embedding" in migration
    assert "LIMIT least(greatest(match_count * 20, 100), 500)" in migration


def test_bookings_keep_optional_local_times_and_a_temporary_user_reference():
    schema = (ROOT / "scripts" / "database_schema.sql").read_text(encoding="utf-8")

    assert "temporary_user_ref TEXT" in schema
    assert "check_in_time TIME" in schema
    assert "check_out_time TIME" in schema
    assert "expires_at TIMESTAMPTZ" in schema
    assert "'PENDING', 'RESERVED', 'CONFIRMED', 'CANCELLED', 'EXPIRED'" in schema
    assert "ALTER TABLE bookings ENABLE ROW LEVEL SECURITY" in schema
