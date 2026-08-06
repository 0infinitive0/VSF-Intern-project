import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import SkeletonCard from './skeleton-card'

/**
 * StageGenerating — the "AI đang xử lý" state (design V-OTA Planner.dc.html:141-154).
 *
 * WHY THERE IS NO STEP-BY-STEP TICK LIST HERE: the design's original
 * isGenerating markup renders a sequential checklist ("✓ Phân tích điểm đến",
 * "✓ Tìm khách sạn phù hợp", …). The backend only emits `pending: true` and
 * wall-clock time — it has no per-step progress signal. Ticking steps forward
 * on a timer would be CLAIMED progress the system does not know. Plan
 * principle "không bịa dữ liệu" and plan.md "Phần chưa làm" #14 (same
 * precedent that removed Stitch's "DeepDive Thinking"): one processing state
 * + the REAL elapsed seconds + skeletons + an indeterminate bar instead. If
 * the backend ever publishes real step progress, add the list back — nothing
 * else here changes.
 *
 * Elapsed copy thresholds mirror the in-thread ElapsedSpinner so the chat and
 * the stage describe the same wait the same way.
 */
export default function StageGenerating({ elapsedMs }: { elapsedMs: number }): ReactNode {
  const { t } = useTranslation()
  const seconds = Math.floor(elapsedMs / 1000)
  const copy =
    seconds >= 10
      ? t('pendingBuildingPlan')
      : seconds >= 3
        ? t('pendingSearchingHotels')
        : t('pendingDefault')

  return (
    <div className="flex-1 min-w-0 overflow-y-auto flex items-center justify-center p-9">
      <div
        role="status"
        aria-live="polite"
        className="w-[min(560px,100%)] glass-panel rounded-[32px] p-8 animate-[vRise_0.6s_cubic-bezier(0.22,1,0.36,1)_both]"
      >
        <div className="flex items-center gap-3 mb-5">
          <div
            aria-hidden="true"
            className="w-[34px] h-[34px] flex-none rounded-[12px] bg-[linear-gradient(145deg,#5C93EE,#2C5FC9)] flex items-center justify-center text-on-primary font-[590] animate-[vPulse_1.8s_infinite]"
          >
            V
          </div>
          <div>
            <div className="text-[15px] font-[530] tracking-[-0.2px]">{copy}</div>
            <div className="text-[12.5px] text-on-surface-muted">
              {/* One real elapsed-second caption; a bare nbsp holds the line on
                  second zero so the panel doesn't jump when the counter starts. */}
              {seconds > 0 ? t('generatingElapsed', { seconds }) : '\u00A0'}
            </div>
          </div>
        </div>

        <div className="h-1 rounded-full bg-fill2 overflow-hidden mb-6" aria-hidden="true">
          <div className="h-full w-1/3 rounded-full bg-primary animate-[indeterminate-segment_1.4s_var(--ease-glide)_infinite]" />
        </div>

        <SkeletonCard variant="hotel" />
      </div>
    </div>
  )
}
