import type { AuthError } from '@supabase/supabase-js'

/**
 * oauth-redirect-error.ts — some Google/OAuth failures only happen *after*
 * the consent redirect (e.g. linkIdentity-ing a Google account whose email
 * already belongs to a different, non-anonymous user — Supabase rejects the
 * merge). signInWithGoogle()'s own `await` in auth-context.tsx never sees
 * this: that call only reports errors from *starting* the redirect, and the
 * browser has already navigated away to Google and back by the time this
 * kind of failure is known. Supabase instead reports it by bouncing the
 * browser back with error/error_code/error_description in the URL — both
 * the query string and the hash, redundantly. App.tsx reads it once on
 * boot via this helper so AuthPanel can surface it like any other auth
 * error instead of it silently vanishing into a dead URL; the params are
 * then stripped so a refresh doesn't re-show it.
 */
export function consumeOAuthRedirectError(): AuthError | null {
  const query = new URLSearchParams(window.location.search)
  const hash = new URLSearchParams(window.location.hash.replace(/^#/, ''))
  const description = query.get('error_description') ?? hash.get('error_description')
  const code = query.get('error_code') ?? hash.get('error_code')
  if (!description && !code) return null

  window.history.replaceState({}, '', window.location.pathname)

  // Shaped like a real Supabase AuthError so translateAuthError's existing
  // (already-tested) message matching handles it with no separate mapping
  // to keep in sync — e.g. error_code=email_exists's description ("A user
  // with this email address has already been registered") matches the
  // same "already registered" check used for signUp's own error.
  return { name: 'AuthApiError', status: 400, message: description ?? code ?? 'Authentication failed.' } as AuthError
}

/**
 * True when a redirect-return error is specifically Supabase's
 * `identity_already_exists` case — linkIdentity refused to attach a Google
 * identity that already belongs to a different, pre-existing user. App.tsx's
 * boot effect uses this to tell that one case apart from every other OAuth
 * failure: instead of surfacing it as an error, it silently retries as a
 * plain sign-in (auth-context.tsx's retryGoogleSignIn) — from the visitor's
 * side, clicking "Continue with Google" for an account that already exists
 * should just log them in, not show a confusing "already linked" message.
 */
export function isIdentityAlreadyLinkedError(error: AuthError): boolean {
  return error.message.toLowerCase().includes('already linked to another user')
}
