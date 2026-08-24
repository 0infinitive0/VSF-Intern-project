import { useTranslation } from 'react-i18next'
import type { StageView } from '../lib/derive-stage'
import { navigationTarget } from '../lib/phase-navigation'

type StepKey = 'intake' | 'hotels' | 'workspace'

/** 'generating' covers TWO very different moments (derive-stage.ts never
 * tells them apart, both are just "AI is working"): searching for hotels
 * right after intake (no hotel has ever been found yet this session), and
 * building the itinerary right after confirming/holding one (hotels were
 * already found — the guest is long past step 1). Defaulting the latter to
 * 'intake' used to yank the rail back to "1. Thông tin" the instant a guest
 * held a room, even though nothing about their trip details changed —
 * `hotelOptionsAvailable` (the RETAINED per-session list, never the
 * turn-local one that empties out for this exact turn) is what
 * distinguishes the two: stay on 'hotels' until the real derived stage
 * lands on 'workspace' once the itinerary actually exists. */
function stepFromStage(stage: StageView, hotelOptionsAvailable: boolean): StepKey {
  if (stage === 'hotels') return 'hotels'
  if (stage === 'workspace') return 'workspace'
  if (stage === 'generating' && hotelOptionsAvailable) return 'hotels'
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
  sessionBookedFromBackend,
}: {
  stage: StageView
  intakeComplete: boolean
  hotelPicked: boolean
  hotelOptionsAvailable: boolean
  hotelsLoading: boolean
  onChangeHotel: () => void
  onViewStage: (stage: StageView) => void
  sessionBookedFromBackend?: boolean
}) {
  const { t } = useTranslation()
  const current = stepFromStage(stage, hotelOptionsAvailable)
  const steps: { key: StepKey; n: string; label: string; locked?: boolean }[] = [
    { key: 'intake', n: '1', label: t('stepDetails') },
    { key: 'hotels', n: '2', label: t('stepHotel'), locked: sessionBookedFromBackend },
    { key: 'workspace', n: '3', label: t('stepItinerary') },
  ]

  return (
    <nav className="flex items-center gap-[5px] px-3.5 py-2.5 border-b border-line shrink-0" aria-label={t('stepNavigatorLabel')}>
      {steps.map((step) => {
        const isCurrent = current === step.key
        const target = navigationTarget(step.key, { intakeComplete, hotelOptionsAvailable, hotelPicked })
        const canChangeHotel =
          step.key === 'hotels' && intakeComplete && !hotelOptionsAvailable && !hotelsLoading && !sessionBookedFromBackend
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
            style={{ transition: 'all .3s var(--ease-spring)' }}
            className={`flex-1 flex items-center justify-center gap-1.5 px-1.5 py-[7px] rounded-[12px] text-[11.5px] whitespace-nowrap disabled:cursor-default active:scale-[0.97] ${
              isCurrent
                ? 'bg-button text-on-button font-semibold border border-button'
                : clickable
                  ? 'bg-glass-2 text-on-surface border border-stroke font-normal hover:bg-glass-3'
                  : 'bg-transparent text-on-surface-faint border border-line font-normal'
            }`}
          >
            <span className="text-[9.5px] opacity-60">{step.n}</span>
            <span>{step.label}</span>
            {step.locked && (
              <span className="material-symbols-outlined text-[12px] opacity-70" aria-hidden="true">
                lock
              </span>
            )}
            {busy && <span aria-hidden="true" className="w-3 h-3 rounded-full border-[1.5px] border-current border-t-transparent animate-spin opacity-70" />}
          </button>
        )
      })}
    </nav>
  )
}
