import { forwardRef } from 'react'
import { useTranslation } from 'react-i18next'
import type { Day, DayItem } from '../types'

// Accent color cycled per day, matching the Trip.com-style route markers.
const DAY_ACCENTS = ['#0047dd', '#00a6ed', '#00d084', '#9575cd', '#ff8a65']

// The 7 real ItemKind values (src/services/trip_edit_planner.py:31) → icon.
// Labels resolve through the i18n catalog at render time.
const KIND_ICON_MAP: Record<string, string> = {
  breakfast: 'egg_alt',
  lunch: 'lunch_dining',
  dinner: 'dinner_dining',
  coffee: 'coffee',
  attraction: 'attractions',
  rest: 'hotel',
  evening: 'nightlife',
}

const KIND_LABEL_KEY: Record<string, string> = {
  breakfast: 'kindBreakfast',
  lunch: 'kindLunch',
  dinner: 'kindDinner',
  coffee: 'kindCoffee',
  attraction: 'kindAttraction',
  rest: 'kindRest',
  evening: 'kindEvening',
}

/**
 * DayCard — one day of the trip plan with a timeline of activities.
 */
const DayCard = forwardRef<HTMLDivElement, { day: Day }>(function DayCard({ day }, ref) {
  const { t } = useTranslation()
  const accent = DAY_ACCENTS[(day.day_number - 1) % DAY_ACCENTS.length]

  return (
    <div
      ref={ref}
      className="bg-surface-background border border-border-subtle rounded-lg p-4 shadow-[0_2px_8px_rgba(0,0,0,0.02)] hover:shadow-md transition-shadow relative overflow-hidden shrink-0"
    >
      <div
        className="absolute left-0 top-0 bottom-0 w-1"
        style={{ backgroundColor: accent }}
        aria-hidden="true"
      />
      <div className="mb-3">
        <div className="font-display font-semibold text-on-surface">
          {t('dayLabel', { n: day.day_number })}
        </div>
        {day.theme && <div className="text-sm text-on-surface-variant mt-0.5">{day.theme}</div>}
      </div>
      <div className="flex flex-col gap-4">
        {(day.items || []).map((item, i) => (
          <ActivityRow key={i} item={item} />
        ))}
      </div>
    </div>
  )
})

function ActivityRow({ item }: { item: DayItem }) {
  const { t } = useTranslation()
  const icon = item.kind ? KIND_ICON_MAP[item.kind] : null
  const labelKey = item.kind ? KIND_LABEL_KEY[item.kind] : null

  return (
    <div className="flex gap-3">
      <div className="w-20 h-20 rounded-lg bg-surface-muted shrink-0 flex items-center justify-center">
        <span className="material-symbols-outlined text-on-surface-variant" aria-hidden="true">
          {icon ?? 'place'}
        </span>
      </div>
      <div className="flex-1 min-w-0">
        <span className="text-[11px] text-on-surface-variant uppercase font-semibold">
          {item.start_time}
          {item.end_time && item.end_time !== item.start_time && ` – ${item.end_time}`}
        </span>
        <h4 className="text-sm text-on-surface mt-1 font-medium">{item.activity}</h4>
        {labelKey && (
          <span className="inline-block mt-1.5 bg-surface-container-high text-on-surface-variant text-[11px] px-2.5 py-1 rounded-md">
            {t(labelKey)}
          </span>
        )}
      </div>
    </div>
  )
}

export default DayCard
