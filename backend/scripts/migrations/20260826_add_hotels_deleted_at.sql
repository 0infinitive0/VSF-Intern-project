-- Admin B1 "Xoá khách sạn" (delete button + confirm on the hotel list).
-- Distinct from `is_active` (20260824_add_hotel_is_active.sql, the "Ngừng
-- bán" sell/no-sell toggle that still lists the hotel): `deleted_at` removes
-- the hotel from the admin list entirely while keeping the row (and every
-- FK'd room/room_prices/booking underneath it) intact -- rooms(hotel_id) is
-- ON DELETE CASCADE and bookings(room_id) is ON DELETE RESTRICT, so a hard
-- delete would either 500 on live booking history or cascade-erase it.
ALTER TABLE hotels ADD COLUMN deleted_at TIMESTAMPTZ;

-- admin_hotel_rows (20260824_add_admin_hotel_view.sql) now excludes
-- soft-deleted hotels so B1's list, filters, and CSV export never see them.
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
WHERE h.deleted_at IS NULL
GROUP BY h.id;

REVOKE ALL ON public.admin_hotel_rows FROM anon, authenticated, PUBLIC;
GRANT  SELECT ON public.admin_hotel_rows TO service_role;
