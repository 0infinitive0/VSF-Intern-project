import { useTranslation } from 'react-i18next'

/**
 * BootSplash — shown for the brief window between mount and AuthProvider
 * resolving a session (getSession(), then signInAnonymously() if none
 * existed). Doubles as the design brief's "brief launching transition"
 * (Design Update - Authentication Ex.md §8) — there is no separate
 * placeholder "workspace" in this real app the way the design prototype had
 * one, so this is that beat's entire on-screen presence.
 */
export default function BootSplash() {
  const { t } = useTranslation()

  return (
    <div
      className="fixed inset-0 flex items-center justify-center"
      style={{ background: 'var(--page)' }}
    >
      <div
        className="glass-panel flex flex-col items-center gap-3.5 px-9 py-7 rounded-[24px]"
        style={{ animation: 'vFade .5s ease both' }}
      >
        <div
          className="w-7 h-7 rounded-full border-2"
          style={{
            borderColor: 'var(--color-outline-variant)',
            borderTopColor: 'var(--color-primary)',
            animation: 'vSpin .8s linear infinite',
          }}
        />
        <div className="text-[13.5px] font-medium text-on-surface tracking-tight">
          {t('authBootLoading')}
        </div>
      </div>
    </div>
  )
}
