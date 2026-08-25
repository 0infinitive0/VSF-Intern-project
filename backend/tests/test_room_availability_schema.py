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


def test_match_hotels_with_rooms_checks_sold_out_on_the_freshest_row_per_night():
    """Regression for phase-11's code review finding
    (20260824_fix_sold_out_freshest_row_precedence.sql): the live schema
    must no longer filter `sold_out` per row before counting distinct
    priced nights -- that let a stale, still-`sold_out=false` OTA row keep a
    night "open" even after a fresher row (an admin close, or a genuine OTA
    recrawl) marked it sold out. `count_priced_open_nights` picks the
    freshest row per night first, then checks sold_out on that one row."""
    schema = (ROOT / "scripts" / "database_schema.sql").read_text(encoding="utf-8")

    assert "CREATE OR REPLACE FUNCTION public.count_priced_open_nights" in schema
    assert "ORDER BY rp.check_in_date, rp.crawled_at DESC" in schema
    assert schema.count("public.count_priced_open_nights(") >= 3  # definition + both CTEs
    assert "count(DISTINCT rp.check_in_date)" not in schema
