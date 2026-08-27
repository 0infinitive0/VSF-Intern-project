import { useEffect, useRef, useState } from 'react'
import { getOverview, type OverviewResponse } from '../../api/overview-client'
import { PageHeader } from '../../layout/page-header'
import { Banner } from '../../ui/banner'
import { DateText } from '../../ui/date-text'
import { PendingOrdersCard } from './pending-orders-card'
import { EmbeddingStatusCard } from './embedding-status-card'
import { ExpiringHoldsCard } from './expiring-holds-card'
import { OverviewStatCards } from './overview-stat-cards'

const POLL_MS = 60_000

type LoadState = { status: 'loading' } | { status: 'loaded'; data: OverviewResponse } | { status: 'error'; detail: string }

interface OverviewPageProps {
  navigate: (to: string) => void
}

/** overview-page.tsx — A3 (phase-17-overview-kpi.md), the `/admin` landing
 * page. One `GET /admin/overview` call every 60s (each of its 5 blocks
 * already fails independently server-side, so a bad Airflow day or a
 * transient Supabase error never blanks the other cards -- this page just
 * renders whatever came back, null block and all). The header's manual
 * "Chạy pipeline" trigger was removed by request; per-hotel re-embed
 * (hotel-detail-page.tsx, embedding-status-page.tsx) is still how an admin
 * forces a specific re-embed -- this page stays read-only. */
export function OverviewPage({ navigate }: OverviewPageProps) {
  const [state, setState] = useState<LoadState>({ status: 'loading' })
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    let cancelled = false

    function poll() {
      getOverview()
        .then((result) => {
          if (cancelled) return
          if (!result.ok) {
            setState({ status: 'error', detail: result.detail })
          } else {
            setState({ status: 'loaded', data: result.data })
          }
          timerRef.current = setTimeout(poll, POLL_MS)
        })
        .catch(() => {
          if (cancelled) return
          setState({ status: 'error', detail: 'Không tải được trang tổng quan.' })
          timerRef.current = setTimeout(poll, POLL_MS)
        })
    }

    poll()
    return () => {
      cancelled = true
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [])

  const data = state.status === 'loaded' ? state.data : null

  return (
    <>
      <PageHeader breadcrumb="Quản trị · Tổng quan" title="Tổng quan vận hành" subtitle={data && <DateText value={data.date} />} />

      <div style={{ flex: 1, minHeight: 0, padding: '22px 28px', display: 'flex', flexDirection: 'column', gap: 16, overflowY: 'auto' }}>
        {state.status === 'error' && <Banner tone="err">{state.detail}</Banner>}

        <OverviewStatCards orders={data?.orders ?? null} />

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, alignItems: 'start' }}>
          <PendingOrdersCard items={state.status === 'loaded' ? (state.data.pending_orders ?? []) : null} navigate={navigate} />
          <ExpiringHoldsCard holds={state.status === 'loaded' ? (state.data.expiring_holds ?? []) : null} />
        </div>

        <EmbeddingStatusCard embedding={data?.embedding ?? null} pipeline={data?.pipeline ?? null} />
      </div>
    </>
  )
}
