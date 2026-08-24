-- `rooms.max_occupancy_raw` is declared in database_schema.sql and written
-- by hotel_pipeline.py's ETL upsert, but at least one deployed database
-- never had it added (observed 42703 "column rooms.max_occupancy_raw does
-- not exist" from admin B5's GET /hotels/{hotel_id}/rooms). Additive,
-- idempotent -- safe to re-run.
ALTER TABLE rooms ADD COLUMN IF NOT EXISTS max_occupancy_raw VARCHAR(100);
