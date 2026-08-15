import type { User } from '@supabase/supabase-js'
import type { TFunction } from 'i18next'

/**
 * profile-display.ts — shared display-name/initial/avatar derivation for an
 * authenticated user. Used by both user-menu.tsx (account button + dropdown)
 * and profile-password-modal.tsx (modal header) so the two surfaces never
 * disagree on what name/initial/avatar represents "this account".
 */
export function getDisplayName(user: User, t: TFunction): string {
  return (user.user_metadata?.full_name as string | undefined) || user.email || t('authAccountFallback')
}

export function getInitial(displayName: string): string {
  return displayName.trim().charAt(0).toUpperCase() || 'V'
}

/** Google populates both `avatar_url` and `picture` in user_metadata
 * (confirmed against this project's real Google-linked accounts); email/
 * password accounts have neither, so this — and therefore UserAvatar's
 * fallback to the initial-letter circle — is the only signal needed to
 * tell the two cases apart. */
export function getAvatarUrl(user: User): string | undefined {
  return (
    (user.user_metadata?.avatar_url as string | undefined) ||
    (user.user_metadata?.picture as string | undefined) ||
    undefined
  )
}
