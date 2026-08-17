-- match_attractions' distance filter has always evaluated to false whenever a caller
-- supplied root_latitude/root_longitude/max_radius_km together: the coordinate-format
-- guard regex was written with doubled backslashes ('^\\s*-?\\d+...') inside a plain
-- '...' string literal. Postgres does not unescape backslashes in a plain literal
-- (standard_conforming_strings has been on by default since 9.1), so the value the
-- regex engine actually receives contains two literal backslash characters before
-- each 's'/'d', not the \s/\d character classes it was meant to express. That pattern
-- cannot match any real "lat,lon" string (e.g. "16.4583925,107.5815424"), so
-- attraction_latitude/attraction_longitude were NULL for every row, unconditionally --
-- which made the final "(... AND attraction_latitude IS NOT NULL AND ...)" branch
-- false for every row whenever a radius filter was actually requested, regardless of
-- true distance. The haversine formula itself, the NULL-guard OR-chain, and every
-- other clause were already correct; only the regex needed the extra backslashes
-- removed. Safe to apply to an existing Supabase project more than once (CREATE OR
-- REPLACE) -- the signature is unchanged from the live function, so this replaces it
-- in place rather than creating a new overload.
CREATE OR REPLACE FUNCTION "public"."match_attractions"(
    "query_embedding" "public"."vector",
    "match_threshold" double precision DEFAULT 0.3,
    "match_count" integer DEFAULT 10,
    "filter_destination_id" "uuid" DEFAULT NULL::"uuid",
    "filter_category" "text" DEFAULT NULL::"text",
    "root_latitude" double precision DEFAULT NULL::double precision,
    "root_longitude" double precision DEFAULT NULL::double precision,
    "max_radius_km" double precision DEFAULT NULL::double precision,
    "filter_exclude_attraction_ids" "uuid"[] DEFAULT ARRAY[]::"uuid"[]
) RETURNS TABLE(
    "id" "uuid",
    "name" "text",
    "description" "text",
    "category" "text",
    "similarity" double precision
)
    LANGUAGE "sql" STABLE
    AS $$
    WITH attraction_scores AS MATERIALIZED (
        SELECT a.id, a.name, a.description, a.category,
            1 - (a.embedding <=> query_embedding) AS similarity,
            CASE WHEN a.coordinates ~ '^\s*-?\d+(\.\d+)?\s*,\s*-?\d+(\.\d+)?\s*$'
                THEN split_part(a.coordinates, ',', 1)::double precision END AS attraction_latitude,
            CASE WHEN a.coordinates ~ '^\s*-?\d+(\.\d+)?\s*,\s*-?\d+(\.\d+)?\s*$'
                THEN split_part(a.coordinates, ',', 2)::double precision END AS attraction_longitude
        FROM public.attractions AS a
        WHERE a.embedding IS NOT NULL
          AND (filter_destination_id IS NULL OR a.destination_id = filter_destination_id)
          AND (filter_category IS NULL OR a.category = filter_category)
          AND (cardinality(filter_exclude_attraction_ids) = 0
               OR NOT (a.id = ANY(filter_exclude_attraction_ids)))
    )
    SELECT attraction_scores.id, attraction_scores.name, attraction_scores.description,
           attraction_scores.category, attraction_scores.similarity
    FROM attraction_scores
    WHERE attraction_scores.similarity > match_threshold
      AND (root_latitude IS NULL OR root_longitude IS NULL OR max_radius_km IS NULL
           OR (attraction_scores.attraction_latitude IS NOT NULL
               AND attraction_scores.attraction_longitude IS NOT NULL
               AND 6371.0 * 2.0 * ASIN(SQRT(
                     POWER(SIN(RADIANS(attraction_scores.attraction_latitude - root_latitude) / 2.0), 2.0)
                     + COS(RADIANS(root_latitude)) * COS(RADIANS(attraction_scores.attraction_latitude))
                     * POWER(SIN(RADIANS(attraction_scores.attraction_longitude - root_longitude) / 2.0), 2.0)
               )) <= max_radius_km))
    ORDER BY attraction_scores.similarity DESC
    LIMIT match_count;
$$;

ALTER FUNCTION "public"."match_attractions"(
    "public"."vector", double precision, integer, "uuid", "text",
    double precision, double precision, double precision, "uuid"[]
) OWNER TO "postgres";
