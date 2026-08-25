import type { PipelineLastRun } from '../../api/pipelines-client'
import { formatDurationVi } from '../../lib/format-duration-vi'

/** pipeline-run-progress.tsx — the running-card extras (phase-14-pipelines-
 * list.md checklist): progress bar, "{n}/{m} bước đã xong" (L57 — Airflow
 * has no record-level progress, so this counts task instances, not rows),
 * and either an ETA (L56: only when there's real history to average from)
 * or a plain elapsed-time line -- never both, never a fabricated ETA. */
export function PipelineRunProgress({ lastRun }: { lastRun: PipelineLastRun }) {
  const progress = lastRun.progress
  if (!progress) return null

  const pct = progress.total > 0 ? Math.round((progress.done / progress.total) * 100) : 0
  const elapsedSeconds = lastRun.start_date ? Math.max(0, Math.floor((Date.now() - new Date(lastRun.start_date).getTime()) / 1000)) : null

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <div style={{ height: 6, borderRadius: 3, background: 'var(--fill)', overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: 'var(--acc)' }} />
      </div>
      <div style={{ fontSize: 11.5, color: 'var(--t3)' }}>
        {progress.total > 0 ? `${progress.done}/${progress.total} bước đã xong` : 'Đang chạy…'}
        {progress.estimated_records != null && ` · ≈ ${progress.estimated_records.toLocaleString('vi-VN')} bản ghi`}
      </div>
      {progress.eta_seconds != null ? (
        <div style={{ fontSize: 11, color: 'var(--t4)' }}>còn ≈ {formatDurationVi(progress.eta_seconds)}</div>
      ) : (
        elapsedSeconds != null && <div style={{ fontSize: 11, color: 'var(--t4)' }}>Đã chạy {formatDurationVi(elapsedSeconds)}</div>
      )}
    </div>
  )
}
