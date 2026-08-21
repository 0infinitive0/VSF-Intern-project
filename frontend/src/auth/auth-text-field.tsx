import { useId, useState, type InputHTMLAttributes } from 'react'

/**
 * auth-text-field.tsx — shared label+input shell for every Auth panel field
 * (email, password, name, confirm password). Password fields get a
 * show/hide toggle (design §3/§21: "Show / Hide Password"). Kept to one
 * component so every field shares identical focus/glass styling instead of
 * four hand-copied markup blocks.
 */
export default function AuthTextField({
  label,
  type = 'text',
  dense = false,
  showToggleLabels,
  error,
  ...inputProps
}: {
  label: string
  type?: 'text' | 'email' | 'password' | 'tel'
  /** 40px instead of the default 44px — ProfilePasswordModal's fields (design:
   * VP-OTA Planner.dc.html's profile dialog uses `height:40px`, shorter than
   * the 44px login/register/forgot-password screens use). Everywhere else
   * this defaults to false, unchanged. */
  dense?: boolean
  /** Present only for password fields — {show, hide} button text/aria-labels. */
  showToggleLabels?: { show: string; hide: string; showAria: string; hideAria: string }
  /** Field-specific validation message shown right under the input, with its
   * border tinted to match — lets a caller with several fields (e.g.
   * booking-modal.tsx's guest step) point at exactly which one needs fixing
   * instead of one blanket "something's wrong" line under the whole form. */
  error?: string
} & Omit<InputHTMLAttributes<HTMLInputElement>, 'type'>) {
  const id = useId()
  const errorId = useId()
  const [revealed, setRevealed] = useState(false)
  const isPassword = type === 'password'
  const resolvedType = isPassword ? (revealed ? 'text' : 'password') : type

  return (
    <label htmlFor={id} className="flex flex-col gap-1.5">
      <span className="text-[10.5px] font-semibold tracking-wide uppercase text-on-surface-muted">
        {label}
      </span>
      <span className="relative block">
        <input
          id={id}
          type={resolvedType}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? errorId : undefined}
          {...inputProps}
          className={`${dense ? 'h-10' : 'h-11'} w-full rounded-[14px] border bg-glass-2 px-3.5 text-[14px] text-on-surface outline-none transition-[box-shadow,background-color,border-color] duration-200 placeholder:text-on-surface-faint focus:border-primary focus:bg-glass-3 focus:shadow-[0_0_0_4px_var(--color-primary-soft)] ${
            isPassword ? 'pr-[74px]' : ''
          } ${inputProps.className ?? ''}`}
          style={error ? { ...inputProps.style, borderColor: 'var(--err)' } : inputProps.style}
        />
        {isPassword && showToggleLabels && (
          <button
            type="button"
            onClick={() => setRevealed((r) => !r)}
            aria-label={revealed ? showToggleLabels.hideAria : showToggleLabels.showAria}
            className="absolute right-1.5 top-1/2 -translate-y-1/2 h-8 rounded-[10px] border px-2.5 text-[10.5px] font-semibold tracking-wide transition-colors hover:bg-fill2"
            style={{ borderColor: 'var(--color-outline-variant)', background: 'var(--color-fill)' }}
          >
            {revealed ? showToggleLabels.hide : showToggleLabels.show}
          </button>
        )}
      </span>
      {error && (
        <span id={errorId} role="alert" className="text-[11.5px] font-medium" style={{ color: 'var(--err)' }}>
          {error}
        </span>
      )}
    </label>
  )
}
