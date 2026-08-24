import { useTranslation } from 'react-i18next'
import { buildMatchReasonLines } from '../lib/match-reason-lines'
import { displayAmenityLabels } from '../lib/hotel-filters'
import type { AmenityCatalogOption, MatchReason } from '../types'

/**
 * MatchReasons — the "AI đề xuất vì..." bullet list, built from the backend's
 * raw match_reasons[] codes through the matchReason.* i18n catalog. Unknown
 * codes never leak as raw strings (buildMatchReasonLines drops them). Used on
 * the hotel card (11.5px/--t2, 4px --t4 dots) and the detail panel's accent
 * panel (13px/--t2, 5px --acc dots) via the `variant` prop.
 */
export default function MatchReasons({
  reasons,
  amenityOptions = [],
  variant = 'card',
}: {
  reasons?: MatchReason[] | null
  amenityOptions?: AmenityCatalogOption[]
  variant?: 'card' | 'panel'
}) {
  const { t, i18n } = useTranslation()
  const lines = buildMatchReasonLines(
    reasons,
    (amenityId) => displayAmenityLabels([amenityId], amenityOptions, i18n.language)[0] ?? amenityId,
  )
  if (lines.length === 0) return null

  // Numeric values (ratings, star counts) honour the UI locale too — "9,2/10"
  // in vi, "9.2/10" in en — same rule as every other number on screen.
  const numFmt = new Intl.NumberFormat(i18n.language === 'vi' ? 'vi-VN' : 'en-US', {
    maximumFractionDigits: 1,
  })
  const fmtValue = (value: string | number) =>
    typeof value === 'number' ? numFmt.format(value) : value

  const panel = variant === 'panel'
  return (
    <div className={`flex flex-col ${panel ? 'gap-[7px]' : 'gap-1'}`}>
      {lines.map((line) => (
        <div key={line.code} className="flex items-start" style={{ gap: panel ? 9 : 7 }}>
          <div
            className={`rounded-full flex-none ${panel ? 'bg-primary' : 'bg-on-surface-faint'}`}
            style={{ width: panel ? 5 : 4, height: panel ? 5 : 4, marginTop: panel ? 7 : 6 }}
            aria-hidden="true"
          />
          <div
            className={`text-on-surface-variant font-normal text-pretty ${
              panel ? 'text-[13px] leading-[1.55]' : 'text-[11.5px] leading-[1.45]'
            }`}
          >
            {t(`matchReason.${line.code}`, { value: fmtValue(line.value) })}
          </div>
        </div>
      ))}
    </div>
  )
}
