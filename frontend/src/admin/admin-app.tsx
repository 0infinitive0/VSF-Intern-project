import { useEffect, useState } from 'react'
import { useAuth } from '../auth/auth-context'
import { getAdminMe, type AdminMe } from './api/admin-me'
import { AdminLogin } from './auth/admin-login'
import { Forbidden } from './auth/forbidden'
import { AdminShell } from './layout/admin-shell'
import { OverviewPage } from './pages/overview-page'
import { HotelCreatePage } from './pages/hotels/hotel-create-page'
import { HotelDetailPage } from './pages/hotels/hotel-detail-page'
import { HotelsPage } from './pages/hotels/hotels-page'
import { RouteStub } from './pages/route-stub'
import { useAdminRoute } from './router'

type MeState = { status: 'checking' } | { status: 'forbidden' } | { status: 'error'; detail: string } | { status: 'ok'; me: AdminMe }

function resolvePage(path: string, navigate: (to: string) => void) {
  if (path === '/admin') return <OverviewPage />
  if (path === '/admin/hotels/new') return <HotelCreatePage navigate={navigate} />
  if (path.startsWith('/admin/hotels/')) {
    const hotelId = decodeURIComponent(path.slice('/admin/hotels/'.length).split('/')[0] ?? '')
    // A trailing slash ("/admin/hotels/") yields an empty id -- treat it as
    // the list page rather than firing GET /hotels/ (which 404s/307s and
    // leaves HotelDetailPage rendering against no hotel).
    if (!hotelId) return <HotelsPage navigate={navigate} />
    return <HotelDetailPage hotelId={hotelId} navigate={navigate} />
  }
  if (path === '/admin/hotels') return <HotelsPage navigate={navigate} />
  if (path === '/admin/embedding') return <RouteStub title="Trạng thái embedding" phase={12} />
  if (path === '/admin/pipelines/do-phu-embedding') return <RouteStub title="Độ phủ embedding" phase={12} />
  if (path.startsWith('/admin/pipelines/runs/')) return <RouteStub title="Chi tiết lần chạy" phase={16} />
  if (path === '/admin/pipelines') return <RouteStub title="Pipeline" phase={14} />
  if (path.startsWith('/admin/orders/')) return <RouteStub title="Chi tiết đơn hàng" phase={5} />
  if (path === '/admin/orders') return <RouteStub title="Danh sách đơn hàng" phase={4} />
  return <RouteStub title="Không tìm thấy trang" phase={0} />
}

/**
 * admin-app.tsx — the gate (see phase-03-admin-shell-frontend.md's "Luồng
 * gate"). `isAnonymous` stands in for "chưa đăng nhập": AuthProvider (reused
 * as-is from the chat app) always mints a real Supabase session, anonymous
 * ones included, so `auth.status` alone can never distinguish "no admin
 * session yet" from "logged in as a real admin" -- only `isAnonymous` can.
 * The anonymous bootstrap itself is accepted as-is (plan's risk table):
 * it's wasted but harmless, since every anonymous caller still 403s.
 */
export function AdminApp() {
  const auth = useAuth()
  const [meState, setMeState] = useState<MeState>({ status: 'checking' })
  const { path, navigate } = useAdminRoute()

  useEffect(() => {
    if (auth.status !== 'ready' || auth.isAnonymous) return
    let cancelled = false
    setMeState({ status: 'checking' })
    getAdminMe().then((result) => {
      if (cancelled) return
      if (result.ok) return setMeState({ status: 'ok', me: result.data })
      if (result.status === 403 || result.status === 401) return setMeState({ status: 'forbidden' })
      setMeState({ status: 'error', detail: result.detail })
    })
    return () => {
      cancelled = true
    }
  }, [auth.status, auth.isAnonymous])

  if (auth.status === 'loading') {
    return <div style={{ minHeight: '100vh' }} />
  }

  if (auth.isAnonymous) {
    return <AdminLogin />
  }

  if (meState.status === 'checking') {
    return <div style={{ minHeight: '100vh' }} />
  }

  if (meState.status === 'forbidden') {
    return <Forbidden />
  }

  if (meState.status === 'error') {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div className="banner banner--err" style={{ maxWidth: 420 }}>
          {meState.detail}
        </div>
      </div>
    )
  }

  return (
    <AdminShell path={path} navigate={navigate}>
      {resolvePage(path, navigate)}
    </AdminShell>
  )
}
