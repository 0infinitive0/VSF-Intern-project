import type { AuthError } from '@supabase/supabase-js'
import type { TFunction } from 'i18next'

/**
 * translate-auth-error.ts — maps Supabase's (English, unstyled) AuthError
 * messages to this app's i18n strings. Design requirement (§5 of the
 * Authentication Experience doc): never show a raw browser alert or an
 * untranslated backend string — inline, localized, in the form.
 *
 * Supabase does not give stable machine-readable error codes for every
 * case on the older GoTrue API this matches against (`error.message`,
 * English, exact-ish substrings) — falls back to the raw message so a
 * legitimate but unmapped error is still visible rather than swallowed.
 */
export function translateAuthError(error: AuthError, t: TFunction): string {
  const msg = error.message.toLowerCase()
  if (msg.includes('invalid login credentials')) return t('authErrCreds')
  if (msg.includes('email not confirmed')) return t('authErrEmailUnconfirmed')
  if (msg.includes('user already registered') || msg.includes('already registered')) {
    return t('authErrAlreadyRegistered')
  }
  if (msg.includes('password should be at least') || msg.includes('password is too short')) {
    return t('authErrShort')
  }
  if (msg.includes('unable to validate email') || msg.includes('invalid email')) {
    return t('authErrEmail')
  }
  if (msg.includes('rate limit') || msg.includes('too many requests')) {
    return t('authErrRateLimited')
  }
  return error.message
}
