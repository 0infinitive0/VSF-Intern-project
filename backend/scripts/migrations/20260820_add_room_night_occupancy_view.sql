-- Convenience view for eyeballing room availability in Supabase Studio's
-- Table Editor without writing SQL every time. Purely additive/read-only:
-- does not change `get_room_availability()` or any table, and carries no
-- risk to booking/payment correctness.
--
-- "How many rooms are left" is deliberately NOT a stored, decremented
-- column anywhere (see get_room_availability in
-- 20260818_add_booking_reservation_rpcs.sql / database_schema.sql) --
-- rooms.available_room_count is the crawled BASE capacity and never
-- changes when a booking is made. A denormalized "remaining" counter would
-- need every booking/cancel/expiry code path to keep it in sync by hand;
-- miss one and it silently drifts from reality forever, with no way to
-- detect it -- exactly the class of bug this same day's earlier fix
-- (fractional-VND `payments.amount` vs. VNPay's whole-VND settlement,
-- c6ba298) already cost a payment pipeline. Availability here stays a pure
-- function of `bookings`, recomputed on every read, so it can never drift
-- from the one source of truth -- the tradeoff is that it isn't a column
-- you can just glance at, which is the whole reason this view exists: a
-- SELECT-able, browsable object that still can't drift, because it's
-- still just a live computation over `bookings`, not a second copy of the
-- number.
--
-- One row per (room, night) that has at least one CONFIRMED or
-- unexpired-RESERVED booking -- a room/night with zero rows simply means
-- "nothing held, still at full base_capacity" (mirrors
-- get_room_availability's own status/date-overlap predicate exactly, just
-- pre-aggregated per night instead of min()'d across a queried stay
-- range). Safe to re-run (CREATE OR REPLACE).
CREATE OR REPLACE VIEW public.room_night_occupancy AS
SELECT
    r.id AS room_id,
    r.hotel_id,
    r.name AS room_name,
    r.available_room_count AS base_capacity,
    nights.night::date AS night,
    sum(b.room_count)::integer AS units_held,
    (r.available_room_count - sum(b.room_count))::integer AS units_available
FROM public.bookings AS b
JOIN public.rooms AS r ON r.id = b.room_id
CROSS JOIN LATERAL generate_series(
    b.check_in_date::timestamp,
    (b.check_out_date - 1)::timestamp,
    interval '1 day'
) AS nights(night)
WHERE b.status = 'CONFIRMED' OR (b.status = 'RESERVED' AND b.expires_at > now())
GROUP BY r.id, r.hotel_id, r.name, r.available_room_count, nights.night
ORDER BY r.id, nights.night;

-- Same lockdown as every other booking/payment-adjacent object in this
-- schema (see amenity_catalog, payments, get_room_availability) -- this
-- view exposes per-guest booking volume per room/night, not something
-- anon/authenticated API clients should be able to read directly. Grants
-- here don't affect what you see in Supabase Studio's Table Editor/SQL
-- Editor (the dashboard connects with elevated/owner privileges), only
-- what the REST/GraphQL API exposes to anon and authenticated callers.
REVOKE ALL ON public.room_night_occupancy FROM PUBLIC, anon, authenticated;
GRANT SELECT ON public.room_night_occupancy TO service_role;
