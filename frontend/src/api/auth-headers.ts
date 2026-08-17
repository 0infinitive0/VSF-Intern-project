/**
 * auth-headers.ts — the one place every api/*-client.ts fetch wrapper gets
 * its bearer token from. Reads straight from the Supabase SDK's own cached
 * session (supabase.auth.getSession(), a fast local read that only hits the
 * network when a refresh is actually due) rather than a separately
 * maintained global variable, so it's always current after a background
 * token refresh with no synchronization code of its own.
 *
 * Every visitor has a token by the time any fetch call can happen — App.tsx
 * gates mounting the chat UI on AuthProvider's boot resolving first (see
 * auth/auth-context.tsx) — so an empty object here should not happen in
 * practice; the console warning exists so a future regression in that
 * gating fails loudly instead of silently sending unauthenticated requests.
 */
import { supabase } from '../lib/supabase-client'

export async function authHeaders(): Promise<Record<string, string>> {
  const {
    data: { session },
  } = await supabase.auth.getSession()
  if (!session?.access_token) {
    // eslint-disable-next-line no-console
    console.warn('auth-headers: no Supabase session yet — request will go out unauthenticated')
    return {}
  }
  return { Authorization: `Bearer ${session.access_token}` }
}
