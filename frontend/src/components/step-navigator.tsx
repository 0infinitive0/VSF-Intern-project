import { useTranslation } from 'react-i18next'
import type { StageView } from '../lib/derive-stage'
import { navigationTarget } from '../lib/phase-navigation'

type StepKey = 'intake' | 'hotels' | 'workspace'

function stepFromStage(stage: StageView): StepKey {
  if (stage === 'hotels') return 'hotels'
  if (stage === 'workspace') return 'workspace'
  return 'intake'
}

/** Three-step rail. Local navigation only swaps views; when the selected
 * hotel has already produced an itinerary, returning to hotels fetches a new
 * candidate list through the deterministic change-hotel endpoint. */
export default function StepNavigator({
  stage,
  intakeComplete,
  hotelPicked,
  hotelOptionsAvailable,
  hotelsLoading,
  onChangeHotel,
  onViewStage,
}: {
  stage: StageView
  intakeComplete: boolean
  hotelPicked: boolean
  hotelOptionsAvailable: boolean
  hotelsLoading: boolean
  onChangeHotel: () => void
  onViewStage: (stage: StageView) => void
}) {
  const { t } = useTranslation()
  const current = stepFromStage(stage)
  const steps: { key: StepKey; n: string; label: string }[] = [
    { key: 'intake', n: '1', label: t('stepDetails') },
    { key: 'hotels', n: '2', label: t('stepHotel') },
    { key: 'workspace', n: '3', label: t('stepItinerary') },
  ]

  return (
    <nav className="flex items-center gap-1.5 px-3.5 py-2.5 border-b border-line shrink-0" aria-label={t('stepNavigatorLabel')}>
      {steps.map((step) => {
        const isCurrent = current === step.key
        const target = navigationTarget(step.key, { intakeComplete, hotelOptionsAvailable, hotelPicked })
        const canChangeHotel = step.key === 'hotels' && intakeComplete && !hotelOptionsAvailable && !hotelsLoading
        const clickable = !isCurrent && (target !== null || canChangeHotel)
        const busy = step.key === 'hotels' && hotelsLoading

        return (
          <button
            key={step.key}
            type="button"
            onClick={() => {
              if (target) onViewStage(target)
              else if (canChangeHotel) onChangeHotel()
            }}
            disabled={!clickable}
            aria-current={isCurrent ? 'step' : undefined}
            aria-busy={busy || undefined}
            className={`flex-1 flex items-center justify-center gap-1.5 px-1.5 py-2 rounded-[12px] text-[11.5px] whitespace-nowrap transition-all disabled:cursor-default ${
              isCurrent
                ? 'bg-button text-on-button font-semibold border border-button'
                : clickable
                  ? 'bg-glass-2 text-on-surface border border-stroke font-normal hover:bg-glass-3'
                  : 'bg-transparent text-on-surface-faint border border-line font-normal'
            }`}
          >
            <span className="text-[9.5px] opacity-60">{step.n}</span>
            {step.label}
            {busy && <span aria-hidden="true" className="w-3 h-3 rounded-full border-[1.5px] border-current border-t-transparent animate-spin opacity-70" />}
          </button>
        )
      })}
    </nav>
  )
}
