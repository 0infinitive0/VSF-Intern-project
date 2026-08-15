import { useTranslation } from 'react-i18next'
import AuthTextField from './auth-text-field'
import PasswordStrengthMeter from './password-strength-meter'
import SubmitButton from './auth-submit-button'

export default function RegisterForm({
  name,
  email,
  password,
  confirm,
  loading,
  onNameChange,
  onEmailChange,
  onPasswordChange,
  onConfirmChange,
  onSubmit,
}: {
  name: string
  email: string
  password: string
  confirm: string
  loading: boolean
  onNameChange: (value: string) => void
  onEmailChange: (value: string) => void
  onPasswordChange: (value: string) => void
  onConfirmChange: (value: string) => void
  onSubmit: () => void
}) {
  const { t } = useTranslation()
  const pwToggle = {
    show: t('authShow'),
    hide: t('authHide'),
    showAria: t('authShowPassword'),
    hideAria: t('authHidePassword'),
  }

  return (
    <form
      className="flex flex-col gap-2.5"
      onSubmit={(e) => {
        e.preventDefault()
        onSubmit()
      }}
    >
      <AuthTextField
        label={t('authNameLabel')}
        type="text"
        autoComplete="name"
        placeholder={t('authNamePlaceholder')}
        required
        value={name}
        onChange={(e) => onNameChange(e.target.value)}
      />
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
        autoComplete="new-password"
        placeholder="••••••••"
        required
        value={password}
        onChange={(e) => onPasswordChange(e.target.value)}
        showToggleLabels={pwToggle}
      />
      {password.length > 0 && <PasswordStrengthMeter password={password} />}
      <AuthTextField
        label={t('authConfirmLabel')}
        type="password"
        autoComplete="new-password"
        placeholder="••••••••"
        required
        value={confirm}
        onChange={(e) => onConfirmChange(e.target.value)}
        showToggleLabels={pwToggle}
      />
      <SubmitButton loading={loading} label={t('authCreateAccount')} />
    </form>
  )
}
