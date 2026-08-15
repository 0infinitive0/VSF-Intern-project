import type { User } from '@supabase/supabase-js'
import type { TFunction } from 'i18next'

/**
 * profile-display.ts — shared display-name/initial derivation for an
 * authenticated user. Used by both user-menu.tsx (account button + dropdown)
 * and profile-password-modal.tsx (modal header) so the two surfaces never
 * disagree on what name/initial represents "this account".
 */
export function getDisplayName(user: User, t: TFunction): string {
  return (user.user_metadata?.full_name as string | undefined) || user.email || t('authAccountFallback')
}

export function getInitial(displayName: string): string {
  return displayName.trim().charAt(0).toUpperCase() || 'V'
}
