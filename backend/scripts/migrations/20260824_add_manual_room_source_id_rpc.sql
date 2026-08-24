-- Same rationale as 20260824_add_manual_hotel_source_id_rpc.sql: postgrest
-- exposes tables/views/functions, not raw sequences, so there is no REST path
-- to call nextval() directly. Phase 10 (B5, quản lý phòng tay) needs exactly
-- that: allocate the next manual_room_source_id_seq value (see
-- database_schema.sql) from the admin API to satisfy rooms'
-- UNIQUE(hotel_id, source_room_id) on insert.
CREATE OR REPLACE FUNCTION public.next_manual_room_source_id()
RETURNS BIGINT
LANGUAGE sql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
    SELECT nextval('public.manual_room_source_id_seq');
$$;

REVOKE ALL ON FUNCTION public.next_manual_room_source_id() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.next_manual_room_source_id() TO service_role;
