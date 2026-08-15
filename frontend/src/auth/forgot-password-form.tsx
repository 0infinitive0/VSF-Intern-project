import { useTranslation } from 'react-i18next'
import AuthTextField from './auth-text-field'
import SubmitButton from './auth-submit-button'

export default function ForgotPasswordForm({
  email,
  loading,
  onEmailChange,
  onSubmit,
  onBackToLogin,
}: {
  email: string
  loading: boolean
  onEmailChange: (value: string) => void
  onSubmit: () => void
  onBackToLogin: () => void
}) {
  const { t } = useTranslation()

  return (
    <form
      className="flex flex-col gap-2.5"
      onSubmit={(e) => {
        e.preventDefault()
        onSubmit()
      }}
    >
      <p className="text-[12.5px] leading-relaxed text-on-surface-variant -mt-1 mb-0.5">
        {t('authForgotBody')}
      </p>
      <AuthTextField
        label={t('authEmailLabel')}
        type="email"
        autoComplete="email"
        placeholder="you@vota.travel"
        required
        value={email}
        onChange={(e) => onEmailChange(e.target.value)}
      />
      <SubmitButton loading={loading} label={t('authSendResetLink')} />
      <button
        type="button"
        onClick={onBackToLogin}
        className="mt-1 text-[12.5px] font-medium text-on-surface-variant hover:text-on-surface transition-colors self-center"
      >
        ← {t('authBackToSignIn')}
      </button>
    </form>
  )
}
