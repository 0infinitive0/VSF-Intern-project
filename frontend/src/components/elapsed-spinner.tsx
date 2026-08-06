import { useTranslation } from 'react-i18next'

/**
 * ElapsedSpinner — in-flow thinking indicator (design dc.html:189-198).
 * Shows three animated dots, plus the honest elapsed-seconds caption only once
 * the wait has stretched past a few seconds (phase-06: three dots in the
 * thread, elapsed time survives as a small caption — nothing is invented, the
 * seconds are real).
 */
export default function ElapsedSpinner({ elapsedMs }: { elapsedMs: number }) {
  const { t } = useTranslation()
  const seconds = Math.floor(elapsedMs / 1000)
  let copy = t('pendingDefault')
  if (seconds >= 10) copy = t('pendingBuildingPlan')
  else if (seconds >= 3) copy = t('pendingSearchingHotels')

  return (
    <div className="flex gap-2.5 items-end" aria-live="polite" aria-busy="true">
      <div className="w-6 h-6 flex-none rounded-[9px] bg-[linear-gradient(145deg,#5C93EE,#2C5FC9)] flex items-center justify-center">
        <span className="text-on-primary text-[11px] font-semibold">V</span>
      </div>
      <div className="flex flex-col gap-1.5">
        <div className="flex gap-1 px-[15px] py-[13px] rounded-[18px] bg-glass-3 border border-line">
          <span className="w-1.5 h-1.5 rounded-full bg-on-surface animate-[vDot_1.1s_infinite]" aria-hidden="true" />
          <span className="w-1.5 h-1.5 rounded-full bg-on-surface animate-[vDot_1.1s_0.16s_infinite]" aria-hidden="true" />
          <span className="w-1.5 h-1.5 rounded-full bg-on-surface animate-[vDot_1.1s_0.32s_infinite]" aria-hidden="true" />
        </div>
        {seconds > 0 && (
          <div className="text-[9.5px] font-medium tracking-[0.04em] text-on-surface-muted px-1">
            {copy} ({seconds} {t('elapsedSuffix')})
          </div>
        )}
      </div>
    </div>
  )
}
