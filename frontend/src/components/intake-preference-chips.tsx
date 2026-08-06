import { useTranslation } from 'react-i18next'
import { PREFERENCE_KEYS, type PreferenceKey } from '../lib/intake-options'

/**
 * IntakePreferenceChips — multi-select travel-interest chips (design
 * dc.html:278-288). Values are canonical PreferenceKeys; the displayed label
 * comes from i18n (`intake.preferenceOptions.<key>`), decoupled from the wire
 * values composeIntakeMessage() emits. The "find hotels" button submits.
 */
export default function IntakePreferenceChips({
  selected,
  onToggle,
  onSubmit,
  disabled,
}: {
  selected: PreferenceKey[]
  onToggle: (key: PreferenceKey) => void
  onSubmit: () => void
  disabled: boolean
}) {
  const { t } = useTranslation()

  return (
    <div className="glass-card p-3.5 animate-[vPop_0.5s_cubic-bezier(0.22,1,0.36,1)_both]">
      <div className="text-[10px] font-semibold tracking-[0.1em] uppercase text-on-surface-muted mb-2.5">
        {t('interests')}
      </div>
      <div className="flex flex-wrap gap-2" role="group" aria-label={t('intakePreferencesLabel')}>
        {PREFERENCE_KEYS.map((key) => {
          const on = selected.includes(key)
          return (
            <button
              key={key}
              type="button"
              aria-pressed={on}
              disabled={disabled}
              onClick={() => onToggle(key)}
              className={`px-3 py-2 rounded-full text-[12.5px] transition-all disabled:opacity-60 ${
                on
                  ? 'bg-button text-on-button border border-button font-medium'
                  : 'bg-glass-2 text-on-surface border border-fill2 font-normal'
              }`}
            >
              {t(`intake.preferenceOptions.${key}`)}
            </button>
          )
        })}
      </div>
      <button
        type="button"
        className={`mt-3 w-full py-2.5 rounded-[13px] text-[13px] font-semibold tracking-[-0.12px] transition-colors ${
          selected.length > 0 ? 'bg-button text-on-button' : 'bg-fill2 text-on-surface-faint'
        }`}
        disabled={disabled || selected.length === 0}
        onClick={onSubmit}
      >
        {t('findHotels')}
      </button>
    </div>
  )
}
