import { useRef } from 'react'
import { S } from '../strings.js'
import DayCard from './day-card.jsx'

/**
 * ItineraryPanel — middle panel showing trip_plan once a hotel is picked.
 * Empty state before the first plan.
 * Renders: header, day-nav pills, hotel summary, day cards, adjustments.
 */
export default function ItineraryPanel({ tripPlan }) {
  const dayRefs = useRef({})

  function scrollToDay(dayNumber) {
    dayRefs.current[dayNumber]?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  if (!tripPlan) {
    return (
      <aside
        className="w-[420px] bg-surface-background border-r border-border-subtle flex flex-col shrink-0"
        aria-label={S.itineraryEmptyTitle}
      >
        <div className="px-4 py-3 border-b border-border-subtle font-display font-semibold text-text-primary">
          {S.itineraryTitle}
        </div>
        <div className="flex-1 overflow-y-auto custom-scrollbar p-4 flex items-center justify-center">
          <div className="text-center text-text-secondary">
            <div className="text-3xl mb-2" aria-hidden="true">📋</div>
            <div className="font-medium text-text-primary">{S.itineraryEmptyTitle}</div>
            <div className="text-sm mt-1">{S.itineraryEmptyBody}</div>
          </div>
        </div>
      </aside>
    )
  }

  const { hotel, days = [], adjustments = [], status } = tripPlan

  return (
    <aside
      className="w-[420px] bg-surface-background border-r border-border-subtle flex flex-col shrink-0"
      aria-label={S.itineraryTitle}
    >
      <div className="px-4 py-3 border-b border-border-subtle flex items-center justify-between">
        <span className="font-display font-semibold text-text-primary">{S.itineraryTitle}</span>
        {status && (
          <span className="px-2 py-0.5 bg-primary-container text-on-primary-container text-xs font-medium rounded-full">
            {status}
          </span>
        )}
      </div>

      {/* Day-nav pills */}
      {days.length > 0 && (
        <div className="px-4 py-2 flex gap-2 overflow-x-auto custom-scrollbar shrink-0 border-b border-border-subtle">
          {days.map((day) => (
            <button
              key={day.day_number}
              type="button"
              onClick={() => scrollToDay(day.day_number)}
              className="px-3 py-1 bg-surface-background border border-border-subtle text-text-secondary hover:bg-surface-muted rounded-full text-xs font-medium whitespace-nowrap transition-colors"
            >
              {S.dayLabel(day.day_number)}
            </button>
          ))}
        </div>
      )}

      <div className="flex-1 overflow-y-auto custom-scrollbar p-4 flex flex-col gap-3">
        {/* Hotel summary */}
        {hotel && (
          <div className="bg-surface-muted rounded-lg p-4">
            <div className="text-xs font-medium text-text-secondary">{S.hotelLabel}</div>
            <div className="font-display font-semibold text-text-primary mt-0.5">{hotel.name}</div>
            {hotel.star_rating && (
              <div className="text-primary text-sm mt-0.5">{'★'.repeat(hotel.star_rating)}</div>
            )}
            {hotel.description && (
              <div className="text-sm text-text-secondary mt-1">{hotel.description}</div>
            )}
          </div>
        )}

        {/* Day cards */}
        {days.map((day) => (
          <DayCard
            key={day.day_number}
            day={day}
            ref={(el) => {
              dayRefs.current[day.day_number] = el
            }}
          />
        ))}

        {/* Adjustments */}
        {adjustments.length > 0 && (
          <div className="bg-surface-muted rounded-lg p-4">
            <div className="text-xs font-medium text-text-secondary mb-2">{S.adjustmentsLabel}</div>
            <ul className="flex flex-col gap-1.5">
              {adjustments.map((adj, i) => (
                <li key={i} className="text-sm text-text-primary">
                  • {adj}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </aside>
  )
}
