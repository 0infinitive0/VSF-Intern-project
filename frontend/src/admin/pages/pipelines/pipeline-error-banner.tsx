import type { PipelineItem } from '../../api/pipelines-client'
import { DateText } from '../../ui/date-text'

interface PipelineErrorBannerProps {
  item: PipelineItem
  navigate: (to: string) => void
}

/** pipeline-error-banner.tsx — top-of-page error banner (phase-14-
 * pipelines-list.md, L54/L55). Design shows one hardcoded OTA-pipeline
 * example; the real mechanism fires for **any** of the 4 real DAGs whose
 * last run failed, content interpolated from that DAG. L55 drops the
 * design's "Giá phòng của N khách sạn có thể đã cũ." clause -- Airflow has
 * no way to derive that number, so the banner only states what's true:
 * which pipeline failed and when. */
export function PipelineErrorBanner({ item, navigate }: PipelineErrorBannerProps) {
  if (item.last_run?.state !== 'failed') return null

  return (
    <div
      className="banner banner--err"
      style={{ display: 'flex', alignItems: 'center', gap: 12, justifyContent: 'space-between' }}
    >
      <span>
        <strong>!</strong> Pipeline {item.label} lỗi lúc{' '}
        {item.last_run.start_date ? <DateText value={item.last_run.start_date} withTime /> : '—'}.
      </span>
      <button type="button" className="btn btn--secondary btn--sm" onClick={() => navigate(`/admin/pipelines/runs/${encodeURIComponent(item.last_run!.run_id)}`)}>
        Xem log
      </button>
    </div>
  )
}
