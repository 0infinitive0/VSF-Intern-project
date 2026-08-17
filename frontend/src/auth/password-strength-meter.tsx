import { useTranslation } from 'react-i18next'

/**
 * password-strength-meter.tsx — same heuristic as the design prototype
 * (V-OTA Auth.dc.html's `renderVals()`): length >= 8, has both cases, has a
 * digit, has a symbol — each present bumps the score by one, capped into
 * three bands. Purely a hint, never a submit gate (the real minimum-length
 * validation lives in register-form.tsx).
 */
export function passwordStrength(password: string): { score: 0 | 1 | 2 | 3; ratio: number } {
  if (!password) return { score: 0, ratio: 0 }
  let score = 0
  if (password.length >= 8) score++
  if (/[a-z]/.test(password) && /[A-Z]/.test(password)) score++
  if (/\d/.test(password)) score++
  if (/[^A-Za-z0-9]/.test(password)) score++
  const band = score <= 1 ? 1 : score <= 2 ? 2 : 3
  return { score: band, ratio: band === 1 ? 0.28 : band === 2 ? 0.62 : 1 }
}

export default function PasswordStrengthMeter({ password }: { password: string }) {
  const { t } = useTranslation()
  const { score, ratio } = passwordStrength(password)
  const label =
    score === 1 ? t('authStrengthWeak') : score === 2 ? t('authStrengthFair') : t('authStrengthStrong')
  const color =
    score === 1 ? 'var(--color-error)' : score === 2 ? 'var(--color-warning)' : 'var(--color-success)'

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between">
        <span className="text-[10.5px] font-semibold tracking-wide uppercase text-on-surface-muted">
          {t('authStrengthLabel')}
        </span>
        <span className="text-[11px] font-medium" style={{ color }}>
          {label}
        </span>
      </div>
      <div className="h-1 rounded-full overflow-hidden bg-fill">
        <div
          className="h-full rounded-full transition-[width,background-color] duration-300 ease-out"
          style={{ width: `${ratio * 100}%`, background: color }}
        />
      </div>
    </div>
  )
}
