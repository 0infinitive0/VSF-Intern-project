import { useTranslation } from 'react-i18next'
import { buildIntakeChecklistRows } from '../lib/intake-checklist-rows'
import type { IntakeStatus } from '../types'

const ROW_LABEL_KEY = {
  destination: 'intakeRowDestination',
  people: 'intakeRowPeople',
  dates: 'intakeRowDates',
  budget: 'intakeRowBudget',
  preferences: 'intakeRowPreferences',
} as const

/**
 * IntakeChecklist — the "THÔNG TIN AI ĐANG THU THẬP" panel of the intake stage
 * (design V-OTA Planner.dc.html:96-111). Every row renders real IntakeStatus
 * data; uncollected rows show the design's literal "—" and never a guessed or
 * prefilled value (phase-07 acceptance criteria). Row derivation lives in the
 * pure lib/intake-checklist-rows.ts; this component only owns markup + i18n.
 *
 * Deliberate deviations from the design source:
 *  - No per-row edit affordance (`r.onPick`/`r.editLabel`): the stage has no
 *    send path in this phase, so a "Sửa" link would be an inert promise. The
 *    chat widgets remain the honest editing surface.
 *  - Preferences render as translated chips (canonical keys →
 *    intake.preferenceOptions.*) instead of one joined string — per phase-07.
 *  - Budget row is permanently "—": the frozen contract carries no chosen-tier
 *    field (see intake-checklist-rows.ts header). Not an omission — a contract
 *    decision recorded in the phase-07 plan.
 */
export default function IntakeChecklist({ intake }: { intake: IntakeStatus | null }) {
  const { t, i18n } = useTranslation()
  const rows = buildIntakeChecklistRows(intake, i18n.language)

  return (
    <div className="glass-panel rounded-[28px] p-5">
      <div className="text-[10px] font-[590] tracking-[0.1em] uppercase text-on-surface-muted mb-3.5">
        {t('intakeCollecting')}
      </div>
      <div className="flex flex-col">
        {rows.map((row) => (
          <div
            key={row.key}
            className="flex items-center gap-3 py-2.5 border-b border-line last:border-b-0"
          >
            <div
              aria-hidden="true"
              className={`w-[18px] h-[18px] flex-none rounded-full border-[1.5px] flex items-center justify-center text-[10px] transition-all duration-[350ms] ${
                row.collected
                  ? 'bg-primary border-primary text-on-primary'
                  : 'bg-transparent border-stroke text-transparent'
              }`}
            >
              ✓
            </div>
            <div className="flex-none w-[104px] text-[12.5px] text-on-surface-muted">
              {t(ROW_LABEL_KEY[row.key])}
            </div>
            <div
              className={`flex-1 text-[13.5px] transition-colors duration-300 ${
                row.collected ? 'text-on-surface' : 'text-on-surface-muted'
              }`}
            >
              {row.key === 'preferences' && row.collected ? (
                <span className="flex flex-wrap gap-1.5">
                  {row.preferenceKeys.map((key) => (
                    <span
                      key={key}
                      className="px-2.5 py-0.5 rounded-full bg-fill text-on-surface-variant text-[11.5px]"
                    >
                      {t(`intake.preferenceOptions.${key}`, { defaultValue: key })}
                    </span>
                  ))}
                </span>
              ) : (
                (row.value ?? '—')
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
