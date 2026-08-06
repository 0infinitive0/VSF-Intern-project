import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import IntakeChecklist from './intake-checklist'
import type { IntakeStatus } from '../types'

const STEP_NUMBERS = [1, 2, 3] as const

/**
 * StageIntake — the hero + live-collection checklist shown while the chat is
 * still gathering trip details (design V-OTA Planner.dc.html:88-126,
 * reference screenshot data/design/screenshots/sb.png).
 *
 * Structure: eyebrow tagline → 42px headline with the animated vHue gradient
 * span → sub-copy → IntakeChecklist (real IntakeStatus values) → three static
 * step-explainer cards. Gradient stops alias --acc/--ok/--warn (never
 * hardcoded #3A73DE/#2A9187/#C8802F) so the dark theme overrides apply. All
 * copy is translated; entrance is the design's vRise .75s.
 */
export default function StageIntake({
  intake,
}: {
  intake: IntakeStatus | null
}): ReactNode {
  const { t } = useTranslation()

  return (
    <div className="flex-1 min-w-0 overflow-y-auto custom-scrollbar flex p-[34px]">
      <div className="m-auto w-[min(640px,100%)] flex flex-col gap-[22px] animate-[vRise_0.75s_cubic-bezier(0.22,1,0.36,1)_both]">
        <div className="flex flex-col gap-3">
          <div className="text-[10px] font-[590] tracking-[0.1em] uppercase text-on-surface-muted">
            {t('intakeHeroTagline')}
          </div>
          <h1 className="text-[42px] font-[590] tracking-[-1.9px] leading-[1.06] text-on-surface text-pretty">
            {t('intakeHeroA')}{' '}
            <span
              className="font-[530] bg-clip-text text-transparent animate-[vHue_12s_ease-in-out_infinite]"
              style={{
                backgroundImage:
                  'linear-gradient(100deg, var(--color-primary), var(--color-success), var(--color-warning), var(--color-primary))',
                backgroundSize: '300% 100%',
              }}
            >
              {t('intakeHeroB')}
            </span>
          </h1>
          <p className="text-[14.5px] leading-[1.62] text-on-surface-variant max-w-[520px] text-pretty">
            {t('intakeHeroSub')}
          </p>
        </div>

        <IntakeChecklist intake={intake} />

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
          {STEP_NUMBERS.map((n) => (
            <div key={n} className="bg-glass-1 border border-edge rounded-[20px] p-3.5">
              <div
                className={`text-[10px] font-[590] tracking-[0.06em] ${
                  n === 1 ? 'text-primary' : 'text-on-surface-faint'
                }`}
              >
                {t(`intakeStep${n}Num`)}
              </div>
              <div className="text-[13px] font-[590] tracking-[-0.12px] mt-[5px]">
                {t(`intakeStep${n}Title`)}
              </div>
              <div className="text-[11.5px] font-[450] tracking-[0.005em] text-on-surface-muted mt-[3px] leading-[1.4]">
                {t(`intakeStep${n}Desc`)}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
