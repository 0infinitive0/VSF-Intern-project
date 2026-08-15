/**
 * session-expired-bus.ts — tells AuthProvider "the token just failed" from
 * places that aren't React (the plain-module fetch wrappers in
 * api/*-client.ts). A 401 there means either Supabase's own silent refresh
 * has already failed (in which case onAuthStateChange in auth-context.tsx
 * will also fire SIGNED_OUT around the same time) or the backend rejected a
 * token Supabase still considers valid (clock skew, a revoked session) —
 * either way the UI reaction is identical, so both paths funnel into the
 * same sessionExpired state via this bus and auth-context's own listener.
 *
 * A plain EventTarget, not a React Context, precisely because the callers
 * (auth-headers.ts, and anything using it) run outside any component tree.
 */
const bus = new EventTarget()
const SESSION_EXPIRED = 'session-expired'

export function reportSessionExpired() {
  bus.dispatchEvent(new Event(SESSION_EXPIRED))
}

export function onSessionExpired(listener: () => void): () => void {
  bus.addEventListener(SESSION_EXPIRED, listener)
  return () => bus.removeEventListener(SESSION_EXPIRED, listener)
}
