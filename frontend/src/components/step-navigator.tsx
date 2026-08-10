import { useTranslation } from 'react-i18next'
import type { StageView } from '../lib/derive-stage'

type StepKey = 'intake' | 'hotels' | 'workspace'

function stepFromStage(stage: StageView): StepKey {
  if (stage === 'hotels') return 'hotels'
  if (stage === 'workspace') return 'workspace'
  return 'intake'
}

/**
 * StepNavigator — three-step rail (design dc.html:139-145, 2507-2518).
 *
 * `stage` is whatever the middle panel is currently showing — the live
 * backend-derived stage, or a client-side view override (see App.tsx) — so
 * the rail's "current" highlight always agrees with the middle panel.
 *
 * Backward navigation prefers a pure client-side view swap: if the target
 * step's data is already sitting in `state` (intake is always collected by
 * the time another step exists; hotel options only while `hotelOptionsAvailable`),
 * clicking it just re-renders that panel via `onViewStage` — no chat turn, no
 * AI reply. Only when the data genuinely isn't loaded anymore (e.g. hotel
 * options were superseded by a trip plan) does the click fall back to sending
 * ONE translated natural-language message through the ordinary send path
 * (e.g. "Tôi muốn đổi khách sạn") — that is what the backend actually supports
 * (session.py edit flow). There is no rollback verb, and we don't pretend
 * there is. Steps not yet reached are inert.
 */
export default function StepNavigator({
  stage,
  intakeComplete,
  hotelPicked,
  hotelOptionsAvailable,
  onSend,
  onViewStage,
}: {
  stage: StageView
  /** intake collection is done (all real missing keys answered) */
  intakeComplete: boolean
  /** a hotel has been picked (trip_plan exists) */
  hotelPicked: boolean
  /** hotel options are still loaded in state — hotels can be viewed without a chat turn */
  hotelOptionsAvailable: boolean
  onSend: (text: string) => void
  onViewStage: (stage: StageView) => void
}) {
  const { t } = useTranslation()
  const current = stepFromStage(stage)

  const steps: { key: StepKey; n: string; label: string; open: boolean; message: string | null; viewable: boolean }[] = [
    { key: 'intake', n: '1', label: t('stepDetails'), open: true, message: t('stepNavBackIntake'), viewable: true },
    {
      key: 'hotels',
      n: '2',
      label: t('stepHotel'),
      open: intakeComplete,
      message: t('stepNavBackHotels'),
      viewable: hotelOptionsAvailable,
    },
    // workspace is the terminal step — nothing is ever "behind" it, so it is never
    // a backward target; it is only ever current (or a disabled forward state).
    { key: 'workspace', n: '3', label: t('stepItinerary'), open: hotelPicked, message: null, viewable: false },
  ]

  return (
    <nav
      className="flex items-center gap-1.5 px-3.5 py-2.5 border-b border-line shrink-0"
      aria-label={t('stepNavigatorLabel')}
    >
      {steps.map((step) => {
        const isCurrent = current === step.key
        const clickable = step.open && !isCurrent && (step.viewable || step.message !== null)
        const handleClick = () => {
          if (!clickable) return
          if (step.viewable) {
            onViewStage(step.key)
            return
          }
          if (step.message) onSend(step.message)
        }
        return (
          <button
            key={step.key}
            type="button"
            onClick={handleClick}
            disabled={!clickable}
            aria-current={isCurrent ? 'step' : undefined}
            className={`flex-1 flex items-center justify-center gap-1.5 px-1.5 py-2 rounded-[12px] text-[11.5px] whitespace-nowrap transition-all disabled:cursor-default ${
              isCurrent
                ? 'bg-button text-on-button font-semibold border border-button'
                : step.open
                  ? 'bg-glass-2 text-on-surface border border-stroke font-normal hover:bg-glass-3'
                  : 'bg-transparent text-on-surface-faint border border-line font-normal'
            }`}
          >
            <span className="text-[9.5px] opacity-60">{step.n}</span>
            {step.label}
          </button>
        )
      })}
    </nav>
  )
}
