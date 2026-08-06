import { useTranslation } from 'react-i18next'

/**
 * IntakeDestinationChips — "quick hint" destination picker (design dc.html:203-212).
 * Renders intake.available_destinations as tappable glass chips. Picking one
 * immediately fills the field (single-tap, no extra confirm — matches the
 * design's `destOptions` onPick which answers right away).
 */
export default function IntakeDestinationChips({
  destinations,
  selected,
  onPick,
  disabled,
}: {
  destinations: string[]
  selected: string
  onPick: (value: string) => void
  disabled: boolean
}) {
  const { t } = useTranslation()

  if (destinations.length === 0) return null

  return (
    <div className="flex flex-col gap-2 animate-[vPop_0.5s_cubic-bezier(0.22,1,0.36,1)_both]">
      <div className="text-[10.5px] text-on-surface-muted pl-1">{t('intakeQuickHint')}</div>
      <div className="flex flex-wrap gap-2" role="group" aria-label={t('intakeDestinationLabel')}>
        {destinations.map((name) => {
          const isSelected = selected === name
          return (
            <button
              key={name}
              type="button"
              aria-pressed={isSelected}
              disabled={disabled}
              onClick={() => onPick(name)}
              className={`px-[13px] py-2 rounded-full text-[12.5px] transition-all disabled:opacity-60 ${
                isSelected
                  ? 'bg-primary text-on-primary border border-primary shadow-[0_4px_12px_-6px_rgb(var(--shadow-rgb)/0.6)]'
                  : 'bg-glass-2 border border-stroke text-on-surface hover:bg-primary hover:text-on-primary hover:border-primary hover:-translate-y-0.5'
              }`}
            >
              {name}
            </button>
          )
        })}
      </div>
    </div>
  )
}
