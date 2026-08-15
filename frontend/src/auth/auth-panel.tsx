import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from './auth-context'
import { translateAuthError } from './translate-auth-error'
import { EMAIL_RE } from './email-pattern'
import LoginForm from './login-form'
import RegisterForm from './register-form'
import ForgotPasswordForm from './forgot-password-form'
import GoogleButton from './google-button'

type Screen = 'login' | 'register' | 'forgot' | 'sent'

/**
 * AuthPanel — the whole Login/Register/Forgot-password/Sent experience as
 * one glass overlay (design: "Authentication is a gateway into V-OTA, not a
 * standalone page" — never a full route, this app has no router). Reachable
 * from SidebarRail's "Sign in" affordance (anonymous) or the account menu
 * (already-identified, e.g. reopening to link a password to a Google-only
 * account — out of scope for now but the same panel would host it later).
 *
 * State machine mirrors the design prototype's (V-OTA Auth.dc.html) exactly,
 * reimplemented against real Supabase calls instead of a setTimeout mock —
 * see auth-context.tsx for the actual signInWithPassword/registerWithPassword/
 * signInWithGoogle/sendPasswordReset calls this dispatches to.
 */
export default function AuthPanel({
  open,
  onClose,
  initialError = '',
}: {
  open: boolean
  onClose: () => void
  /** Pre-filled error to show the moment the panel opens — e.g. an OAuth
   * redirect failure caught by App.tsx via consumeOAuthRedirectError()
   * before the user ever touched this panel's own form. */
  initialError?: string
}) {
  const { t } = useTranslation()
  const auth = useAuth()
  const [screen, setScreen] = useState<Screen>('login')
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const panelRef = useRef<HTMLDivElement>(null)

  // Fresh state every time the panel is (re)opened — a half-filled register
  // form from a previous visit should not resurface silently.
  useEffect(() => {
    if (!open) return
    setScreen('login')
    setName('')
    setEmail('')
    setPassword('')
    setConfirm('')
    setError(initialError)
    setLoading(false)
  }, [open, initialError])

  useEffect(() => {
    if (!open) return
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape' && !loading) onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [open, loading, onClose])

  if (!open) return null

  function goTo(next: Screen) {
    setScreen(next)
    setError('')
  }

  async function handleLogin() {
    if (!EMAIL_RE.test(email.trim())) return setError(t('authErrEmail'))
    if (password.length < 8) return setError(t('authErrShort'))
    setLoading(true)
    setError('')
    const { error: authError } = await auth.signInWithPassword(email.trim(), password)
    setLoading(false)
    if (authError) return setError(translateAuthError(authError, t))
    onClose()
  }

  async function handleRegister() {
    if (!name.trim()) return setError(t('authErrName'))
    if (!EMAIL_RE.test(email.trim())) return setError(t('authErrEmail'))
    if (password.length < 8) return setError(t('authErrShort'))
    if (password !== confirm) return setError(t('authErrMatch'))
    setLoading(true)
    setError('')
    const { error: authError } = await auth.registerWithPassword(name.trim(), email.trim(), password)
    setLoading(false)
    if (authError) return setError(translateAuthError(authError, t))
    onClose()
  }

  async function handleForgot() {
    if (!EMAIL_RE.test(email.trim())) return setError(t('authErrEmail'))
    setLoading(true)
    setError('')
    const { error: authError } = await auth.sendPasswordReset(email.trim())
    setLoading(false)
    if (authError) return setError(translateAuthError(authError, t))
    setScreen('sent')
  }

  async function handleGoogle() {
    setError('')
    const { error: authError } = await auth.signInWithGoogle()
    // Success navigates the browser away — nothing left to do here.
    if (authError) setError(translateAuthError(authError, t))
  }

  const isLogin = screen === 'login'
  const isRegister = screen === 'register'
  const isForgot = screen === 'forgot'
  const isSent = screen === 'sent'
  const showSocial = isLogin || isRegister
  const title = isLogin
    ? t('authLoginTitle')
    : isRegister
      ? t('authRegisterTitle')
      : isForgot
        ? t('authForgotTitle')
        : t('authSentTitle')
  const subtitle = isLogin
    ? t('authLoginSubtitle')
    : isRegister
      ? t('authRegisterSubtitle')
      : isForgot
        ? t('authForgotSubtitle')
        : t('authSentSubtitle')

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: 'rgba(10,14,20,.32)', backdropFilter: 'blur(8px)', animation: 'vFade .3s ease both' }}
      onClick={() => !loading && onClose()}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="auth-panel-title"
        className="glass-panel relative w-full max-w-[400px] p-6 rounded-[28px] overflow-hidden"
        style={{ animation: 'vRise .45s var(--ease-glide) both' }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex flex-col gap-1 mb-4.5">
          <div id="auth-panel-title" className="text-[21px] font-semibold tracking-tight text-on-surface">
            {title}
          </div>
          <div className="text-[13px] leading-relaxed text-on-surface-variant">{subtitle}</div>
        </div>

        {error && (
          <div
            role="alert"
            aria-live="assertive"
            className="flex gap-2 items-start px-3.5 py-2.5 mb-3.5 rounded-[14px]"
            style={{ background: 'var(--color-error-soft, rgba(192,94,112,.12))', border: '1px solid var(--color-error)' }}
          >
            <span className="w-1.5 h-1.5 rounded-full mt-1.5 shrink-0" style={{ background: 'var(--color-error)' }} />
            <span className="text-[12.5px] leading-relaxed text-on-surface">{error}</span>
          </div>
        )}

        {isLogin && (
          <LoginForm
            email={email}
            password={password}
            loading={loading}
            onEmailChange={setEmail}
            onPasswordChange={setPassword}
            onForgot={() => goTo('forgot')}
            onSubmit={handleLogin}
          />
        )}
        {isRegister && (
          <RegisterForm
            name={name}
            email={email}
            password={password}
            confirm={confirm}
            loading={loading}
            onNameChange={setName}
            onEmailChange={setEmail}
            onPasswordChange={setPassword}
            onConfirmChange={setConfirm}
            onSubmit={handleRegister}
          />
        )}
        {isForgot && (
          <ForgotPasswordForm
            email={email}
            loading={loading}
            onEmailChange={setEmail}
            onSubmit={handleForgot}
            onBackToLogin={() => goTo('login')}
          />
        )}
        {isSent && (
          <div className="flex flex-col gap-3.5">
            <div className="flex items-center gap-3 p-3.5 rounded-[18px] bg-glass-2 border" style={{ borderColor: 'var(--color-outline-variant)' }}>
              <div
                className="w-9 h-9 shrink-0 rounded-[13px] flex items-center justify-center text-[16px]"
                style={{ background: 'var(--color-success-soft, rgba(42,145,135,.16))', color: 'var(--color-success)' }}
              >
                ✦
              </div>
              <div className="text-[12.5px] leading-relaxed text-on-surface-variant">{t('authSentBody')}</div>
            </div>
            <button
              type="button"
              onClick={() => goTo('login')}
              className="h-11 rounded-[15px] border text-[14px] font-medium text-on-surface transition-colors hover:bg-glass-3"
              style={{ borderColor: 'var(--color-outline-variant)', background: 'var(--g2)' }}
            >
              {t('authBackToSignIn')}
            </button>
          </div>
        )}

        {showSocial && (
          <div className="flex flex-col gap-3 mt-4">
            <div className="flex items-center gap-2.5">
              <span className="flex-1 h-px bg-fill" />
              <span className="text-[11px] text-on-surface-muted">{t('authOr')}</span>
              <span className="flex-1 h-px bg-fill" />
            </div>
            <GoogleButton disabled={loading} onClick={handleGoogle} />
          </div>
        )}

        {(isLogin || isRegister) && (
          <div className="mt-4 pt-3.5 border-t flex items-center justify-center gap-1.5 text-[12.5px] text-on-surface-variant" style={{ borderColor: 'var(--color-line)' }}>
            {isLogin ? t('authNoAccount') : t('authHasAccount')}
            <button
              type="button"
              onClick={() => goTo(isLogin ? 'register' : 'login')}
              className="font-semibold text-primary hover:opacity-70 transition-opacity"
            >
              {isLogin ? t('authCreateAccountLink') : t('authSignInLink')}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
