import { useEffect, useRef, useState } from 'react'
import { getOverview, type OverviewResponse } from '../../api/overview-client'
import { triggerPipelineRun } from '../../api/pipelines-client'
import { pipelineErrorVi } from '../../lib/pipeline-error-vi'
import { PageHeader } from '../../layout/page-header'
import { Banner } from '../../ui/banner'
import { Button } from '../../ui/button'
import { DateText } from '../../ui/date-text'
import { PipelineTriggerDialog } from '../pipelines/pipeline-trigger-dialog'
import { AttentionOrdersCard } from './attention-orders-card'
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
 * renders whatever came back, null block and all). "Chạy pipeline" reuses
 * C1's simple trigger dialog (Phase 15's richer C2 options dialog doesn't
 * exist yet), same interim call Phase 14 made for its own header button. */
export function OverviewPage({ navigate }: OverviewPageProps) {
  const [state, setState] = useState<LoadState>({ status: 'loading' })
  const [refreshKey, setRefreshKey] = useState(0)
  const [triggerOpen, setTriggerOpen] = useState(false)
  const [triggerBusy, setTriggerBusy] = useState(false)
  const [triggerMessage, setTriggerMessage] = useState<{ tone: 'ok' | 'err'; text: string } | null>(null)
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
  }, [refreshKey])

  const data = state.status === 'loaded' ? state.data : null
  const pipelineDagId = data?.pipeline?.dag_id ?? null

  async function handleConfirmTrigger() {
    if (!pipelineDagId || triggerBusy) return
    setTriggerBusy(true)
    setTriggerMessage(null)
    const result = await triggerPipelineRun(pipelineDagId)
    setTriggerBusy(false)
    setTriggerOpen(false)
    if (!result.ok) {
      setTriggerMessage({ tone: 'err', text: pipelineErrorVi(result.detail) })
      return
    }
    setTriggerMessage({ tone: 'ok', text: 'Đã bắt đầu chạy pipeline.' })
    setRefreshKey((k) => k + 1)
  }

  return (
    <>
      <PageHeader
        breadcrumb="Quản trị · Tổng quan"
        title="Tổng quan vận hành"
        subtitle={data && <DateText value={data.date} />}
        action={
          <Button
            variant="primary"
            size="sm"
            disabled={!pipelineDagId || data?.pipeline?.state === 'running'}
            onClick={() => setTriggerOpen(true)}
          >
            Chạy pipeline
          </Button>
        }
      />

      <div style={{ flex: 1, minHeight: 0, padding: '22px 28px', display: 'flex', flexDirection: 'column', gap: 16, overflowY: 'auto' }}>
        {triggerMessage && <Banner tone={triggerMessage.tone}>{triggerMessage.text}</Banner>}
        {state.status === 'error' && <Banner tone="err">{state.detail}</Banner>}

        <OverviewStatCards orders={data?.orders ?? null} />

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, alignItems: 'start' }}>
          <AttentionOrdersCard items={state.status === 'loaded' ? (state.data.attention_orders ?? []) : null} navigate={navigate} />
          <ExpiringHoldsCard holds={state.status === 'loaded' ? (state.data.expiring_holds ?? []) : null} />
        </div>

        <EmbeddingStatusCard embedding={data?.embedding ?? null} pipeline={data?.pipeline ?? null} />
      </div>

      <PipelineTriggerDialog
        open={triggerOpen}
        label="Embedding"
        busy={triggerBusy}
        onConfirm={handleConfirmTrigger}
        onClose={() => setTriggerOpen(false)}
      />
    </>
  )
}
