-- "Chưa chạy lại embedding": a row whose vector still exists but whose
-- RAG text has been edited since that vector was built.
--
-- Before this, an admin edit to a RAG field (EMBEDDING_FIELDS /
-- RAG_FIELDS_ROOM in src/api/admin/embedding_fields.py) set `embedding` back
-- to NULL. That made the row indistinguishable from one that was never
-- embedded ("Chưa embed") AND dropped it out of match_hotels_with_rooms
-- entirely -- the bot stopped finding the hotel at all until the next DAG
-- run, which is worse for search than answering from slightly stale text.
--
-- `embedding_stale` keeps the old vector in place and records that it no
-- longer matches the row's text. The admin UI renders it as its own state
-- and the "Chạy embedding" button clears it by re-embedding.
ALTER TABLE hotels ADD COLUMN embedding_stale BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE rooms  ADD COLUMN embedding_stale BOOLEAN NOT NULL DEFAULT false;

-- Partial indexes: every read is "which rows still need re-embedding", never
-- "which rows are fine", so only the true side is worth indexing.
CREATE INDEX hotels_embedding_stale_idx ON hotels (embedding_stale) WHERE embedding_stale;
CREATE INDEX rooms_embedding_stale_idx  ON rooms  (embedding_stale) WHERE embedding_stale;

-- admin_hotel_rows (20260826_add_hotels_deleted_at.sql) gains the two
-- staleness aggregates B1/B7's embedding dot needs. New columns are appended
-- after `updated_at` -- CREATE OR REPLACE VIEW can only add columns at the
-- end, never reorder the existing ones.
--
-- A row that is stale but has no vector at all is already "Chưa embed" (a
-- stronger state), so `hotel_embedding_stale` is deliberately gated on
-- `embedding IS NOT NULL`: staleness only means anything on top of an
-- existing vector.
CREATE OR REPLACE VIEW public.admin_hotel_rows AS
SELECT
  h.id, h.name, h.address, h.city, h.star_rating,
  h.source_platform, h.is_active, h.image_url,
  (h.source_platform = 'manual')                    AS is_manual,
  (h.embedding IS NOT NULL)                         AS hotel_embedded,
  count(r.id)                                       AS room_count,
  count(r.id) FILTER (WHERE r.embedding IS NULL)    AS rooms_missing_embedding,
  h.updated_at,
  (h.embedding IS NOT NULL AND h.embedding_stale)   AS hotel_embedding_stale,
  count(r.id) FILTER (
    WHERE r.embedding IS NOT NULL AND r.embedding_stale
  )                                                 AS rooms_stale_embedding
FROM public.hotels h
LEFT JOIN public.rooms r ON r.hotel_id = h.id
WHERE h.deleted_at IS NULL
GROUP BY h.id;

REVOKE ALL ON public.admin_hotel_rows FROM anon, authenticated, PUBLIC;
GRANT  SELECT ON public.admin_hotel_rows TO service_role;
