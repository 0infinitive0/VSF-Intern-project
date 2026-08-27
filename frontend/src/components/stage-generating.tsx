import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { phaseLabelKey } from '../lib/phase-labels'
import SkeletonCard from './skeleton-card'
import TurnPhases from './turn-phases'
import type { TurnPhase } from '../types'

/**
 * StageGenerating — the "AI đang xử lý" state (design reference:
 * data/trip_planner/trip_planner_components, the generating-state mock's
 * sequential checklist — "Phân tích điểm đến", "Tìm khách sạn phù hợp", …).
 *
 * The step-by-step tick list is now REAL: plan 260806-1602-streaming-chat-messages
 * gives the backend a `phase` SSE event at each real pipeline position it
 * passes through, so `phases` here is exactly that — never invented, never
 * pre-drawn (see turn-phases.tsx). Before the first event arrives (a brief
 * window at the very start of a turn), `TurnPhases` renders null and the
 * indeterminate bar below fills that gap instead.
 *
 * Elapsed copy thresholds mirror the in-thread ElapsedSpinner so the chat and
 * the stage describe the same wait the same way.
 */
export default function StageGenerating({
  elapsedMs,
  phases,
  hasTripPlan,
}: {
  elapsedMs: number
  phases: TurnPhase[]
  /**
   * Once a trip plan already exists, a later turn that re-runs `hotel_node`
   * (e.g. editing dates/people/budget re-triggers a real availability
   * re-check per `IMPACT_MAP`, domain/travel_state.py) is not the user
   * picking a hotel for the first time — showing "Đang tìm khách sạn phù
   * hợp" here reads as if their already-selected hotel is being searched
   * for again. Dropped from the checklist in that case; the real backend
   * work still happens, this only hides a misleading row.
   */
  hasTripPlan: boolean
}): ReactNode {
  const { t } = useTranslation()
  const seconds = Math.floor(elapsedMs / 1000)
  const visiblePhases = hasTripPlan ? phases.filter((p) => p.key !== 'hotel_search') : phases
  // Title must track the same phase the checklist below is currently
  // spinning on — never an independent elapsed-time guess that can drift
  // from what's actually happening (e.g. still reading "lên lịch trình"
  // while the list has already moved on to "soạn câu trả lời").
  const currentPhaseLabelKey = [...visiblePhases].reverse().map((p) => phaseLabelKey(p.key)).find((key) => key !== null)
  const copy = currentPhaseLabelKey
    ? t(currentPhaseLabelKey)
    : seconds >= 10
      ? t('pendingBuildingPlan')
      : seconds >= 3 && !hasTripPlan
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
          <div className="text-[15px] font-[530] tracking-[-0.2px]">{copy}</div>
        </div>

        {visiblePhases.length > 0 ? (
          <div className="mb-6">
            <TurnPhases phases={visiblePhases} />
          </div>
        ) : (
          <div className="h-1 rounded-full bg-fill2 overflow-hidden mb-6" aria-hidden="true">
            <div className="h-full w-1/3 rounded-full bg-primary animate-[indeterminate-segment_1.4s_var(--ease-glide)_infinite]" />
          </div>
        )}

        <SkeletonCard variant="hotel" />
      </div>
    </div>
  )
}
