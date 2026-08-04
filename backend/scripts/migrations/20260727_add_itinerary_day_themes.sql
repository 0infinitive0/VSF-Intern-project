-- Store deterministic day themes with each itinerary.
-- Safe to apply to an existing Supabase project more than once.
ALTER TABLE itineraries
ADD COLUMN IF NOT EXISTS day_themes JSONB NOT NULL DEFAULT '[]'::jsonb;

COMMENT ON COLUMN itineraries.day_themes IS
'Daily themes serialized as [{day_number, title, query}].';
