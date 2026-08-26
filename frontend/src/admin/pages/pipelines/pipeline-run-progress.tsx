import type { PipelineLastRun } from '../../api/pipelines-client'
import { Spinner } from '../../ui/spinner'

/** pipeline-run-progress.tsx — the running-card extras (phase-14-pipelines-
 * list.md checklist): progress bar and "{n}/{m} bước đã xong" (L57 — Airflow
 * has no record-level progress, so this counts task instances, not rows). */
export function PipelineRunProgress({ lastRun }: { lastRun: PipelineLastRun }) {
  const progress = lastRun.progress
  if (!progress) return null

  const pct = progress.total > 0 ? Math.round((progress.done / progress.total) * 100) : 0

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <div style={{ height: 6, borderRadius: 3, background: 'var(--fill)', overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: 'var(--acc)' }} />
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11.5, color: 'var(--t3)' }}>
        <Spinner size={11} />
        {progress.total > 0 ? `${progress.done}/${progress.total} bước đã xong` : 'Đang chạy…'}
      </div>
    </div>
  )
}
