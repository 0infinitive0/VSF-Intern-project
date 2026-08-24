-- Admin B1 (Danh sách khách sạn) read model. One row per hotel with the
-- aggregates the screen needs -- room count and per-hotel/per-room
-- embedding coverage -- computed here so the admin API issues one query
-- instead of N+1 per hotel. Safe to re-run (CREATE OR REPLACE).
--
-- `hotels` itself stays open to `anon` (the chat app reads it directly),
-- but this view adds operational aggregates an unauthenticated caller has
-- no reason to see, so it is locked to service_role only, same posture as
-- room_night_occupancy (20260820_add_room_night_occupancy_view.sql).
CREATE OR REPLACE VIEW public.admin_hotel_rows AS
SELECT
  h.id, h.name, h.address, h.city, h.star_rating,
  h.source_platform, h.is_active, h.image_url,
  (h.source_platform = 'manual')                    AS is_manual,
  (h.embedding IS NOT NULL)                         AS hotel_embedded,
  count(r.id)                                       AS room_count,
  count(r.id) FILTER (WHERE r.embedding IS NULL)    AS rooms_missing_embedding,
  h.updated_at
FROM public.hotels h
LEFT JOIN public.rooms r ON r.hotel_id = h.id
GROUP BY h.id;

REVOKE ALL ON public.admin_hotel_rows FROM anon, authenticated, PUBLIC;
GRANT  SELECT ON public.admin_hotel_rows TO service_role;
