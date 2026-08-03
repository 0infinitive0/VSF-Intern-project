import { forwardRef } from 'react'
import { S } from '../strings'
import type { Day, DayItem } from '../types'

// Accent color cycled per day, matching the Trip.com-style route markers.
const DAY_ACCENTS = ['#0047dd', '#00a6ed', '#00d084', '#9575cd', '#ff8a65']

// The 7 real ItemKind values (src/services/trip_edit_planner.py:31) → icon + label.
// Anything outside this set (null, unknown, future backend additions) gets no
// badge — never a guessed default.
const KIND_MAP: Record<string, { icon: string; label: string }> = {
  breakfast: { icon: 'egg_alt', label: S.kindBreakfast },
  lunch: { icon: 'lunch_dining', label: S.kindLunch },
  dinner: { icon: 'dinner_dining', label: S.kindDinner },
  coffee: { icon: 'coffee', label: S.kindCoffee },
  attraction: { icon: 'attractions', label: S.kindAttraction },
  rest: { icon: 'hotel', label: S.kindRest },
  evening: { icon: 'nightlife', label: S.kindEvening },
}

/**
 * DayCard — one day of the trip plan with a timeline of activities.
 */
const DayCard = forwardRef<HTMLDivElement, { day: Day }>(function DayCard({ day }, ref) {
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
          {S.dayLabel(day.day_number)}
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
  const kind = item.kind && KIND_MAP[item.kind] ? KIND_MAP[item.kind] : null

  return (
    <div className="flex gap-3">
      <div className="w-20 h-20 rounded-lg bg-surface-muted shrink-0 flex items-center justify-center">
        <span className="material-symbols-outlined text-on-surface-variant" aria-hidden="true">
          {kind?.icon ?? 'place'}
        </span>
      </div>
      <div className="flex-1 min-w-0">
        <span className="text-[11px] text-on-surface-variant uppercase font-semibold">
          {item.start_time}
          {item.end_time && item.end_time !== item.start_time && ` – ${item.end_time}`}
        </span>
        <h4 className="text-sm text-on-surface mt-1 font-medium">{item.activity}</h4>
        {kind && (
          <span className="inline-block mt-1.5 bg-surface-container-high text-on-surface-variant text-[11px] px-2.5 py-1 rounded-md">
            {kind.label}
          </span>
        )}
      </div>
    </div>
  )
}

export default DayCard
