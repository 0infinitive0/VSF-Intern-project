-- Backport of the room-hold RPCs that already run live on Supabase but had
-- never been captured in a committed migration (found via direct inspection
-- with the Supabase MCP `execute_sql`/`pg_get_functiondef` — see
-- 260818-booking-backend-robustness plan). These three functions are the
-- most concurrency-critical code in the system: create_booking_reservation
-- is what makes "two guests hold the last room at the same second" resolve
-- correctly instead of double-booking. Bodies below are the exact live
-- definitions, only reformatted for readability (matching
-- get_room_availability's style just above this table in
-- database_schema.sql) — no logic changed. Safe to (re)apply to the live
-- project: CREATE OR REPLACE keeps today's signatures, so this replaces the
-- functions in place rather than creating new overloads.
--
-- create_booking_reservation — holds `p_room_count` units of one room type
-- for `p_hold_minutes` (default 15). Concurrency safety comes from
-- `pg_advisory_xact_lock(hashtextextended(p_room_id::text, 0))`, taken
-- BEFORE availability is computed: two requests for the same room_id are
-- serialized by Postgres itself (the second blocks until the first commits
-- or rolls back), so the loser always recomputes availability against the
-- winner's just-inserted row and gets a clean 'insufficient_room_availability'
-- instead of racing it. Availability itself is computed the same way
-- get_room_availability does (min remaining across every night of the stay,
-- counting CONFIRMED + not-yet-expired RESERVED bookings) — an expired hold
-- stops counting the instant its expires_at passes, with no cron/background
-- sweep required for correctness.
CREATE OR REPLACE FUNCTION public.create_booking_reservation(
    p_room_id UUID,
    p_temporary_user_ref TEXT,
    p_check_in_date DATE,
    p_check_in_time TIME,
    p_check_out_date DATE,
    p_check_out_time TIME,
    p_room_count INTEGER,
    p_total_amount NUMERIC,
    p_currency TEXT,
    p_hold_minutes INTEGER DEFAULT 15
)
RETURNS bookings
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_booking public.bookings;
    v_available INTEGER;
BEGIN
    IF p_check_out_date <= p_check_in_date
       OR p_room_count <= 0
       OR p_hold_minutes NOT BETWEEN 1 AND 60 THEN
        RAISE EXCEPTION 'invalid_booking_request';
    END IF;

    -- Serializes every concurrent hold attempt for THIS room: the second
    -- caller waits here until the first transaction commits/rolls back, so
    -- the availability check below never races another in-flight reservation
    -- for the same room.
    PERFORM pg_advisory_xact_lock(hashtextextended(p_room_id::text, 0));

    SELECT min(
        room.available_room_count - coalesce((
            SELECT sum(b.room_count)::integer
            FROM public.bookings b
            WHERE b.room_id = room.id
              AND (
                  b.status = 'CONFIRMED'
                  OR (b.status = 'RESERVED' AND b.expires_at > now())
              )
              AND b.check_in_date <= night.stay_date
              AND b.check_out_date > night.stay_date
        ), 0)
    ) INTO v_available
    FROM public.rooms room
    CROSS JOIN LATERAL generate_series(
        p_check_in_date::timestamp,
        (p_check_out_date - 1)::timestamp,
        interval '1 day'
    ) AS night(stay_date)
    WHERE room.id = p_room_id;

    IF coalesce(v_available, 0) < p_room_count THEN
        RAISE EXCEPTION 'insufficient_room_availability';
    END IF;

    INSERT INTO public.bookings (
        temporary_user_ref, room_id, check_in_date, check_in_time,
        check_out_date, check_out_time, room_count, status, expires_at,
        total_amount, currency
    ) VALUES (
        nullif(btrim(p_temporary_user_ref), ''), p_room_id, p_check_in_date,
        coalesce(p_check_in_time, time '14:00'), p_check_out_date,
        coalesce(p_check_out_time, time '12:00'), p_room_count, 'RESERVED',
        now() + make_interval(mins => p_hold_minutes), p_total_amount, p_currency
    )
    RETURNING * INTO v_booking;

    RETURN v_booking;
END;
$$;
REVOKE ALL ON FUNCTION public.create_booking_reservation(
    UUID, TEXT, DATE, TIME, DATE, TIME, INTEGER, NUMERIC, TEXT, INTEGER
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.create_booking_reservation(
    UUID, TEXT, DATE, TIME, DATE, TIME, INTEGER, NUMERIC, TEXT, INTEGER
) TO service_role;

-- confirm_booking_reservation — flips a held booking to CONFIRMED. Locks the
-- specific booking row (FOR UPDATE) rather than the room-level advisory
-- lock — confirm doesn't need to recompute room-wide availability, only
-- guard against a concurrent confirm/cancel on the SAME row. Ownership is
-- `temporary_user_ref` equality; a missing booking and a wrong ref raise the
-- identical 'booking_not_found' so neither case leaks which one it was
-- (same pattern as this codebase's session-not-found handling). A RESERVED
-- row whose hold already lapsed is lazily flipped to EXPIRED right here
-- (the only place a stale RESERVED row's status column is ever touched;
-- availability itself already excludes it via expires_at > now() regardless).
CREATE OR REPLACE FUNCTION public.confirm_booking_reservation(
    p_booking_id UUID,
    p_temporary_user_ref TEXT
)
RETURNS bookings
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_booking public.bookings;
BEGIN
    SELECT * INTO v_booking FROM public.bookings WHERE id = p_booking_id FOR UPDATE;

    IF NOT FOUND OR v_booking.temporary_user_ref IS DISTINCT FROM nullif(btrim(p_temporary_user_ref), '') THEN
        RAISE EXCEPTION 'booking_not_found';
    END IF;

    IF v_booking.status = 'RESERVED' AND v_booking.expires_at <= now() THEN
        UPDATE public.bookings SET status = 'EXPIRED', updated_at = now() WHERE id = p_booking_id;
        RAISE EXCEPTION 'booking_reservation_expired';
    END IF;

    IF v_booking.status <> 'RESERVED' THEN
        RAISE EXCEPTION 'booking_not_confirmable';
    END IF;

    UPDATE public.bookings
    SET status = 'CONFIRMED', expires_at = NULL, updated_at = now()
    WHERE id = p_booking_id
    RETURNING * INTO v_booking;

    RETURN v_booking;
END;
$$;
REVOKE ALL ON FUNCTION public.confirm_booking_reservation(UUID, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.confirm_booking_reservation(UUID, TEXT) TO service_role;

-- cancel_booking — releases a held (or even confirmed) booking. Idempotent:
-- calling it again on an already-CANCELLED or already-EXPIRED row just
-- returns that row unchanged instead of erroring, so a retried request or a
-- "cancel the rest of a hold group after one reservation failed" cleanup
-- loop (frontend's use-room-hold.ts) never has to special-case a double-cancel.
CREATE OR REPLACE FUNCTION public.cancel_booking(
    p_booking_id UUID,
    p_temporary_user_ref TEXT
)
RETURNS bookings
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_booking public.bookings;
BEGIN
    SELECT * INTO v_booking FROM public.bookings WHERE id = p_booking_id FOR UPDATE;

    IF NOT FOUND OR v_booking.temporary_user_ref IS DISTINCT FROM nullif(btrim(p_temporary_user_ref), '') THEN
        RAISE EXCEPTION 'booking_not_found';
    END IF;

    IF v_booking.status IN ('CANCELLED', 'EXPIRED') THEN
        RETURN v_booking;
    END IF;

    UPDATE public.bookings
    SET status = 'CANCELLED', cancelled_at = now(), updated_at = now()
    WHERE id = p_booking_id
    RETURNING * INTO v_booking;

    RETURN v_booking;
END;
$$;
REVOKE ALL ON FUNCTION public.cancel_booking(UUID, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.cancel_booking(UUID, TEXT) TO service_role;
