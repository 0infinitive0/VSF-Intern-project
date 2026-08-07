import { useTranslation } from 'react-i18next'
import { phaseLabelKey } from '../lib/phase-labels'
import type { TurnPhase } from '../types'

/**
 * TurnPhases — the growing step-tick list for the "AI đang xử lý" state
 * (design reference: data/trip_planner/trip_planner_components, the
 * generating-state mock's "Phân tích điểm đến" / "Tìm khách sạn phù hợp" …
 * checklist). Lives in stage-generating.tsx's right-hand panel — NOT inline
 * in the chat thread (that duplicated the same progress in two places).
 *
 * The list grows one row per real `phase` event received — never pre-drawn:
 * a branch that skips a step (e.g. an intake turn never touches
 * `itinerary_build`) simply never adds that row. Every step but the last is
 * "done" (a tick); the last one shown is still "in progress" (a spinner),
 * since the branch could still emit more before `final` arrives. An unknown
 * key is dropped silently by phaseLabelKey — never rendered as a raw string.
 * Renders nothing (null) until the first event arrives — the caller falls
 * back to an indeterminate indicator for that brief window.
 */
export default function TurnPhases({ phases }: { phases: TurnPhase[] }) {
  const { t } = useTranslation()

  const rows = phases
    .map((p) => ({ ...p, labelKey: phaseLabelKey(p.key) }))
    .filter((p): p is TurnPhase & { labelKey: string } => p.labelKey !== null)

  if (rows.length === 0) return null

  return (
    <div className="flex flex-col gap-2.5" aria-live="polite" aria-busy="true">
      {rows.map((row, i) => {
        const isLast = i === rows.length - 1
        return (
          <div key={`${row.key}-${row.at}`} className="flex items-center gap-2.5 text-[13.5px] text-on-surface">
            {isLast ? (
              <span
                className="w-4 h-4 flex-none rounded-full border-2 border-primary border-t-transparent animate-spin"
                aria-hidden="true"
              />
            ) : (
              <span
                className="w-4 h-4 flex-none rounded-full bg-success/15 text-success flex items-center justify-center text-[10px] font-bold"
                aria-hidden="true"
              >
                ✓
              </span>
            )}
            <span>{t(row.labelKey)}</span>
          </div>
        )
      })}
    </div>
  )
}
