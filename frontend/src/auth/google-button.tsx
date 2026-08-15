import { useTranslation } from 'react-i18next'

/**
 * google-button.tsx — "Continue with Google" (design: §23 of the
 * Authentication Experience doc). Redirects the browser away via
 * signInWithOAuth/linkIdentity (see auth-context.tsx) — there is nothing to
 * await here, so this only surfaces a synchronous kickoff error (e.g.
 * Supabase project has no Google provider configured yet).
 */
export default function GoogleButton({ disabled, onClick }: { disabled: boolean; onClick: () => void }) {
  const { t } = useTranslation()

  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className="h-11 rounded-[15px] border flex items-center justify-center gap-2.5 text-[13.5px] font-medium text-on-surface transition-[background-color,transform] duration-200 disabled:opacity-60 disabled:cursor-not-allowed hover:not-disabled:-translate-y-px"
      style={{ borderColor: 'var(--color-outline-variant)', background: 'var(--g2)' }}
    >
      <span
        aria-hidden
        className="w-[17px] h-[17px] rounded-full inline-block"
        style={{
          background:
            'conic-gradient(from -20deg, #EA4335, #FBBC05 90deg, #34A853 190deg, #4285F4 300deg, #EA4335)',
        }}
      />
      {t('authGoogleContinue')}
    </button>
  )
}
