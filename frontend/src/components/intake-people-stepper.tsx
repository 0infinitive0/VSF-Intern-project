import { useState } from 'react'
import { useTranslation } from 'react-i18next'

/**
 * IntakePeopleStepper — segmented 1..5+ picker (design dc.html:214-224).
 * Mirrors the design's peopleOptions: a segmented control with equal segments,
 * active segment highlighted. The "confirm" button commits the pending count —
 * selecting a segment does NOT advance the flow, so the user can change their
 * mind before committing.
 */
export default function IntakePeopleStepper({
  value,
  onCommit,
  disabled,
}: {
  value: number
  onCommit: (n: number) => void
  disabled: boolean
}) {
  const { t } = useTranslation()
  const [pending, setPending] = useState(value)
  const options = [1, 2, 3, 4, 5]

  return (
    <div className="glass-card p-3.5 animate-[vPop_0.5s_cubic-bezier(0.22,1,0.36,1)_both]">
      <div className="text-[10px] font-semibold tracking-[0.1em] uppercase text-on-surface-muted mb-2.5">
        {t('intakePeopleLabel')}
      </div>
      <div
        className="flex p-0.5 rounded-[13px] bg-fill gap-0.5"
        role="group"
        aria-label={t('intakePeopleLabel')}
      >
        {options.map((n) => {
          const isSelected = pending === n
          return (
            <button
              key={n}
              type="button"
              aria-pressed={isSelected}
              disabled={disabled}
              onClick={() => setPending(n)}
              className={`flex-1 py-2 rounded-[10px] text-[13px] transition-all disabled:opacity-60 ${
                isSelected
                  ? 'bg-glass-3 text-on-surface font-semibold shadow-[0_4px_12px_-6px_rgb(var(--shadow-rgb)/0.6)]'
                  : 'bg-transparent text-on-surface-variant font-normal'
              }`}
            >
              {n === 5 ? '5+' : String(n)}
            </button>
          )
        })}
      </div>
      <button
        type="button"
        className="mt-2.5 w-full py-2.5 rounded-[13px] bg-button text-on-button text-[13px] font-semibold tracking-[-0.12px] disabled:opacity-50"
        disabled={disabled || pending <= 0}
        onClick={() => onCommit(pending)}
      >
        {t('intakeConfirm')}
      </button>
    </div>
  )
}
