-- Phase 11 (B6, phase-11-room-prices.md) code review finding: an admin
-- marking a night `sold_out=true` did NOT reliably hide it from bot
-- search/pricing when an OTA row already existed for that same night.
--
-- `match_hotels_with_rooms`'s "does every requested night have a live
-- price" check counted `count(DISTINCT rp.check_in_date) WHERE
-- rp.sold_out = false` -- filtering `sold_out` PER ROW, before asking which
-- row is the freshest for that night. A night with two rows -- an older OTA
-- row (`sold_out=false`) and a newer admin row (`sold_out=true`, meant to
-- close it) -- still had a `sold_out=false` row satisfying the filter, so
-- the night still counted as open. Exactly the class of bug F3/F4
-- (phase-01-migrations.md) already fixed for the PRICE side (the freshest
-- `crawled_at` row wins) but never applied to `sold_out` -- crawled_at
-- precedence only actually took effect among rows that were already
-- `sold_out=false`, so flipping `sold_out` opted the admin's own row out of
-- the very comparison it needed to win.
--
-- `count_priced_open_nights` fixes this once, shared by both CTEs below:
-- pick the freshest row PER NIGHT first (`DISTINCT ON ... ORDER BY
-- crawled_at DESC`), THEN check that one row's `sold_out` -- same
-- freshest-wins semantics `place_details._average_price` already uses for
-- price (see backend/src/services/place_details.py, fixed in this same
-- change).
CREATE OR REPLACE FUNCTION public.count_priced_open_nights(
    p_room_id UUID,
    p_start_date DATE,
    p_end_date DATE
)
RETURNS INTEGER
LANGUAGE sql
STABLE
AS $$
    SELECT count(*)::integer
    FROM (
        SELECT DISTINCT ON (rp.check_in_date) rp.sold_out
        FROM public.room_prices AS rp
        WHERE rp.room_id = p_room_id
          AND rp.check_in_date >= p_start_date
          AND rp.check_out_date <= p_end_date
        ORDER BY rp.check_in_date, rp.crawled_at DESC
    ) AS freshest
    WHERE freshest.sold_out = false;
$$;

GRANT EXECUTE ON FUNCTION public.count_priced_open_nights(UUID, DATE, DATE)
    TO anon, authenticated, service_role;

-- Signature unchanged (same 13 parameters) -- CREATE OR REPLACE keeps every
-- existing call site working untouched. Only change from the live function:
-- both `count(DISTINCT rp.check_in_date) ... AND rp.sold_out = false`
-- subqueries replaced with `count_priced_open_nights(...)`.
CREATE OR REPLACE FUNCTION public.match_hotels_with_rooms(
    filter_exclude_hotel_ids UUID[],
    query_embedding public.vector,
    match_threshold DOUBLE PRECISION DEFAULT 0.3,
    match_count INTEGER DEFAULT 10,
    filter_destination_id UUID DEFAULT NULL::uuid,
    filter_min_price NUMERIC DEFAULT NULL::numeric,
    filter_max_price NUMERIC DEFAULT NULL::numeric,
    root_latitude DOUBLE PRECISION DEFAULT NULL::double precision,
    root_longitude DOUBLE PRECISION DEFAULT NULL::double precision,
    max_radius_km DOUBLE PRECISION DEFAULT NULL::double precision,
    filter_start_date DATE DEFAULT NULL::date,
    filter_end_date DATE DEFAULT NULL::date,
    filter_min_guests INTEGER DEFAULT NULL::integer
)
RETURNS TABLE(
    id UUID,
    name TEXT,
    description TEXT,
    star_rating DOUBLE PRECISION,
    lowest_price NUMERIC,
    average_nightly_price NUMERIC,
    total_stay_price NUMERIC,
    stay_night_count INTEGER,
    currency TEXT,
    priced_room_name TEXT,
    similarity DOUBLE PRECISION,
    matched_room_names TEXT[],
    "amenities" JSONB
)
LANGUAGE sql
STABLE
AS $$
  WITH hotel_scores AS (
    SELECT
      h.id AS hotel_id,
      1 - (h.embedding <=> query_embedding) AS sim,
      NULL::text AS room_name
    FROM public.hotels AS h
    WHERE h.embedding IS NOT NULL
      AND h.is_active
      AND (filter_destination_id IS NULL OR h.destination_id = filter_destination_id)
      AND (
        filter_start_date IS NULL OR filter_end_date IS NULL
        OR EXISTS (
          SELECT 1
          FROM public.rooms AS r
          WHERE r.hotel_id = h.id
            AND public.count_priced_open_nights(
              r.id, filter_start_date, filter_end_date
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
      AND h.is_active
      AND (filter_destination_id IS NULL OR h.destination_id = filter_destination_id)
      AND (
        filter_start_date IS NULL OR filter_end_date IS NULL
        OR (
          public.count_priced_open_nights(
            r.id, filter_start_date, filter_end_date
          ) = (filter_end_date - filter_start_date)
          AND public.get_room_availability(
            r.id, filter_start_date, filter_end_date
          ) > 0
        )
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

ALTER FUNCTION public.match_hotels_with_rooms(
    UUID[], public.vector, DOUBLE PRECISION, INTEGER, UUID, NUMERIC, NUMERIC,
    DOUBLE PRECISION, DOUBLE PRECISION, DOUBLE PRECISION, DATE, DATE, INTEGER
) OWNER TO "postgres";

GRANT EXECUTE ON FUNCTION public.match_hotels_with_rooms(
    UUID[],
    public.vector,
    DOUBLE PRECISION,
    INTEGER,
    UUID,
    NUMERIC,
    NUMERIC,
    DOUBLE PRECISION,
    DOUBLE PRECISION,
    DOUBLE PRECISION,
    DATE,
    DATE,
    INTEGER
) TO anon, authenticated, service_role;
