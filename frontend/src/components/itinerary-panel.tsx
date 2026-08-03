import { useRef } from 'react'
import { S } from '../strings'
import DayCard from './day-card'
import { formatTripDateRange } from '../lib/format-trip-dates'
import type { TripPlan } from '../types'

/**
 * ItineraryPanel — middle panel showing trip_plan once a hotel is picked.
 * Empty state before the first plan.
 * Renders: tabs, header, day-nav pills, hotel summary, day cards, adjustments.
 */
export default function ItineraryPanel({
  tripPlan,
  width,
}: {
  tripPlan: TripPlan | null
  width: number
}) {
  const dayRefs = useRef<Record<number, HTMLDivElement | null>>({})

  function scrollToDay(dayNumber: number) {
    dayRefs.current[dayNumber]?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  const tabs = (
    <div className="flex items-center justify-between px-4 pt-3 border-b border-border-subtle shrink-0">
      <div className="flex gap-6">
        <span className="text-sm font-semibold text-on-surface border-b-2 border-primary pb-2">
          {S.itineraryTabLabel}
        </span>
        <button
          type="button"
          className="text-sm text-on-surface-variant pb-2 opacity-60 cursor-not-allowed"
          disabled
          title={S.ideasTabLabel}
        >
          {S.ideasTabLabel}
        </button>
        <button
          type="button"
          className="text-sm text-on-surface-variant pb-2 opacity-60 cursor-not-allowed"
          disabled
          title={S.bookingsTabLabel}
        >
          {S.bookingsTabLabel}
        </button>
      </div>
      <button
        type="button"
        className="p-1 text-on-surface-variant opacity-60 cursor-not-allowed"
        disabled
        title="Toàn màn hình (chưa hỗ trợ)"
      >
        <span className="material-symbols-outlined text-[18px]" aria-hidden="true">
          open_in_full
        </span>
      </button>
    </div>
  )

  if (!tripPlan) {
    return (
      <aside
        className="bg-surface-background border-r border-border-subtle flex flex-col shrink-0"
        style={{ width }}
        aria-label={S.itineraryEmptyTitle}
      >
        {tabs}
        <div className="flex-1 overflow-y-auto custom-scrollbar p-4 flex items-center justify-center">
          <div className="text-center text-on-surface-variant">
            <span className="material-symbols-outlined text-4xl" aria-hidden="true">
              explore
            </span>
            <div className="font-medium text-on-surface mt-2">{S.itineraryEmptyTitle}</div>
            <div className="text-sm mt-1">{S.itineraryEmptyBody}</div>
          </div>
        </div>
      </aside>
    )
  }

  const { hotel, days = [], adjustments = [], status, destination, start_date, end_date, number_of_adults } =
    tripPlan
  const dateRange = formatTripDateRange(start_date, end_date)

  return (
    <aside
      className="bg-surface-background border-r border-border-subtle flex flex-col shrink-0"
      style={{ width }}
      aria-label={S.itineraryTitle}
    >
      {tabs}

      <div className="px-4 pt-4">
        <div className="flex items-center justify-between gap-2">
          <h1 className="font-display text-xl font-bold text-on-surface truncate">
            {destination || S.itineraryTitle}
          </h1>
          <div className="flex items-center gap-2 shrink-0">
            {status && (
              <span className="px-2 py-0.5 bg-primary-container text-on-primary-container text-xs font-medium rounded-full">
                {status}
              </span>
            )}
            <button
              type="button"
              className="p-1 text-on-surface-variant opacity-60 cursor-not-allowed"
              disabled
              title="Chỉnh sửa (chưa hỗ trợ)"
            >
              <span className="material-symbols-outlined text-[18px]" aria-hidden="true">
                edit
              </span>
            </button>
            <button
              type="button"
              className="p-1 text-on-surface-variant opacity-60 cursor-not-allowed"
              disabled
              title="Chia sẻ (chưa hỗ trợ)"
            >
              <span className="material-symbols-outlined text-[18px]" aria-hidden="true">
                share
              </span>
            </button>
          </div>
        </div>

        {(dateRange || number_of_adults != null) && (
          <div className="flex items-center gap-5 text-on-surface-variant text-sm bg-surface-muted p-3 rounded-lg border border-border-subtle/50 mt-3">
            {dateRange && (
              <span className="flex items-center gap-1.5">
                <span className="material-symbols-outlined text-[18px]" aria-hidden="true">
                  calendar_month
                </span>
                {dateRange}
              </span>
            )}
            {number_of_adults != null && (
              <span className="flex items-center gap-1.5">
                <span className="material-symbols-outlined text-[18px]" aria-hidden="true">
                  group
                </span>
                {number_of_adults} {S.guestsAdultsSuffix}
              </span>
            )}
          </div>
        )}
      </div>

      {/* Day-nav pills */}
      {days.length > 0 && (
        <div className="px-4 py-3 flex gap-2 overflow-x-auto custom-scrollbar shrink-0">
          {days.map((day) => (
            <button
              key={day.day_number}
              type="button"
              onClick={() => scrollToDay(day.day_number)}
              className="px-3 py-1 bg-surface-background border border-outline-variant text-secondary hover:bg-surface-muted rounded-full text-xs font-medium whitespace-nowrap transition-colors"
            >
              {S.dayLabel(day.day_number)}
            </button>
          ))}
          <button
            type="button"
            className="px-3 py-1 border border-outline-variant text-on-surface-variant rounded-full text-xs font-medium opacity-60 cursor-not-allowed"
            disabled
            title={S.addDayLabel}
            aria-label={S.addDayLabel}
          >
            +
          </button>
        </div>
      )}

      <div className="flex-1 overflow-y-auto custom-scrollbar p-4 flex flex-col gap-3">
        {/* Hotel summary */}
        {hotel && (
          <div className="bg-surface-muted rounded-lg p-4">
            <div className="text-xs font-medium text-on-surface-variant">{S.hotelLabel}</div>
            <div className="font-display font-semibold text-on-surface mt-0.5">{hotel.name}</div>
            {hotel.star_rating && (
              <div className="text-primary text-sm mt-0.5">{'★'.repeat(hotel.star_rating)}</div>
            )}
            {hotel.description && (
              <div className="text-sm text-on-surface-variant mt-1">{hotel.description}</div>
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
            <div className="text-xs font-medium text-on-surface-variant mb-2">
              {S.adjustmentsLabel}
            </div>
            <ul className="flex flex-col gap-1.5">
              {adjustments.map((adj, i) => (
                <li key={i} className="text-sm text-on-surface">
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
