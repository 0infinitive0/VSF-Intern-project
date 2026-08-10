import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { formatCurrency } from '../lib/format-currency'

// Real backend tier bounds (hotel_selection.py:_BUDGET_TIER_RANGE_VND) — the
// slider's own min/max, and the default handle positions mirror the old
// "Tầm trung" chip so replacing the chips changes the widget, not the default.
const SLIDER_MIN_VND = 200_000
const SLIDER_MAX_VND = 5_000_000
const SLIDER_STEP_VND = 50_000
const DEFAULT_MIN_VND = 800_000
const DEFAULT_MAX_VND = 2_500_000

/**
 * IntakeBudgetSlider — dual-thumb VND/night range picker replacing the old
 * tier chips (design reference: two overlapped native range inputs, min/max
 * labels, confirm button). Selecting doesn't auto-advance — same
 * commit-on-confirm interaction as IntakePeopleStepper/IntakeDateRange: the
 * user can drag freely and only "Xác nhận ngân sách" commits it.
 */
export default function IntakeBudgetSlider({
  min,
  max,
  onCommit,
  onSkip,
  disabled,
}: {
  min: number | null
  max: number | null
  onCommit: (min: number, max: number) => void
  onSkip: () => void
  disabled: boolean
}) {
  const { t, i18n } = useTranslation()
  const [pendingMin, setPendingMin] = useState(min ?? DEFAULT_MIN_VND)
  const [pendingMax, setPendingMax] = useState(max ?? DEFAULT_MAX_VND)

  const handleMinChange = (value: number) => {
    setPendingMin(Math.min(value, pendingMax - SLIDER_STEP_VND))
  }
  const handleMaxChange = (value: number) => {
    setPendingMax(Math.max(value, pendingMin + SLIDER_STEP_VND))
  }

  return (
    <div className="glass-card p-4 animate-[vPop_0.5s_cubic-bezier(0.22,1,0.36,1)_both]">
      <div className="text-[10px] font-semibold tracking-[0.1em] uppercase text-on-surface-muted mb-1.5">
        {t('budgetRange')}
      </div>
      <div className="flex items-baseline justify-between text-[13px] font-[590] text-on-surface mb-2.5">
        <span>{formatCurrency(pendingMin, i18n.language)}</span>
        <span>{formatCurrency(pendingMax, i18n.language)}</span>
      </div>
      <div className="relative h-6" role="group" aria-label={t('intakeBudgetLabel')}>
        <div className="absolute top-1/2 left-0 right-0 h-1 -translate-y-1/2 rounded-full bg-fill" />
        <div
          className="absolute top-1/2 h-1 -translate-y-1/2 rounded-full bg-button"
          style={{
            left: `${((pendingMin - SLIDER_MIN_VND) / (SLIDER_MAX_VND - SLIDER_MIN_VND)) * 100}%`,
            right: `${100 - ((pendingMax - SLIDER_MIN_VND) / (SLIDER_MAX_VND - SLIDER_MIN_VND)) * 100}%`,
          }}
        />
        <input
          type="range"
          aria-label={t('budgetMinLabel')}
          min={SLIDER_MIN_VND}
          max={SLIDER_MAX_VND}
          step={SLIDER_STEP_VND}
          value={pendingMin}
          disabled={disabled}
          onChange={(e) => handleMinChange(Number(e.target.value))}
          className="range-thumb absolute inset-x-0 top-0 w-full h-6 appearance-none bg-transparent disabled:opacity-60"
        />
        <input
          type="range"
          aria-label={t('budgetMaxLabel')}
          min={SLIDER_MIN_VND}
          max={SLIDER_MAX_VND}
          step={SLIDER_STEP_VND}
          value={pendingMax}
          disabled={disabled}
          onChange={(e) => handleMaxChange(Number(e.target.value))}
          className="range-thumb absolute inset-x-0 top-0 w-full h-6 appearance-none bg-transparent disabled:opacity-60"
        />
      </div>
      <div className="flex gap-2 mt-3">
        <button
          type="button"
          className="flex-1 py-2.5 rounded-[13px] bg-button text-on-button text-[13px] font-semibold tracking-[-0.12px] disabled:opacity-50"
          disabled={disabled}
          onClick={() => onCommit(pendingMin, pendingMax)}
        >
          {t('confirmBudget')}
        </button>
        <button
          type="button"
          className="flex-none px-3.5 py-2.5 rounded-[13px] border border-stroke bg-glass-2 text-on-surface-variant text-[13px] font-[530] disabled:opacity-50"
          disabled={disabled}
          onClick={onSkip}
        >
          {t('skipBudget')}
        </button>
      </div>
    </div>
  )
}
