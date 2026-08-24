-- postgrest exposes tables/views/functions, not raw sequences -- there is no
-- REST path to call nextval() directly. Phase 8 (B2, tạo khách sạn tay) needs
-- exactly that: allocate the next manual_hotel_source_id_seq value (see
-- 20260824_add_manual_source_id_sequences.sql) from the admin API to satisfy
-- hotels' UNIQUE(source_platform, source_hotel_id) on insert. This function is
-- the minimal wrapper making that one sequence callable via .rpc(), nothing
-- more -- it does not touch the hotels table itself.
CREATE OR REPLACE FUNCTION public.next_manual_hotel_source_id()
RETURNS BIGINT
LANGUAGE sql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
    SELECT nextval('public.manual_hotel_source_id_seq');
$$;

REVOKE ALL ON FUNCTION public.next_manual_hotel_source_id() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.next_manual_hotel_source_id() TO service_role;
