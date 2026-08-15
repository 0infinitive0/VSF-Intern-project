import { useTranslation } from 'react-i18next'
import AuthTextField from './auth-text-field'
import SubmitButton from './auth-submit-button'

export default function LoginForm({
  email,
  password,
  loading,
  onEmailChange,
  onPasswordChange,
  onForgot,
  onSubmit,
}: {
  email: string
  password: string
  loading: boolean
  onEmailChange: (value: string) => void
  onPasswordChange: (value: string) => void
  onForgot: () => void
  onSubmit: () => void
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
      <AuthTextField
        label={t('authEmailLabel')}
        type="email"
        autoComplete="email"
        placeholder="you@vota.travel"
        required
        value={email}
        onChange={(e) => onEmailChange(e.target.value)}
      />
      <AuthTextField
        label={t('authPasswordLabel')}
        type="password"
        autoComplete="current-password"
        placeholder="••••••••"
        required
        value={password}
        onChange={(e) => onPasswordChange(e.target.value)}
        showToggleLabels={{
          show: t('authShow'),
          hide: t('authHide'),
          showAria: t('authShowPassword'),
          hideAria: t('authHidePassword'),
        }}
      />
      <div className="flex justify-end -mt-1">
        <button
          type="button"
          onClick={onForgot}
          className="text-[12.5px] font-medium text-primary hover:opacity-70 transition-opacity"
        >
          {t('authForgotPassword')}
        </button>
      </div>
      <SubmitButton loading={loading} label={t('authSignIn')} />
    </form>
  )
}
