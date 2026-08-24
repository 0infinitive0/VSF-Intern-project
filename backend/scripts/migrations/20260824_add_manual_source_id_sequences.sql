-- hotels.source_hotel_id / rooms.source_room_id are BIGINT NOT NULL, keyed by
-- UNIQUE(source_platform, source_hotel_id) and UNIQUE(hotel_id, source_room_id)
-- respectively -- there is no UUID variant of either column to generate into.
-- Admin-entered hotels/rooms (no OTA origin) need their own id source that
-- can never collide with a real OTA id. Because source_platform is part of
-- the hotels unique key, a manual hotel can safely reuse a numeric id an OTA
-- also happens to use -- the platform value keeps them apart.
--
-- rooms has no source_platform column at all -- its unique key is scoped only
-- to (hotel_id, source_room_id) -- so an admin-entered room added to an
-- EXISTING crawled hotel has no discriminator protecting it: a later re-crawl
-- of that hotel that happens to assign a small OTA room_id equal to the
-- manual room's id would upsert (ON CONFLICT ... DO UPDATE) straight over the
-- admin's row, silently. manual_room_source_id_seq therefore starts at a high
-- offset, comfortably inside BIGINT and far above any plausible real OTA
-- room_id, so that collision can't happen in practice.
--
-- No DEFAULT is attached to either column: ETL inserts must keep writing the
-- OTA's original source_hotel_id/source_room_id untouched. The backend reads
-- nextval() explicitly only on the admin-entry insert path.
CREATE SEQUENCE manual_hotel_source_id_seq START 1;
CREATE SEQUENCE manual_room_source_id_seq START 9000000000;

-- Same deny-by-default posture as every table in this schema: only the
-- backend (service_role) should ever pull the next id.
REVOKE ALL ON SEQUENCE manual_hotel_source_id_seq FROM anon, authenticated, PUBLIC;
REVOKE ALL ON SEQUENCE manual_room_source_id_seq FROM anon, authenticated, PUBLIC;
GRANT USAGE, SELECT ON SEQUENCE manual_hotel_source_id_seq TO service_role;
GRANT USAGE, SELECT ON SEQUENCE manual_room_source_id_seq TO service_role;
