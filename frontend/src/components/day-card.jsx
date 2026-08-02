import { forwardRef } from 'react'
import { S } from '../strings.js'

// Accent color cycled per day, matching the Trip.com-style route markers.
const DAY_ACCENTS = ['#0047dd', '#00a6ed', '#00d084', '#9575cd', '#ff8a65']

/**
 * DayCard — one day of the trip plan with a timeline of activities.
 */
const DayCard = forwardRef(function DayCard({ day }, ref) {
  const accent = DAY_ACCENTS[(day.day_number - 1) % DAY_ACCENTS.length]

  return (
    <div
      ref={ref}
      className="bg-surface-background border border-border-subtle rounded-lg p-4 shadow-[0_2px_8px_rgba(0,0,0,0.02)] hover:shadow-md transition-shadow relative overflow-hidden"
    >
      <div
        className="absolute left-0 top-0 bottom-0 w-1"
        style={{ backgroundColor: accent }}
        aria-hidden="true"
      />
      <div className="mb-3">
        <div className="font-display font-semibold text-text-primary">
          {S.dayLabel(day.day_number)}
        </div>
        {day.theme && <div className="text-sm text-text-secondary mt-0.5">{day.theme}</div>}
      </div>
      <div className="flex flex-col gap-3">
        {(day.items || []).map((item, i) => (
          <div key={i} className="flex gap-3">
            <div className="w-14 shrink-0 text-xs text-text-secondary text-right pt-0.5">
              {item.start_time}
              {item.end_time && item.end_time !== item.start_time && (
                <div className="text-text-secondary/70">{item.end_time}</div>
              )}
            </div>
            <div
              className="w-2 h-2 rounded-full mt-1.5 shrink-0"
              style={{ backgroundColor: accent }}
            />
            <div className="text-sm text-text-primary">{item.activity}</div>
          </div>
        ))}
      </div>
    </div>
  )
})

export default DayCard
