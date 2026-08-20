-- Party-size ("min_guests") search used to be an app-level post-filter (Python,
-- hotel_selection.py) applied AFTER the RPC's own `LIMIT match_count` — so a
-- search asking for 5 hotels could over-fetch, filter, and still come back with
-- fewer than 5 even when more qualifying hotels existed beyond the over-fetched
-- page. It also only ever checked a single room's `max_guests`, which is wrong
-- once a guest can book MULTIPLE rooms (and multiple room types) at one hotel to
-- cover a large party — a hotel with two 2-guest rooms can seat 4 people even
-- though no single room does.
--
-- This moves the filter into the RPC itself, before the final ORDER BY/LIMIT —
-- same treatment `20260730_add_price_filter_to_match_hotels_with_rooms.sql` gave
-- price — so `LIMIT match_count` means "best match_count hotels that can ALSO
-- seat the party", not "best match_count hotels, then hope enough survive a
-- second filter pass." A hotel's capacity is the SUM, across every room type it
-- has, of (how many units of that type are bookable) * (that type's max_guests):
-- exactly the ceiling on what a guest could assemble by booking several rooms.
-- "How many units are bookable" is `get_room_availability` for a real date
-- range (same per-night, booking-aware count `hotel_scores`/`room_scores`
-- already use), or the room's `available_room_count` inventory snapshot when no
-- dates were given yet (mirrors how those same two CTEs skip the availability
-- EXISTS check entirely when dates are absent).
--
-- Safe to apply to an existing Supabase project more than once (CREATE OR
-- REPLACE). The old signature is dropped first: Postgres treats a different
-- parameter list as a distinct overload rather than a replacement, and having
-- both simultaneously makes every existing call ambiguous ("function ... is not
-- unique") since the new function's extra parameter has a default too.
DROP FUNCTION IF EXISTS "public"."match_hotels_with_rooms"(
    "uuid"[], "public"."vector", double precision, integer, "uuid", numeric, numeric,
    double precision, double precision, double precision, date, date
);

CREATE OR REPLACE FUNCTION "public"."match_hotels_with_rooms"(
    "filter_exclude_hotel_ids" "uuid"[],
    "query_embedding" "public"."vector",
    "match_threshold" double precision DEFAULT 0.3,
    "match_count" integer DEFAULT 10,
    "filter_destination_id" "uuid" DEFAULT NULL::"uuid",
    "filter_min_price" numeric DEFAULT NULL::numeric,
    "filter_max_price" numeric DEFAULT NULL::numeric,
    "root_latitude" double precision DEFAULT NULL::double precision,
    "root_longitude" double precision DEFAULT NULL::double precision,
    "max_radius_km" double precision DEFAULT NULL::double precision,
    "filter_start_date" date DEFAULT NULL::date,
    "filter_end_date" date DEFAULT NULL::date,
    "filter_min_guests" integer DEFAULT NULL::integer
) RETURNS TABLE(
    "id" "uuid",
    "name" "text",
    "description" "text",
    "star_rating" double precision,
    "lowest_price" numeric,
    "average_nightly_price" numeric,
    "total_stay_price" numeric,
    "stay_night_count" integer,
    "currency" "text",
    "priced_room_name" "text",
    "similarity" double precision,
    "matched_room_names" "text"[],
    "amenities" jsonb
)
    LANGUAGE "sql" STABLE
    AS $$
  WITH hotel_scores AS (
    SELECT
      h.id AS hotel_id,
      1 - (h.embedding <=> query_embedding) AS sim,
      NULL::text AS room_name
    FROM public.hotels AS h
    WHERE h.embedding IS NOT NULL
      AND (filter_destination_id IS NULL OR h.destination_id = filter_destination_id)
      AND (
        filter_start_date IS NULL OR filter_end_date IS NULL
        OR EXISTS (
          SELECT 1
          FROM public.rooms AS r
          WHERE r.hotel_id = h.id
            AND (
              SELECT count(*)
              FROM public.room_prices AS rp
              WHERE rp.room_id = r.id
                AND rp.check_in_date >= filter_start_date
                AND rp.check_out_date <= filter_end_date
                AND rp.sold_out = false
            ) = (filter_end_date - filter_start_date)
            AND public.get_room_availability(
              r.id, filter_start_date, filter_end_date
            ) > 0
        )
      )
  ),
  room_scores AS (
    SELECT
      r.hotel_id,
      1 - (r.embedding <=> query_embedding) AS sim,
      r.name AS room_name
    FROM public.rooms AS r
    JOIN public.hotels AS h ON h.id = r.hotel_id
    WHERE r.embedding IS NOT NULL
      AND (filter_destination_id IS NULL OR h.destination_id = filter_destination_id)
      AND (
        filter_start_date IS NULL OR filter_end_date IS NULL
        OR (
          SELECT count(*)
          FROM public.room_prices AS rp
          WHERE rp.room_id = r.id
            AND rp.check_in_date >= filter_start_date
            AND rp.check_out_date <= filter_end_date
            AND rp.sold_out = false
        ) = (filter_end_date - filter_start_date)
        AND public.get_room_availability(
          r.id, filter_start_date, filter_end_date
        ) > 0
      )
  ),
  combined AS (
    SELECT * FROM hotel_scores WHERE sim > match_threshold
    UNION ALL
    SELECT * FROM room_scores WHERE sim > match_threshold
  ),
  aggregated AS (
    SELECT
      hotel_id,
      max(sim) AS max_sim,
      array_remove(array_agg(DISTINCT room_name), NULL) AS matched_rooms
    FROM combined
    GROUP BY hotel_id
  ),
  -- Total guests this hotel could seat by booking every bookable unit of every
  -- room type it has -- the ceiling on what's assemblable across multiple rooms
  -- and multiple room types, not just the single largest room.
  hotel_capacity AS (
    SELECT
      r.hotel_id,
      sum(
        greatest(
          CASE
            WHEN filter_start_date IS NULL OR filter_end_date IS NULL
              THEN coalesce(r.available_room_count, 0)
            ELSE public.get_room_availability(r.id, filter_start_date, filter_end_date)
          END,
          0
        ) * coalesce(r.max_guests, 0)
      ) AS total_capacity
    FROM public.rooms AS r
    GROUP BY r.hotel_id
  )
  SELECT
    h.id,
    h.name,
    h.description,
    h.star_rating,
    h.lowest_price,
    h.lowest_price AS average_nightly_price,
    h.lowest_price * coalesce(filter_end_date - filter_start_date, 1) AS total_stay_price,
    coalesce(filter_end_date - filter_start_date, 1) AS stay_night_count,
    h.currency,
    NULL::text AS priced_room_name,
    a.max_sim AS similarity,
    a.matched_rooms AS matched_room_names,
    coalesce(
      (
        SELECT jsonb_agg(
          jsonb_build_object(
            'id', catalog.id,
            'label_vi', catalog.label_vi,
            'label_en', catalog.label_en,
            'category', catalog.category,
            'icon_key', catalog.icon_key
          )
          ORDER BY amenity.ordinality
        )
        FROM unnest(coalesce(h.amenities, ARRAY[]::text[])) WITH ORDINALITY
          AS amenity(amenity_id, ordinality)
        JOIN public.amenity_catalog AS catalog ON catalog.id = amenity.amenity_id
        WHERE catalog.is_approved
      ),
      '[]'::jsonb
    ) AS amenities
  FROM aggregated AS a
  JOIN public.hotels AS h ON h.id = a.hotel_id
  LEFT JOIN hotel_capacity AS hc ON hc.hotel_id = h.id
  WHERE (filter_min_price IS NULL OR h.lowest_price IS NULL OR h.lowest_price >= filter_min_price)
    AND (filter_max_price IS NULL OR h.lowest_price IS NULL OR h.lowest_price <= filter_max_price)
    AND (
      cardinality(coalesce(filter_exclude_hotel_ids, ARRAY[]::uuid[])) = 0
      OR h.id <> ALL(filter_exclude_hotel_ids)
    )
    AND (filter_min_guests IS NULL OR coalesce(hc.total_capacity, 0) >= filter_min_guests)
  ORDER BY a.max_sim DESC
  LIMIT match_count;
$$;

ALTER FUNCTION "public"."match_hotels_with_rooms"(
    "uuid"[], "public"."vector", double precision, integer, "uuid", numeric, numeric,
    double precision, double precision, double precision, date, date, integer
) OWNER TO "postgres";

GRANT EXECUTE ON FUNCTION "public"."match_hotels_with_rooms"(
    "uuid"[], "public"."vector", double precision, integer, "uuid", numeric, numeric,
    double precision, double precision, double precision, date, date, integer
) TO anon, authenticated, service_role;
