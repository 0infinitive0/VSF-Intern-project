-- Two changes to create_booking_reservation, landed together since both
-- touch the same function body (plan
-- 260818-vnpay-payment-and-email-confirmation, addendum 2):
--
--   1. bookings.session_id — links a hold to the chat session that created
--      it (sidebar "Đang giữ phòng"/"Đã thanh toán" badge — see
--      session_store.py's booking_states_for_sessions/summarize). New
--      nullable column + new p_session_id param, written through on INSERT.
--      confirm_booking_reservation/cancel_booking need NO changes: they
--      operate by p_booking_id, and session_id already rides along on the
--      row from creation.
--
--   2. A cross-hotel hold guard: nothing previously stopped one guest ref
--      (temporary_user_ref, shared cross-tab via localStorage — see
--      frontend/src/lib/guest-ref.ts) from holding rooms at two different
--      hotels at once, one hold per browser tab (roomHold's `status`/
--      `heldHotelId`/`bookings` are per-tab React state, and its
--      sessionStorage persistence is per-tab too — neither is shared across
--      tabs the way `temporary_user_ref` is). Fix has two parts:
--        a. a SECOND pg_advisory_xact_lock keyed on the guest ref (salt 1,
--           independent of the existing per-room lock's salt 0), taken
--           right alongside the room lock, so two concurrent requests for
--           the SAME guest ref (even for different hotels/rooms) serialize
--           against each other — closes the race the exception check below
--           can't close alone. Always locks room first, then guest ref, in
--           every call, so no deadlock cycle is possible.
--        b. after both locks, reject with 'guest_already_holding_elsewhere'
--           if this guest ref already has another live (RESERVED,
--           unexpired) booking at a DIFFERENT hotel. Reject only — never
--           auto-cancels the other hold, so nothing disappears out from
--           under a guest's other tab without them acting on it. Same-hotel
--           holds (a multi-room-type cart, or switchHold's release-then-
--           reserve for the hotel already held) are unaffected: the prior
--           hold at that hotel is already CANCELLED — a separate, already-
--           committed transaction — by the time this runs.
--
-- IMPORTANT: this is NOT a same-signature CREATE OR REPLACE. Adding
-- p_session_id changes the function's input-argument-type list, and
-- Postgres only lets CREATE OR REPLACE FUNCTION replace a function whose
-- argument types are unchanged — otherwise it silently creates a SECOND,
-- overloaded function and leaves the old 10-arg one live and callable with
-- none of the guard logic below. Drop the old signature explicitly first.

ALTER TABLE bookings
    ADD COLUMN session_id VARCHAR(255) REFERENCES sessions(session_id) ON DELETE SET NULL;

DROP FUNCTION IF EXISTS public.create_booking_reservation(
    UUID, TEXT, DATE, TIME, DATE, TIME, INTEGER, NUMERIC, TEXT, INTEGER
);

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
    p_hold_minutes INTEGER DEFAULT 15,
    p_session_id TEXT DEFAULT NULL
)
RETURNS bookings
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_booking public.bookings;
    v_available INTEGER;
    v_guest_ref TEXT;
    v_hotel_id UUID;
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

    -- Second lock, independent key (salt 1): serializes every concurrent
    -- hold attempt for THIS GUEST regardless of which room/hotel each is
    -- for. Trimmed the same way the INSERT below normalizes the ref, so two
    -- refs differing only by incidental whitespace still serialize. A NULL
    -- guest ref takes no lock here (pg_advisory_xact_lock is STRICT — a
    -- NULL argument is a silent no-op, not an error).
    v_guest_ref := nullif(btrim(p_temporary_user_ref), '');
    PERFORM pg_advisory_xact_lock(hashtextextended(v_guest_ref, 1));

    SELECT hotel_id INTO v_hotel_id FROM public.rooms WHERE id = p_room_id;

    -- Reject a hold at a different hotel while this guest ref already holds
    -- a live one elsewhere. v_hotel_id IS NOT NULL guards an unknown/bogus
    -- p_room_id: let that fall through to the existing availability check
    -- below (which already handles "no such room" via v_available staying
    -- NULL) rather than misreporting it as a cross-hotel conflict.
    IF v_hotel_id IS NOT NULL AND v_guest_ref IS NOT NULL AND EXISTS (
        SELECT 1
        FROM public.bookings b
        JOIN public.rooms br ON br.id = b.room_id
        WHERE b.temporary_user_ref = v_guest_ref
          AND b.status = 'RESERVED'
          AND b.expires_at > now()
          AND br.hotel_id IS DISTINCT FROM v_hotel_id
    ) THEN
        RAISE EXCEPTION 'guest_already_holding_elsewhere';
    END IF;

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
        total_amount, currency, session_id
    ) VALUES (
        nullif(btrim(p_temporary_user_ref), ''), p_room_id, p_check_in_date,
        coalesce(p_check_in_time, time '14:00'), p_check_out_date,
        coalesce(p_check_out_time, time '12:00'), p_room_count, 'RESERVED',
        now() + make_interval(mins => p_hold_minutes), p_total_amount, p_currency,
        nullif(btrim(p_session_id), '')
    )
    RETURNING * INTO v_booking;

    RETURN v_booking;
END;
$$;
REVOKE ALL ON FUNCTION public.create_booking_reservation(
    UUID, TEXT, DATE, TIME, DATE, TIME, INTEGER, NUMERIC, TEXT, INTEGER, TEXT
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.create_booking_reservation(
    UUID, TEXT, DATE, TIME, DATE, TIME, INTEGER, NUMERIC, TEXT, INTEGER, TEXT
) TO service_role;
