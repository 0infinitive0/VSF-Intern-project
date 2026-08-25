-- Phase 18 (plans/260824-1015-admin-dashboard-portal/phase-18-amenity-catalog.md):
-- Danh mục tiện ích & tiện nghi.
--
-- `amenity_catalog.needs_review`/`retired_at` already exist on this database
-- (20260821_hotel_preference_catalog_redesign.sql) -- this migration does NOT
-- add columns. It adds one view (usage counts for the "Dùng ở" column and the
-- "Ngừng dùng" usage guard) and does a one-time cleanup of `needs_review`,
-- which is out of scope for this phase (decision #5): the column stays, but
-- the 2026-08-21 backfill's flags are cleared so they don't sit unactioned
-- with no UI to see or clear them.

begin;

create view admin_amenity_usage as
select amenity_id,
       count(*) filter (where src = 'hotel') as hotel_count,
       count(*) filter (where src = 'room')  as room_count
from (
  select unnest(coalesce(amenities, '{}'::text[]))       as amenity_id, 'hotel' as src from hotels
  union all
  select unnest(coalesce(room_facilities, '{}'::text[])) as amenity_id, 'room'  as src from rooms
) u
group by amenity_id;

revoke all on admin_amenity_usage from anon, authenticated, public;
grant select on admin_amenity_usage to service_role;

update amenity_catalog set needs_review = false where needs_review;

commit;
