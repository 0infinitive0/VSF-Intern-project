import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from './auth-context'
import { translateAuthError } from './translate-auth-error'
import { EMAIL_RE } from './email-pattern'
import { isValidPhone } from './phone-pattern'
import { getDisplayName } from './profile-display'
import AuthTextField from './auth-text-field'
import DateOfBirthField from './date-of-birth-field'
import PasswordStrengthMeter, { passwordStrength } from './password-strength-meter'
import UserAvatar from './user-avatar'

/**
 * ProfilePasswordModal — the account slot's "Profile & password" screen
 * (design: V-OTA Planner.dc.html's profile dialog, opened from UserMenu's
 * dropdown). Two independent sections/forms sharing one dialog, exactly like
 * the design: personal information (name/email/phone/city/date of birth,
 * saved via auth.updateProfile) and change password — each has its own
 * submit button and its own inline status message, so saving one never
 * touches the other's state.
 *
 * The password section forks on `hasPassword`: a Google-only account (no
 * 'email' entry in user.app_metadata.providers) has no password to verify,
 * so it gets a "set a password" form calling auth.setInitialPassword
 * instead of the current/new/confirm form calling auth.updatePassword.
 *
 * Only reachable for a signed-in, non-anonymous user (UserMenu gates the
 * menu item that opens this), so `useAuth().user` is assumed non-null here.
 *
 * Rendered by UserMenu through a portal to document.body rather than in
 * place: SidebarRail's <aside> carries the glass-panel utility, and
 * `backdrop-filter` (like `transform`/`filter`) makes an element the
 * containing block for `position: fixed` descendants — nested here, this
 * dialog would be clipped to the 252px-wide rail instead of covering the
 * viewport.
 *
 * Open/close is a two-phase transition (design: openProfile/closeProfile,
 * V-OTA Planner.dc.html:2021-2032) rather than the one-shot vFade/vRise
 * AuthPanel/SessionExpiredModal use — this modal is reopened repeatedly
 * within the same session (unlike those two, which gate a page-load-once
 * flow), so a closing transition matters more here. `visible` starts false,
 * flips true a frame later (mount-then-transition, not a keyframe) so the
 * backdrop/card fade+scale in; closing reverses that and only calls the
 * real `onClose` (which unmounts this component) after the transition
 * finishes, matching the design's 380ms.
 */
const CLOSE_TRANSITION_MS = 380

export default function ProfilePasswordModal({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation()
  const auth = useAuth()
  const user = auth.user!
  const dialogRef = useRef<HTMLDivElement>(null)

  const [visible, setVisible] = useState(false)
  const closeTimerRef = useRef<ReturnType<typeof setTimeout>>(undefined)

  useEffect(() => {
    let raf2 = 0
    const raf1 = requestAnimationFrame(() => {
      raf2 = requestAnimationFrame(() => setVisible(true))
    })
    return () => {
      cancelAnimationFrame(raf1)
      cancelAnimationFrame(raf2)
    }
  }, [])

  const handleClose = useCallback(() => {
    setVisible(false)
    clearTimeout(closeTimerRef.current)
    closeTimerRef.current = setTimeout(onClose, CLOSE_TRANSITION_MS)
  }, [onClose])

  useEffect(() => () => clearTimeout(closeTimerRef.current), [])

  const [fullName, setFullName] = useState((user.user_metadata?.full_name as string | undefined) ?? '')
  const [email, setEmail] = useState(user.email ?? '')
  const [phone, setPhone] = useState((user.user_metadata?.phone as string | undefined) ?? '')
  const [city, setCity] = useState((user.user_metadata?.city as string | undefined) ?? '')
  const [dateOfBirth, setDateOfBirth] = useState((user.user_metadata?.date_of_birth as string | undefined) ?? '')
  const [profileSaving, setProfileSaving] = useState(false)
  const [profileError, setProfileError] = useState('')
  const [profileSaved, setProfileSaved] = useState(false)
  const savedTimerRef = useRef<ReturnType<typeof setTimeout>>(undefined)

  const [pwCurrent, setPwCurrent] = useState('')
  const [pwNew, setPwNew] = useState('')
  const [pwConfirm, setPwConfirm] = useState('')
  const [pwSaving, setPwSaving] = useState(false)
  const [pwMsg, setPwMsg] = useState('')
  const [pwOk, setPwOk] = useState(false)

  useEffect(() => () => clearTimeout(savedTimerRef.current), [])

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') handleClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [handleClose])

  const displayName = getDisplayName(user, t)
  const memberSinceYear = new Date(user.created_at).getFullYear()
  const verified = Boolean(user.email_confirmed_at)
  // Google-only accounts have no 'email' entry among their linked providers
  // — there's no password to verify before setting a new one (see the
  // module doc comment and auth-context.tsx's setInitialPassword).
  const hasPassword = Boolean(user.app_metadata?.providers?.includes('email'))
  const pwToggle = {
    show: t('authShow'),
    hide: t('authHide'),
    showAria: t('authShowPassword'),
    hideAria: t('authHidePassword'),
  }

  async function handleSaveProfile() {
    const trimmedEmail = email.trim()
    const trimmedPhone = phone.trim()
    if (!EMAIL_RE.test(trimmedEmail)) {
      setProfileError(t('authErrEmail'))
      return
    }
    if (trimmedPhone && !isValidPhone(trimmedPhone)) {
      setProfileError(t('authErrPhone'))
      return
    }
    setProfileSaving(true)
    setProfileError('')
    const { error } = await auth.updateProfile({
      fullName: fullName.trim(),
      email: trimmedEmail,
      phone: trimmedPhone,
      city: city.trim(),
      dateOfBirth,
    })
    setProfileSaving(false)
    if (error) {
      setProfileError(translateAuthError(error, t))
      return
    }
    setProfileSaved(true)
    clearTimeout(savedTimerRef.current)
    savedTimerRef.current = setTimeout(() => setProfileSaved(false), 2600)
  }

  function pwFail(msg: string) {
    setPwOk(false)
    setPwMsg(msg)
  }

  async function handleChangePassword() {
    if (hasPassword && !pwCurrent) return pwFail(t('authErrCurrentPasswordRequired'))
    if (pwNew.length < 8) return pwFail(t('authErrShort'))
    if (passwordStrength(pwNew).score < 3) return pwFail(t('authErrWeakPassword'))
    if (pwNew !== pwConfirm) return pwFail(t('authErrMatch'))
    setPwSaving(true)
    setPwMsg('')
    const { error, wrongCurrent } = hasPassword
      ? await auth.updatePassword(pwCurrent, pwNew)
      : await auth.setInitialPassword(pwNew)
    setPwSaving(false)
    if (error) {
      setPwOk(false)
      setPwMsg(wrongCurrent ? t('authErrCurrentPasswordWrong') : translateAuthError(error, t))
      return
    }
    setPwOk(true)
    setPwCurrent('')
    setPwNew('')
    setPwConfirm('')
    setPwMsg(hasPassword ? t('authPasswordUpdated') : t('authPasswordSet'))
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto p-5 py-6.5"
      style={{
        background: 'rgba(12,18,30,.34)',
        backdropFilter: 'blur(10px)',
        opacity: visible ? 1 : 0,
        transition: 'opacity .34s ease',
      }}
      onClick={handleClose}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="profile-modal-title"
        className="glass-panel relative w-full max-w-[940px] rounded-[28px]"
        style={{
          opacity: visible ? 1 : 0,
          transform: visible ? 'none' : 'translateY(16px) scale(.975)',
          transition: 'opacity .38s cubic-bezier(.22,1,.36,1), transform .44s cubic-bezier(.22,1,.36,1)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <header className="relative flex items-center gap-3.5 px-6 py-5.5 border-b" style={{ borderColor: 'var(--color-line)' }}>
          <UserAvatar
            user={user}
            displayName={displayName}
            className="w-[54px] h-[54px] shrink-0 rounded-[19px] text-[19px]"
            fallbackStyle={{
              background: 'linear-gradient(145deg,#7FA8F2,#3A73DE)',
              boxShadow: '0 14px 30px -14px rgba(44,95,201,.7)',
            }}
          />
          <div className="flex-1 min-w-0">
            <nav aria-label="Breadcrumb" className="text-[10px] font-semibold tracking-widest uppercase text-on-surface-muted mb-1">
              V‑OTA · {t('authProfileCrumb')}
            </nav>
            <h1 id="profile-modal-title" className="m-0 text-[20px] font-semibold tracking-tight text-on-surface truncate">
              {displayName}
            </h1>
            <p className="mt-0.5 text-[12.5px] text-on-surface-muted truncate">
              {user.email} · {t('authProfileMember', { year: memberSinceYear })}
            </p>
          </div>
          {verified && (
            <span
              className="hidden sm:flex shrink-0 items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-medium"
              style={{ background: 'var(--color-success-soft, rgba(42,145,135,.14))', color: 'var(--color-success)' }}
            >
              ✓ {t('authProfileVerified')}
            </span>
          )}
          <button
            type="button"
            onClick={handleClose}
            aria-label={t('authProfileCloseLabel')}
            className="shrink-0 w-[34px] h-[34px] rounded-full border border-edge text-on-surface-variant text-[13px] cursor-pointer transition-transform duration-200 hover:scale-[1.08] active:scale-[0.92]"
            style={{ background: 'var(--g3)' }}
          >
            ✕
          </button>
        </header>

        <div className="grid gap-4 p-6" style={{ gridTemplateColumns: 'repeat(auto-fit,minmax(320px,1fr))' }}>
          <section aria-labelledby="pf-info" className="glass-card flex flex-col gap-3 p-4.5">
            <div>
              <h2 id="pf-info" className="m-0 text-[14.5px] font-semibold tracking-tight text-on-surface">
                {t('authProfileInfoTitle')}
              </h2>
              <p className="mt-1 text-[11.5px] leading-relaxed text-on-surface-muted">{t('authProfileInfoSub')}</p>
            </div>

            <AuthTextField
              label={t('authNameLabel')}
              type="text"
              dense
              autoComplete="name"
              placeholder={t('authNamePlaceholder')}
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
            />
            <AuthTextField
              label={t('authEmailLabel')}
              type="email"
              dense
              autoComplete="email"
              placeholder="you@vota.travel"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
            <AuthTextField
              label={t('authPhoneLabel')}
              type="tel"
              dense
              autoComplete="tel"
              placeholder={t('authPhonePlaceholder')}
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
            />
            <DateOfBirthField value={dateOfBirth} onChange={setDateOfBirth} />
            <AuthTextField
              label={t('authCityLabel')}
              type="text"
              dense
              autoComplete="address-level2"
              placeholder={t('authCityPlaceholder')}
              value={city}
              onChange={(e) => setCity(e.target.value)}
            />

            {profileError && (
              <div role="alert" aria-live="assertive" className="text-[11.5px] leading-relaxed" style={{ color: 'var(--color-error)' }}>
                {profileError}
              </div>
            )}

            <div className="flex items-center gap-2.5 mt-auto pt-1">
              <button
                type="button"
                onClick={handleSaveProfile}
                disabled={profileSaving}
                className="h-[42px] px-4.5 rounded-[14px] bg-button text-on-button text-[13px] font-semibold tracking-tight transition-transform duration-200 disabled:cursor-progress disabled:opacity-80 active:not-disabled:scale-[.97]"
              >
                {t('authProfileSave')}
              </button>
              <span
                aria-live="polite"
                className="text-[11.5px] font-medium transition-opacity duration-300"
                style={{ color: 'var(--color-success)', opacity: profileSaved ? 1 : 0 }}
              >
                {t('authProfileSaved')}
              </span>
            </div>
          </section>

          <section aria-labelledby="pf-pw" className="glass-card flex flex-col gap-3 p-4.5">
            <div>
              <h2 id="pf-pw" className="m-0 text-[14.5px] font-semibold tracking-tight text-on-surface">
                {hasPassword ? t('authChangePasswordTitle') : t('authSetPasswordTitle')}
              </h2>
              <p className="mt-1 text-[11.5px] leading-relaxed text-on-surface-muted">
                {hasPassword ? t('authChangePasswordSub') : t('authSetPasswordSub')}
              </p>
            </div>

            {hasPassword && (
              <AuthTextField
                label={t('authCurrentPasswordLabel')}
                type="password"
                dense
                autoComplete="current-password"
                placeholder="••••••••"
                value={pwCurrent}
                onChange={(e) => {
                  setPwCurrent(e.target.value)
                  setPwMsg('')
                }}
                showToggleLabels={pwToggle}
              />
            )}
            <AuthTextField
              label={t('authNewPasswordLabel')}
              type="password"
              dense
              autoComplete="new-password"
              placeholder="••••••••"
              value={pwNew}
              onChange={(e) => {
                setPwNew(e.target.value)
                setPwMsg('')
              }}
              showToggleLabels={pwToggle}
            />
            {pwNew.length > 0 && <PasswordStrengthMeter password={pwNew} />}
            <AuthTextField
              label={t('authConfirmNewPasswordLabel')}
              type="password"
              dense
              autoComplete="new-password"
              placeholder="••••••••"
              value={pwConfirm}
              onChange={(e) => {
                setPwConfirm(e.target.value)
                setPwMsg('')
              }}
              showToggleLabels={pwToggle}
            />

            <div className="flex items-center gap-2.5 mt-auto pt-1">
              <button
                type="button"
                onClick={handleChangePassword}
                disabled={pwSaving}
                className="h-[42px] px-4.5 rounded-[14px] border border-outline-variant bg-glass-3 text-on-surface text-[13px] font-semibold transition-transform duration-200 disabled:cursor-progress disabled:opacity-80 hover:not-disabled:bg-glass-2 active:not-disabled:scale-[.97]"
              >
                {hasPassword ? t('authUpdatePassword') : t('authSetPassword')}
              </button>
              {pwMsg && (
                <span
                  aria-live="polite"
                  className="flex-1 min-w-0 text-[11.5px] leading-relaxed font-medium"
                  style={{ color: pwOk ? 'var(--color-success)' : 'var(--color-error)' }}
                >
                  {pwMsg}
                </span>
              )}
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}
