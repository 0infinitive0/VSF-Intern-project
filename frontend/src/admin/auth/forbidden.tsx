import { useAuth } from '../../auth/auth-context'
import { Button } from '../ui/button'

/** A1 — GET /admin/me returned 403: a real, non-admin account. This is UX
 * only (every backend route already enforces require_admin) -- signing out
 * here just gets the visitor back to a clean login form. */
export function Forbidden() {
  const { user, signOut } = useAuth()

  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div
        className="card"
        style={{ width: 392, padding: 28, display: 'flex', flexDirection: 'column', gap: 18 }}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, alignItems: 'flex-start' }}>
          <div
            style={{
              width: 34,
              height: 34,
              borderRadius: 10,
              background: 'var(--err-soft)',
              color: 'var(--err)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: 16,
              fontWeight: 700,
            }}
          >
            !
          </div>
          <div style={{ fontSize: 19, fontWeight: 700, letterSpacing: '-.01em' }}>
            Tài khoản này không có quyền truy cập trang quản trị
          </div>
        </div>

        <div className="banner banner--err">
          Bạn đã đăng nhập bằng <strong>{user?.email ?? 'tài khoản này'}</strong>. Tài khoản này không có vai trò{' '}
          <strong>admin</strong>.
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <Button onClick={() => signOut()}>Quay lại đăng nhập</Button>
          <Button variant="secondary" onClick={() => window.location.assign('/')}>
            Về trang chat khách hàng
          </Button>
        </div>
      </div>
    </div>
  )
}
