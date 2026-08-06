import { useState } from 'react'
import { useTranslation } from 'react-i18next'

/**
 * IntakeBudgetTiers — budget/accommodation tier chips (design dc.html:258-276,
 * but tier chips instead of the slider — see phase-06 plan "Ngân sách giữ dạng
 * chip theo mức"). Options come from intake.budget_options, which are the real
 * backend tier labels (including the "Bỏ qua, không cần lọc theo giá" skip
 * option); their values pass through untouched because composeIntakeMessage()
 * maps them to wire phrases via budgetPhraseFromLabel. The chosen tier commits
 * on "confirm" — selecting does not auto-advance the flow.
 */
export default function IntakeBudgetTiers({
  options,
  selected,
  onCommit,
  disabled,
}: {
  options: string[]
  selected: string
  onCommit: (value: string) => void
  disabled: boolean
}) {
  const { t } = useTranslation()
  const [pending, setPending] = useState(selected)

  return (
    <div className="glass-card p-4 animate-[vPop_0.5s_cubic-bezier(0.22,1,0.36,1)_both]">
      <div className="text-[10px] font-semibold tracking-[0.1em] uppercase text-on-surface-muted mb-1.5">
        {t('budgetRange')}
      </div>
      <div className="flex flex-wrap gap-2" role="group" aria-label={t('intakeBudgetLabel')}>
        {options.map((label) => {
          const isSelected = pending === label
          return (
            <button
              key={label}
              type="button"
              aria-pressed={isSelected}
              disabled={disabled}
              onClick={() => setPending(label)}
              className={`px-3.5 py-2 rounded-full text-[12.5px] transition-all disabled:opacity-60 ${
                isSelected
                  ? 'bg-button text-on-button font-medium shadow-[0_4px_12px_-6px_rgb(var(--shadow-rgb)/0.6)]'
                  : 'glass-chip text-on-surface font-normal hover:bg-glass-3'
              }`}
            >
              {label}
            </button>
          )
        })}
      </div>
      <button
        type="button"
        className="mt-3 w-full py-2.5 rounded-[13px] bg-button text-on-button text-[13px] font-semibold tracking-[-0.12px] disabled:opacity-50"
        disabled={disabled || !pending}
        onClick={() => onCommit(pending)}
      >
        {t('confirmBudget')}
      </button>
    </div>
  )
}
