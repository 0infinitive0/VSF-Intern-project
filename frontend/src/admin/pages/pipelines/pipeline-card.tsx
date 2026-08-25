import type { PipelineItem } from '../../api/pipelines-client'
import { Button } from '../../ui/button'
import { DateText } from '../../ui/date-text'
import { formatDurationVi } from '../../lib/format-duration-vi'
import { PipelineRunProgress } from './pipeline-run-progress'
import { PipelineSparkline } from './pipeline-sparkline'
import { PipelineStatusChip } from './pipeline-status-chip'

interface PipelineCardProps {
  item: PipelineItem
  disabled: boolean
  busy: boolean
  onRun: () => void
}

/** pipeline-card.tsx — C1's card (phase-14-pipelines-list.md checklist).
 * Border/glow by state, running card swaps the button for a disabled
 * "Đang chạy…" one and adds the progress block -- no `dag_id` or other
 * technical term ever rendered (plan's "Ranh giới không được vượt"). */
export function PipelineCard({ item, disabled, busy, onRun }: PipelineCardProps) {
  const state = item.last_run?.state
  const isRunning = state === 'running'
  const isFailed = state === 'failed'

  const borderStyle = isFailed
    ? { border: '1px solid rgba(192,94,112,.35)' }
    : isRunning
      ? { border: '1px solid var(--acc)', boxShadow: '0 0 0 3px var(--acc-soft)' }
      : { border: '1px solid var(--stroke)' }

  return (
    <div className="card" style={{ padding: 18, display: 'flex', flexDirection: 'column', gap: 12, ...borderStyle }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 10 }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 15, fontWeight: 700 }}>{item.label}</div>
          <div style={{ fontSize: 12.5, color: 'var(--t3)' }}>{item.description}</div>
        </div>
        <PipelineStatusChip state={state} />
      </div>

      {item.last_run && (
        <div style={{ fontSize: 11.5, color: 'var(--t4)', display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {item.last_run.start_date && <DateText value={item.last_run.start_date} withTime />}
          {item.last_run.duration_seconds != null && <span>· {formatDurationVi(item.last_run.duration_seconds)}</span>}
        </div>
      )}

      <PipelineSparkline runs={item.recent_runs ?? []} />

      {isRunning && item.last_run && <PipelineRunProgress lastRun={item.last_run} />}

      <div style={{ display: 'flex', gap: 8 }}>
        {isRunning ? (
          <Button variant="secondary" size="sm" disabled style={{ background: 'var(--fill)', color: 'var(--t4)', flex: 1 }}>
            Đang chạy…
          </Button>
        ) : (
          <Button variant="primary" size="sm" disabled={disabled || busy} onClick={onRun} style={{ flex: 1 }}>
            Chạy
          </Button>
        )}
      </div>
    </div>
  )
}
