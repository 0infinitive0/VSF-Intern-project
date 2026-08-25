import { useEffect, useRef, useState } from 'react'
import { listPipelines, triggerPipelineRun, type PipelineItem, type PipelinesListResponse } from '../../api/pipelines-client'
import { pipelineErrorVi } from '../../lib/pipeline-error-vi'
import { PageHeader } from '../../layout/page-header'
import { Banner } from '../../ui/banner'
import { Button } from '../../ui/button'
import { PipelineCard } from './pipeline-card'
import { PipelineErrorBanner } from './pipeline-error-banner'
import { PipelineTriggerDialog } from './pipeline-trigger-dialog'

const POLL_MS_RUNNING = 5000
const POLL_MS_IDLE = 60000

type ListState = { status: 'loading' } | { status: 'loaded'; data: PipelinesListResponse } | { status: 'error'; detail: string }

interface PipelinesPageProps {
  navigate: (to: string) => void
}

/** pipelines-page.tsx — C1 orchestrator (phase-14-pipelines-list.md). Owns
 * the poll loop (5s while any card is running, 60s otherwise, stopped on
 * unmount) and the one trigger dialog shared by all 4 cards. "Lịch sử lần
 * chạy" header button is deliberately absent (L58): its target
 * `/admin/pipelines/runs` has no route yet -- Phase 16 adds it. */
export function PipelinesPage({ navigate }: PipelinesPageProps) {
  const [listState, setListState] = useState<ListState>({ status: 'loading' })
  const [refreshKey, setRefreshKey] = useState(0)
  const [triggerDialog, setTriggerDialog] = useState<{ dagId: string; label: string } | null>(null)
  const [triggerBusy, setTriggerBusy] = useState(false)
  const [triggerMessage, setTriggerMessage] = useState<{ tone: 'ok' | 'err'; text: string } | null>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    let cancelled = false

    function scheduleNext(hasRunning: boolean) {
      if (cancelled) return
      timerRef.current = setTimeout(poll, hasRunning ? POLL_MS_RUNNING : POLL_MS_IDLE)
    }

    function poll() {
      listPipelines()
        .then((result) => {
          if (cancelled) return
          if (!result.ok) {
            setListState({ status: 'error', detail: result.detail })
            scheduleNext(false)
            return
          }
          setListState({ status: 'loaded', data: result.data })
          scheduleNext(result.data.items.some((item) => item.last_run?.state === 'running'))
        })
        .catch(() => {
          // adminFetch's success path awaits res.json() outside its own
          // try/catch -- a 200 with a non-JSON body (proxy/gateway HTML, a
          // truncated response) rejects instead of resolving to `{ok:false}`.
          // Without this, the poll loop would silently die here: no more
          // scheduleNext, no error shown, the page stuck on stale data.
          if (cancelled) return
          setListState({ status: 'error', detail: 'Không tải được danh sách pipeline.' })
          scheduleNext(false)
        })
    }

    poll()
    return () => {
      cancelled = true
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [refreshKey])

  async function handleConfirmTrigger() {
    if (!triggerDialog || triggerBusy) return
    setTriggerBusy(true)
    setTriggerMessage(null)
    const result = await triggerPipelineRun(triggerDialog.dagId)
    setTriggerBusy(false)
    setTriggerDialog(null)
    if (!result.ok) {
      setTriggerMessage({ tone: 'err', text: pipelineErrorVi(result.detail) })
      return
    }
    setTriggerMessage({ tone: 'ok', text: `Đã bắt đầu chạy pipeline.` })
    setRefreshKey((k) => k + 1) // re-poll immediately instead of waiting up to 60s
  }

  const items = listState.status === 'loaded' ? listState.data.items : []
  const connected = listState.status === 'loaded' ? listState.data.connected : true
  const failedItem = items.find((item) => item.last_run?.state === 'failed')
  const embedding = items.find((item) => item.has_params)

  return (
    <>
      <PageHeader
        breadcrumb="Quản trị · Dữ liệu bot"
        title="Pipeline"
        action={
          embedding && (
            <Button
              variant="primary"
              size="sm"
              disabled={!connected || triggerBusy || embedding.last_run?.state === 'running'}
              onClick={() => setTriggerDialog({ dagId: embedding.dag_id, label: embedding.label })}
            >
              Chạy embedding
            </Button>
          )
        }
      />

      <div style={{ flex: 1, minHeight: 0, padding: '22px 28px', display: 'flex', flexDirection: 'column', gap: 14, overflowY: 'auto' }}>
        {triggerMessage && <Banner tone={triggerMessage.tone}>{triggerMessage.text}</Banner>}

        {!connected && (
          <Banner tone="warn">! Không kết nối được Airflow — pipeline không chạy được lúc này.</Banner>
        )}

        {listState.status === 'error' && <Banner tone="err">{listState.detail}</Banner>}

        {failedItem && <PipelineErrorBanner item={failedItem} navigate={navigate} />}

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 14 }}>
          {listState.status === 'loading' &&
            Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="card" style={{ height: 180, opacity: 0.4 }} />
            ))}

          {items.map((item: PipelineItem) => (
            <PipelineCard
              key={item.dag_id}
              item={item}
              disabled={!connected}
              busy={triggerBusy}
              onRun={() => setTriggerDialog({ dagId: item.dag_id, label: item.label })}
            />
          ))}
        </div>
      </div>

      <PipelineTriggerDialog
        open={triggerDialog !== null}
        label={triggerDialog?.label ?? null}
        busy={triggerBusy}
        onConfirm={handleConfirmTrigger}
        onClose={() => setTriggerDialog(null)}
      />
    </>
  )
}
