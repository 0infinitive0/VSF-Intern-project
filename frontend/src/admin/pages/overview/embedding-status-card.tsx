import type { OverviewEmbedding, OverviewPipeline } from '../../api/overview-client'
import { Banner } from '../../ui/banner'
import { DateText } from '../../ui/date-text'
import { formatDurationVi } from '../../lib/format-duration-vi'
import { pipelineRunStateVi } from '../../lib/pipeline-run-state-vi'

interface EmbeddingStatusCardProps {
  embedding: OverviewEmbedding | null
  pipeline: OverviewPipeline | null
}

/** embedding-status-card.tsx — A3's "Pipeline embedding" block (phase-17-
 * overview-kpi.md). Airflow disconnected must not blank this card or any
 * other (L78) -- rendered as its own state, the 3 other blocks stay
 * unaffected regardless of what `pipeline` says.
 *
 * `pipeline === null` (still loading, or `_fetch_pipeline_block` caught an
 * unrelated exception) is kept distinct from `pipeline.connected === false`
 * (Airflow confirmed unreachable) -- code-review M2 finding: the two used to
 * render the same "Không kết nối được Airflow" banner, which is a false
 * claim while the block simply hasn't loaded yet. Embedding coverage is
 * shown unconditionally whenever `embedding` itself is present (M3 finding):
 * it comes from an independent Supabase call and stays healthy even on a
 * bad Airflow day, so it must not disappear along with the pipeline info. */
export function EmbeddingStatusCard({ embedding, pipeline }: EmbeddingStatusCardProps) {
  const pipelineKnown = pipeline !== null
  const airflowDown = pipelineKnown && !pipeline.connected

  return (
    <div className="card" style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ fontSize: 14, fontWeight: 700 }}>Pipeline embedding</div>
        {pipeline?.connected && pipeline.state && (
          <span className={`chip ${pipeline.state === 'failed' ? 'chip--err' : pipeline.state === 'running' ? 'chip--held' : 'chip--ok'}`}>
            {pipeline.state === 'success' ? '✓' : pipeline.state === 'failed' ? '✕' : '◐'} {pipelineRunStateVi(pipeline.state)}
          </span>
        )}
      </div>

      {!pipelineKnown ? (
        <div style={{ fontSize: 12.5, color: 'var(--t3)' }}>Đang tải…</div>
      ) : airflowDown ? (
        <Banner tone="warn">! Không kết nối được Airflow — pipeline không chạy được lúc này.</Banner>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, fontSize: 12.5 }}>
          <div>
            <span style={{ color: 'var(--t3)' }}>Lần chạy gần nhất — </span>
            {pipeline.last_run_at ? <DateText value={pipeline.last_run_at} withTime /> : 'Chưa chạy lần nào'}
          </div>
          {pipeline.duration_seconds != null && (
            <div>
              <span style={{ color: 'var(--t3)' }}>Thời gian chạy — </span>
              {formatDurationVi(pipeline.duration_seconds)}
            </div>
          )}
        </div>
      )}

      {embedding && (
        <div style={{ fontSize: 12.5 }}>
          <span style={{ color: 'var(--t3)' }}>Bản ghi đã nhúng — </span>
          <span className="tabular-nums">
            {embedding.embedded.toLocaleString('vi-VN')} / {embedding.total.toLocaleString('vi-VN')}
          </span>
        </div>
      )}

      {embedding && embedding.missing > 0 && <Banner tone="warn">{embedding.missing_label} — bot sẽ không gợi ý được các mục này.</Banner>}
    </div>
  )
}
