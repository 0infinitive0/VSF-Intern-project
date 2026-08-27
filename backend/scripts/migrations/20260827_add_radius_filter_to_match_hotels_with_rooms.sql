-- match_hotels_with_rooms has accepted root_latitude/root_longitude/max_radius_km
-- since the signature was first written, but the body never referenced any of the
-- three: every WHERE clause filtered on is_active, destination, stay dates, price,
-- exclusions and guest capacity only. A radius request therefore returned hotels at
-- any distance, silently -- no error, no log, nothing for the caller to notice. The
-- app side was already correct end to end (`search_center.resolve_center` geocodes
-- the named landmark against `attractions`/`hotels` and never guesses,
-- `supabase_search.validate_radius_filter` range-checks the triple, and
-- `hotel_selection.select_hotel_candidates` forwards it), and there is no app-side
-- distance filter to fall back on, so the whole feature ended at this function.
--
-- Observed on 2026-08-27 (LangSmith trace 01a04156-1221-7ad1-a7ec-28937a1247f3):
-- "khách sạn ... cách Cầu Rồng trong 3km" resolved the center correctly to
-- 16.0611042,108.2276926 and still returned hotels 3.363 km and 3.898 km away.
--
-- Filtering happens in BOTH scoring CTEs rather than in the final WHERE so distance
-- prunes hotels before the vector comparison and before the per-room availability
-- subqueries run, which is also the only placement the GiST index below can serve.
--
-- earthdistance (a great-circle sphere of 6378.168 km, the equatorial radius) is used
-- instead of match_attractions' hand-rolled 6371.0 haversine because only the former
-- has an indexable operator. The two disagree by ~0.1% -- about 4 m at a 3 km radius --
-- which is far inside the precision of the stored coordinates themselves.
--
-- Hotels whose `coordinates` are NULL or malformed yield a NULL point, so they drop
-- out whenever a radius filter is active and are unaffected when it is not. That is
-- deliberate: a hotel whose position is unknown cannot be shown as being within 3 km
-- of anything.

CREATE SCHEMA IF NOT EXISTS extensions;

-- earthdistance's install script calls cube's functions unqualified, so cube has to
-- be resolvable by name while it runs, not merely installed.
CREATE EXTENSION IF NOT EXISTS cube WITH SCHEMA extensions;
SET search_path = extensions, public;
CREATE EXTENSION IF NOT EXISTS earthdistance WITH SCHEMA extensions;
RESET search_path;

-- `hotels.coordinates` is a "lat,lng" varchar, so the point has to be parsed before
-- it can be compared. Wrapping the parse in one IMMUTABLE function -- rather than
-- inlining the CASE at both call sites -- is what lets the index expression below and
-- the RPC predicates be spelled identically, which is the condition for the planner
-- to match them.
--
-- The regex guard is what makes this total: a row that is not a well-formed pair
-- yields NULL instead of raising, so a single bad row can neither break the index
-- build nor fail a search. It is written with single backslashes on purpose --
-- doubling them is exactly the bug 20260817_fix_match_attractions_radius_regex.sql
-- had to undo, since Postgres does not unescape backslashes in a plain literal.
CREATE OR REPLACE FUNCTION public.coordinates_to_earth(coordinates TEXT)
RETURNS extensions.earth
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
SET search_path = ''
AS $$
  SELECT CASE
    WHEN coordinates ~ '^\s*-?\d+(\.\d+)?\s*,\s*-?\d+(\.\d+)?\s*$'
    THEN extensions.ll_to_earth(
           split_part(coordinates, ',', 1)::double precision,
           split_part(coordinates, ',', 2)::double precision
         )
  END;
$$;

ALTER FUNCTION public.coordinates_to_earth(TEXT) OWNER TO "postgres";

GRANT EXECUTE ON FUNCTION public.coordinates_to_earth(TEXT)
    TO anon, authenticated, service_role;

CREATE INDEX IF NOT EXISTS idx_hotels_coordinates_earth
    ON public.hotels
    USING gist (public.coordinates_to_earth(coordinates));

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
      -- earth_box is a bounding cube, so it admits corner rows that are further than
      -- max_radius_km; it is the part an index can answer. earth_distance is the
      -- exact great-circle check that removes them again. Both are needed.
      AND (
        root_latitude IS NULL OR root_longitude IS NULL OR max_radius_km IS NULL
        OR (
          public.coordinates_to_earth(h.coordinates) OPERATOR(extensions.<@)
            extensions.earth_box(
              extensions.ll_to_earth(root_latitude, root_longitude),
              max_radius_km * 1000.0
            )
          AND extensions.earth_distance(
                public.coordinates_to_earth(h.coordinates),
                extensions.ll_to_earth(root_latitude, root_longitude)
              ) <= max_radius_km * 1000.0
        )
      )
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
        root_latitude IS NULL OR root_longitude IS NULL OR max_radius_km IS NULL
        OR (
          public.coordinates_to_earth(h.coordinates) OPERATOR(extensions.<@)
            extensions.earth_box(
              extensions.ll_to_earth(root_latitude, root_longitude),
              max_radius_km * 1000.0
            )
          AND extensions.earth_distance(
                public.coordinates_to_earth(h.coordinates),
                extensions.ll_to_earth(root_latitude, root_longitude)
              ) <= max_radius_km * 1000.0
        )
      )
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
