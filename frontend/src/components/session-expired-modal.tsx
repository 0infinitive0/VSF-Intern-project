import { useTranslation } from 'react-i18next'
import { useAuth } from '../auth/auth-context'

/**
 * SessionExpiredModal — soft glass dialog for an UNEXPECTED session death
 * (design §13: never yank the user straight back to a login screen).
 * auth-context.tsx already tells apart "you signed out" and "an anonymous
 * session quietly died and was re-minted" from this — `sessionExpired` only
 * ever becomes true for the third case: a previously-real identified
 * session that expired mid-use.
 *
 * Deliberately does NOT unmount AppShell — this renders as a sibling overlay
 * (see App.tsx), so useChatSession()'s in-memory transcript/state survives
 * underneath it untouched. "Sign in again" hands off to the same AuthPanel
 * used everywhere else (App.tsx composes dismiss + reopen into
 * `onSignInAgain`) rather than duplicating a login form here.
 */
export default function SessionExpiredModal({ onSignInAgain }: { onSignInAgain: () => void }) {
  const { t } = useTranslation()
  const { sessionExpired } = useAuth()

  if (!sessionExpired) return null

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="session-expired-title"
      className="fixed inset-0 z-[60] flex items-center justify-center p-4"
      style={{ background: 'rgba(10,14,20,.28)', backdropFilter: 'blur(10px)', animation: 'vFade .35s ease both' }}
    >
      <div
        className="glass-panel w-full max-w-[380px] p-6.5 rounded-[26px] flex flex-col gap-2.5"
        style={{ animation: 'vRise .5s var(--ease-glide) both' }}
      >
        <div id="session-expired-title" className="text-[18.5px] font-semibold tracking-tight text-on-surface">
          {t('authSessionExpiredTitle')}
        </div>
        <div className="text-[13px] leading-relaxed text-on-surface-variant">
          {t('authSessionExpiredBody')}
        </div>
        <button
          type="button"
          onClick={onSignInAgain}
          className="h-[46px] mt-2 rounded-[15px] bg-button text-on-button text-[14px] font-semibold transition-transform duration-200 hover:-translate-y-px active:scale-[.985]"
        >
          {t('authSignIn')}
        </button>
      </div>
    </div>
  )
}
