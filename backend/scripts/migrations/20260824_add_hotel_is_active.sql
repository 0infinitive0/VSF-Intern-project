-- Soft-delete flag for hotels. Admin "Ngừng bán" (deactivate) must not remove
-- the row: rooms(hotel_id) references hotels(id) and bookings/payments chain
-- off rooms, so a hard delete would need cascading through live booking data.
-- ADD COLUMN ... DEFAULT true is a metadata-only change on Postgres 11+ (no
-- table rewrite, no long lock) because the default is a constant.
ALTER TABLE hotels ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT true;

-- Partial index: only rows that need filtering out (is_active = false) are
-- indexed. While every hotel is active (the common case), the planner has no
-- reason to use it at all.
CREATE INDEX hotels_is_active_idx ON hotels (is_active) WHERE is_active = false;
