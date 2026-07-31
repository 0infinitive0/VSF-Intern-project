import { S } from '../strings.js'
import DayCard from './day-card.jsx'

/**
 * ItineraryPanel — right-side panel showing trip_plan once a hotel is picked.
 * Empty state before the first plan.
 * Renders: hotel summary, status badge, day cards, adjustments.
 */
export default function ItineraryPanel({ tripPlan }) {
  if (!tripPlan) {
    return (
      <aside className="itinerary-panel" aria-label={S.itineraryEmptyTitle}>
        <div className="itinerary-panel__header">
          <span className="itinerary-panel__header-icon">🗺️</span>
          {S.itineraryTitle}
        </div>
        <div className="itinerary-panel__scroll">
          <div className="itinerary-empty">
            <div className="itinerary-empty__icon">📋</div>
            <div className="itinerary-empty__title">{S.itineraryEmptyTitle}</div>
            <div className="itinerary-empty__body">{S.itineraryEmptyBody}</div>
          </div>
        </div>
      </aside>
    )
  }

  const { hotel, days = [], adjustments = [], status } = tripPlan

  return (
    <aside className="itinerary-panel" aria-label={S.itineraryTitle}>
      <div className="itinerary-panel__header">
        <span className="itinerary-panel__header-icon">🗺️</span>
        {S.itineraryTitle}
        {status && (
          <span className="status-badge" style={{ marginLeft: 'auto' }}>
            {status}
          </span>
        )}
      </div>

      <div className="itinerary-panel__scroll">
        {/* Hotel summary */}
        {hotel && (
          <div className="hotel-summary">
            <div className="hotel-summary__label">{S.hotelLabel}</div>
            <div className="hotel-summary__name">{hotel.name}</div>
            {hotel.star_rating && (
              <div className="hotel-summary__stars">
                {'★'.repeat(hotel.star_rating)}
              </div>
            )}
            {hotel.description && (
              <div className="hotel-summary__desc">{hotel.description}</div>
            )}
          </div>
        )}

        {/* Day cards */}
        {days.map((day) => (
          <DayCard key={day.day_number} day={day} />
        ))}

        {/* Adjustments */}
        {adjustments.length > 0 && (
          <div className="adjustments">
            <div className="adjustments__label">{S.adjustmentsLabel}</div>
            <ul className="adjustments__list">
              {adjustments.map((adj, i) => (
                <li key={i} className="adjustments__item">{adj}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </aside>
  )
}
