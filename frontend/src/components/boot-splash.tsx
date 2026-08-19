import { useTranslation } from 'react-i18next'

/**
 * BootSplash — shown for the brief window between mount and AuthProvider
 * resolving a session (getSession(), then signInAnonymously() if none
 * existed). Doubles as the design brief's "brief launching transition"
 * (Design Update - Authentication Ex.md §8) — there is no separate
 * placeholder "workspace" in this real app the way the design prototype had
 * one, so this is that beat's entire on-screen presence.
 *
 * Also reused by App.tsx for the VNPay-return processing gate (a different
 * "brief launching transition": the session-bootstrap flash that would
 * otherwise show right after returning from a real payment) — `messageKey`
 * lets that call site swap the label without needing its own near-identical
 * component.
 */
export default function BootSplash({ messageKey = 'authBootLoading' }: { messageKey?: string }) {
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
          {t(messageKey)}
        </div>
      </div>
    </div>
  )
}
