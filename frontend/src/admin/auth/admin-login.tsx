import { useState, type FormEvent } from 'react'
import { useAuth } from '../../auth/auth-context'
import { Button } from '../ui/button'
import { Input } from '../ui/input'

/** Vietnamese-only mapping (no i18next in this bundle -- see admin.html's
 * module docstring in phase-03-admin-shell-frontend.md's risk table). */
function describeLoginError(message: string): string {
  const msg = message.toLowerCase()
  if (msg.includes('invalid login credentials')) return 'Email hoặc mật khẩu không đúng.'
  if (msg.includes('rate limit') || msg.includes('too many requests')) {
    return 'Thử lại quá nhiều lần. Vui lòng chờ một lát.'
  }
  return message
}

export function AdminLogin() {
  const { signInWithPassword } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setError('')
    setSubmitting(true)
    const { error: authError } = await signInWithPassword(email, password)
    setSubmitting(false)
    if (authError) setError(describeLoginError(authError.message))
  }

  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <form
        onSubmit={handleSubmit}
        className="card"
        style={{ width: 392, padding: 28, display: 'flex', flexDirection: 'column', gap: 18 }}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, alignItems: 'flex-start' }}>
          <div
            style={{
              width: 34,
              height: 34,
              borderRadius: 10,
              background: 'var(--btn)',
              color: 'var(--btn-fg)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: 12.5,
              fontWeight: 700,
            }}
          >
            VSF
          </div>
          <div style={{ fontSize: 19, fontWeight: 700, letterSpacing: '-.01em' }}>Đăng nhập quản trị</div>
          <div style={{ fontSize: 13, color: 'var(--t3)' }}>Chỉ tài khoản vận hành nội bộ mới truy cập được.</div>
        </div>

        <Input
          id="admin-email"
          label="Email"
          type="email"
          autoComplete="username"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />

        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <label htmlFor="admin-password" className="field-label">
            Mật khẩu
          </label>
          <div style={{ position: 'relative' }}>
            <input
              id="admin-password"
              className="input"
              type={showPassword ? 'text' : 'password'}
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              style={{ paddingRight: 56 }}
            />
            <button
              type="button"
              onClick={() => setShowPassword((v) => !v)}
              style={{
                position: 'absolute',
                right: 12,
                top: 0,
                height: 40,
                background: 'none',
                border: 'none',
                fontSize: 11.5,
                fontWeight: 600,
                color: 'var(--acc)',
                cursor: 'pointer',
              }}
            >
              {showPassword ? 'Ẩn' : 'Hiện'}
            </button>
          </div>
        </div>

        {error && <div className="banner banner--err">{error}</div>}

        <Button type="submit" disabled={submitting}>
          {submitting ? 'Đang đăng nhập…' : 'Đăng nhập'}
        </Button>
        <div style={{ fontSize: 11.5, color: 'var(--t4)', textAlign: 'center' }}>
          Quên mật khẩu? Liên hệ quản trị hệ thống.
        </div>
      </form>
    </div>
  )
}
