import { useEffect, useState } from 'react'
import { useAuth } from '../auth/auth-context'
import { getAdminMe, type AdminMe } from './api/admin-me'
import { AdminLogin } from './auth/admin-login'
import { Forbidden } from './auth/forbidden'
import { AdminShell } from './layout/admin-shell'
import { AmenityCatalogPage } from './pages/amenities/amenity-catalog-page'
import { EmbeddingCoveragePage } from './pages/embedding/embedding-coverage-page'
import { EmbeddingStatusPage } from './pages/embedding/embedding-status-page'
import { HotelCreatePage } from './pages/hotels/hotel-create-page'
import { HotelDetailPage } from './pages/hotels/hotel-detail-page'
import { HotelsPage } from './pages/hotels/hotels-page'
import { RoomPricesPage } from './pages/hotels/prices/room-prices-page'
import { OrderDetailPage } from './pages/orders/order-detail-page'
import { OrdersPage } from './pages/orders/orders-page'
import { OverviewPage } from './pages/overview/overview-page'
import { PipelinesPage } from './pages/pipelines/pipelines-page'
import { RouteStub } from './pages/route-stub'
import { useAdminRoute } from './router'

type MeState = { status: 'checking' } | { status: 'forbidden' } | { status: 'error'; detail: string } | { status: 'ok'; me: AdminMe }

function resolvePage(path: string, navigate: (to: string) => void) {
  if (path === '/admin') return <OverviewPage navigate={navigate} />
  if (path === '/admin/hotels/new') return <HotelCreatePage navigate={navigate} />
  if (path.startsWith('/admin/hotels/')) {
    const segments = decodeURIComponent(path.slice('/admin/hotels/'.length)).split('/')
    const hotelId = segments[0] ?? ''
    // A trailing slash ("/admin/hotels/") yields an empty id -- treat it as
    // the list page rather than firing GET /hotels/ (which 404s/307s and
    // leaves HotelDetailPage rendering against no hotel).
    if (!hotelId) return <HotelsPage navigate={navigate} />
    // /admin/hotels/:hotelId/rooms/:roomId/prices (B6, phase-11) -- the one
    // nested route under /hotels/:id; everything else on that prefix still
    // falls through to HotelDetailPage's own tabs.
    if (segments[1] === 'rooms' && segments[2] && segments[3] === 'prices') {
      return <RoomPricesPage hotelId={hotelId} roomId={segments[2]} navigate={navigate} />
    }
    return <HotelDetailPage hotelId={hotelId} navigate={navigate} />
  }
  if (path === '/admin/hotels') return <HotelsPage navigate={navigate} />
  if (path === '/admin/amenities-catalog') return <AmenityCatalogPage />
  if (path === '/admin/embedding') return <EmbeddingStatusPage navigate={navigate} />
  if (path === '/admin/pipelines/do-phu-embedding') return <EmbeddingCoveragePage navigate={navigate} />
  if (path.startsWith('/admin/pipelines/runs/')) return <RouteStub title="Chi tiết lần chạy" phase={16} />
  if (path === '/admin/pipelines') return <PipelinesPage navigate={navigate} />
  if (path.startsWith('/admin/orders/')) {
    const paymentId = decodeURIComponent(path.slice('/admin/orders/'.length))
    if (!paymentId) return <OrdersPage navigate={navigate} />
    return <OrderDetailPage paymentId={paymentId} />
  }
  if (path === '/admin/orders') return <OrdersPage navigate={navigate} />
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
