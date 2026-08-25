-- Phase 11 (B6, phase-11-room-prices.md): admin bulk price write. Postgrest's
-- REST upsert only targets a plain-column ON CONFLICT list
-- (`?on_conflict=col1,col2`), but room_prices' natural-key uniqueness is the
-- expression index `ux_room_prices_natural_key` on
-- `(room_id, check_in_date, check_out_date, COALESCE(source_url, ''))` --
-- postgrest cannot target that from the table REST API, so this RPC issues
-- the raw upsert instead and returns aggregate counts so the caller can
-- write one summarized admin_audit_log row per call instead of one per
-- night.
--
-- `source_url` is always written as NULL and `crawled_at` as now() -- this
-- is what lets an admin-entered price outrank a stale OTA row for the same
-- night (place_details._average_price picks the row with the latest
-- crawled_at) without touching the OTA pipeline itself (decision #7).
CREATE OR REPLACE FUNCTION public.admin_upsert_room_prices(
    p_room_id UUID,
    p_nights DATE[],
    p_price NUMERIC,
    p_currency TEXT,
    p_sold_out BOOLEAN
)
RETURNS TABLE(written INTEGER, created INTEGER, updated INTEGER)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
    WITH upsert AS (
        INSERT INTO room_prices (room_id, price, currency, check_in_date, check_out_date, sold_out, source_url, crawled_at)
        SELECT p_room_id, p_price, p_currency, night, night + 1, p_sold_out, NULL, now()
        -- DISTINCT here, not just in the caller: "ON CONFLICT DO UPDATE
        -- command cannot affect row a second time" is a hard Postgres error
        -- (SQLSTATE 21000) if p_nights ever repeats a date, and this RPC is
        -- now a durable DB contract other callers may reach besides the
        -- admin API's own Pydantic-deduped request body.
        FROM (SELECT DISTINCT night FROM unnest(p_nights) AS night) AS nights
        ON CONFLICT (room_id, check_in_date, check_out_date, COALESCE(source_url, ''))
        DO UPDATE SET price = EXCLUDED.price,
                      currency = EXCLUDED.currency,
                      sold_out = EXCLUDED.sold_out,
                      crawled_at = now()
        RETURNING (xmax = 0) AS inserted
    )
    SELECT count(*)::integer AS written,
           count(*) FILTER (WHERE inserted)::integer AS created,
           count(*) FILTER (WHERE NOT inserted)::integer AS updated
    FROM upsert;
$$;

REVOKE ALL ON FUNCTION public.admin_upsert_room_prices(UUID, DATE[], NUMERIC, TEXT, BOOLEAN) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.admin_upsert_room_prices(UUID, DATE[], NUMERIC, TEXT, BOOLEAN)
    TO service_role;
