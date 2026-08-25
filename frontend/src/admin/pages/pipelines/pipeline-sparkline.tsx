import type { PipelineRunSummary } from '../../api/pipelines-client'
import { formatDurationVi } from '../../lib/format-duration-vi'
import { pipelineRunStateVi } from '../../lib/pipeline-run-state-vi'

const BAR_COLOR: Record<string, string> = {
  success: 'rgba(42,145,135,.55)',
  failed: 'var(--err)',
  running: 'var(--acc)',
}

const BAR_WIDTH = 8
const BAR_MAX_HEIGHT = 32
const BAR_MIN_HEIGHT = 6

/** pipeline-sparkline.tsx — "biểu đồ thanh 10 lần chạy gần nhất" (phase-14-
 * pipelines-list.md checklist). `runs` must already be oldest-first (the
 * client's `list_dag_runs` returns newest-first; `pipelines.py` reverses it
 * server-side) so the last bar is always the most recent run -- no special
 * casing needed here for "thanh cuối đổi màu theo trạng thái lần chạy mới
 * nhất", it falls out of per-bar coloring by construction. */
export function PipelineSparkline({ runs }: { runs: PipelineRunSummary[] }) {
  if (runs.length === 0) {
    return <div style={{ height: BAR_MAX_HEIGHT, fontSize: 11, color: 'var(--t4)', display: 'flex', alignItems: 'center' }}>Chưa có lần chạy nào</div>
  }
  const maxDuration = Math.max(1, ...runs.map((r) => r.duration_seconds ?? 0))
  return (
    <div style={{ display: 'flex', alignItems: 'flex-end', gap: 3, height: BAR_MAX_HEIGHT }}>
      {runs.map((run, i) => {
        const height =
          run.duration_seconds != null ? Math.max(BAR_MIN_HEIGHT, Math.round((run.duration_seconds / maxDuration) * BAR_MAX_HEIGHT)) : BAR_MIN_HEIGHT
        const color = (run.state && BAR_COLOR[run.state]) || 'var(--stroke)'
        const stateLabel = pipelineRunStateVi(run.state)
        const title = run.duration_seconds != null ? `${stateLabel} · ${formatDurationVi(run.duration_seconds)}` : stateLabel
        return <span key={run.run_id || i} title={title} style={{ width: BAR_WIDTH, height, borderRadius: 3, background: color, flex: 'none' }} />
      })}
    </div>
  )
}
