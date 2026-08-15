-- Adds per-user ownership to `sessions`, the missing piece that let
-- GET /api/v1/chat/sessions return every visitor's sessions with no filtering
-- (plan 260814-supabase-auth-and-per-user-history). Nullable, not backfilled:
-- SESSION_PERSISTENCE_ENABLED is off in every environment as of this migration,
-- so there is no real row population to reconcile — every session created after
-- the backend's auth dependency ships will always carry a user_id (anonymous
-- Supabase users included; every visitor gets a real auth.users row).
--
-- Deliberately does NOT touch `persist_session_checkpoint` (the RPC
-- src/services/session_store.py calls first, falling back to a plain table
-- upsert only on PGRST202). That function's defining migration
-- (20260811_add_session_checkpoint_persistence.sql, referenced by
-- backend/tests/test_session_store.py) is not present in this repo — a
-- pre-existing gap, not something this migration should guess at reconstructing.
-- session_store.upsert() instead stamps user_id with a small separate update
-- after either path succeeds, independent of what that RPC's live body does.
--
-- Safe to apply to an existing Supabase project more than once.

ALTER TABLE sessions
  ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE;

COMMENT ON COLUMN sessions.user_id IS
'Owner of this session — a real auth.users row for every visitor, anonymous or '
'permanent (Supabase Anonymous Auth). Nullable only for rows created before this '
'migration or outside the HTTP API (e.g. the CLI), which carry no owner concept.';

-- Matches the exact access pattern GET /api/v1/chat/sessions needs: "this
-- caller's rows, newest first" (session_store.list_sessions() already orders
-- by updated_at desc).
CREATE INDEX IF NOT EXISTS idx_sessions_user_id_updated_at
  ON sessions (user_id, updated_at DESC);

-- Defense-in-depth only, NOT applied by default (see below): the assumption
-- was that the backend's Supabase client always uses a service-role key,
-- which bypasses RLS by design, so enabling this would cost nothing. That
-- assumption wasn't actually verified against this project's real
-- SUPABASE_SERVICE_KEY. If that key turns out to be a client-safe/publishable
-- key rather than a true service-role/secret key, enabling RLS here would
-- silently break every direct table read/write in session_store.py — writes
-- rejected by WITH CHECK, reads returning zero rows — with no error, since
-- the backend never runs as an `authenticated` role that satisfies
-- `auth.uid() = user_id`. Left commented out until that's confirmed; the
-- real enforcement doesn't depend on it either way — it's
-- backend/src/auth's get_current_user + _owned_session_or_404 in routes.py,
-- entirely at the application layer, unaffected by whether this runs.
--
-- ALTER TABLE sessions ENABLE ROW LEVEL SECURITY;
--
-- DROP POLICY IF EXISTS "Users manage their own sessions" ON sessions;
-- CREATE POLICY "Users manage their own sessions"
--   ON sessions
--   FOR ALL
--   TO authenticated
--   USING (auth.uid() = user_id)
--   WITH CHECK (auth.uid() = user_id);
