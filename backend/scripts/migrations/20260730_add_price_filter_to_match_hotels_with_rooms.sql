-- match_hotels_with_rooms previously never returned lowest_price, so callers could not
-- filter by budget at the SQL level: they had to fetch a large oversampled pool by
-- semantic similarity alone and filter by price in application code afterward, which
-- silently dropped in-range hotels whenever none of the top-N nearest-by-embedding
-- results happened to be in range (price is uncorrelated with embedding similarity).
-- This adds lowest_price to the return shape and two optional price bounds, filtered
-- directly in SQL before the final ORDER BY/LIMIT — so LIMIT match_count now means
-- "best match_count results that are ALSO in range", not "best match_count results,
-- then hope some survive a price filter applied afterward."
-- Safe to apply to an existing Supabase project more than once (CREATE OR REPLACE).
-- The old 4-arg signature is dropped first: Postgres treats a different parameter list
-- as a distinct overload rather than a replacement, and having both simultaneously makes
-- every existing 4-arg call ("query_embedding, match_threshold, match_count,
-- filter_destination_id") ambiguous — Postgres can no longer tell which overload to pick
-- since the new function's extra params all have defaults too, so it raises
-- "function ... is not unique" instead of picking one.
DROP FUNCTION IF EXISTS "public"."match_hotels_with_rooms"(
    "public"."vector", double precision, integer, "uuid"
);

CREATE OR REPLACE FUNCTION "public"."match_hotels_with_rooms"(
    "query_embedding" "public"."vector",
    "match_threshold" double precision DEFAULT 0.3,
    "match_count" integer DEFAULT 10,
    "filter_destination_id" "uuid" DEFAULT NULL::"uuid",
    "filter_min_price" numeric DEFAULT NULL,
    "filter_max_price" numeric DEFAULT NULL
) RETURNS TABLE(
    "id" "uuid",
    "name" "text",
    "description" "text",
    "star_rating" double precision,
    "lowest_price" numeric,
    "similarity" double precision,
    "matched_room_names" "text"[]
)
    LANGUAGE "sql" STABLE
    AS $$
  with hotel_scores as (
    -- 1. Calculate similarity against hotel descriptions/amenities
    select
      id as hotel_id,
      1 - (embedding <=> query_embedding) as sim,
      null::text as room_name
    from hotels
    where embedding is not null
      and (filter_destination_id is null or destination_id = filter_destination_id)
  ),
  room_scores as (
    -- 2. Calculate similarity against room descriptions/facilities
    select
      r.hotel_id,
      1 - (r.embedding <=> query_embedding) as sim,
      r.name as room_name
    from rooms r
    join hotels h on r.hotel_id = h.id
    where r.embedding is not null
      and (filter_destination_id is null or h.destination_id = filter_destination_id)
  ),
  combined as (
    -- 3. Combine hotel matches and room matches
    select * from hotel_scores where sim > match_threshold
    union all
    select * from room_scores where sim > match_threshold
  ),
  aggregated as (
    -- 4. Group by hotel_id: take the HIGHEST score and collect matched room names!
    select
      hotel_id,
      max(sim) as max_sim,
      array_remove(array_agg(distinct room_name), null) as matched_rooms
    from combined
    group by hotel_id
  )
  -- 5. Return full hotel details sorted by the highest similarity score, filtered by
  --    price range where requested. A missing lowest_price is never excluded — same
  --    fail-open convention as the rest of the price-preference code (never punish a
  --    hotel for missing data we simply don't have).
  select
    h.id,
    h.name,
    h.description,
    h.star_rating,
    h.lowest_price,
    a.max_sim as similarity,
    a.matched_rooms as matched_room_names
  from aggregated a
  join hotels h on h.id = a.hotel_id
  where (filter_min_price is null or h.lowest_price is null or h.lowest_price >= filter_min_price)
    and (filter_max_price is null or h.lowest_price is null or h.lowest_price <= filter_max_price)
  order by a.max_sim desc
  limit match_count;
$$;

ALTER FUNCTION "public"."match_hotels_with_rooms"(
    "public"."vector", double precision, integer, "uuid", numeric, numeric
) OWNER TO "postgres";
