/**
 * supabase-client.ts — the one Supabase client instance for the whole app.
 *
 * Talks ONLY to Supabase Auth (signInAnonymously, signInWithPassword,
 * signUp, signInWithOAuth, onAuthStateChange, ...). This app never queries
 * Supabase Postgres directly from the browser — trip/session data always
 * goes through the FastAPI backend (api/*-client.ts), which holds the
 * service-role key server-side. VITE_SUPABASE_ANON_KEY here is the public,
 * safe-to-bundle anon key (same two-token discipline this file's sibling,
 * VITE_MAPBOX_TOKEN, already documents in .env.example).
 */
import { createClient } from '@supabase/supabase-js'

const url = import.meta.env.VITE_SUPABASE_URL as string | undefined
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined

const configured = Boolean(url && anonKey)

if (!configured) {
  // Loud, not silent: every other env-driven feature in this app (Mapbox)
  // renders an honest "unavailable" state instead of guessing — auth can't
  // do that (it gates the whole app), so a clear console error is the
  // closest equivalent for a misconfigured deploy. createClient() itself
  // throws on an empty/malformed URL (unlike Mapbox's token, which just
  // renders inert) — a syntactically valid placeholder keeps module import
  // from crashing the entire app; every Auth call against it still fails
  // (network error against a host that doesn't exist), which is the same
  // "loudly broken, not silently wrong" outcome, just deferred to call time.
  // eslint-disable-next-line no-console
  console.error(
    'supabase-client: VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY are not set — auth will not work. See frontend/.env.example.',
  )
}

export const supabase = createClient(url || 'https://not-configured.invalid', anonKey || 'not-configured', {
  auth: {
    persistSession: true,
    autoRefreshToken: true,
    detectSessionInUrl: true,
  },
})
