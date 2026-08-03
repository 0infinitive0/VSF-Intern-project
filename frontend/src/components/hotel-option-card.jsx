import { S } from '../strings.js'

/**
 * HotelOptionCard — shown when stage === "hotel_options".
 * Clicking sends String(hotel.index) as the next message, which is the ordinal
 * already expected by select_hotel on the backend — no new verb needed.
 */
function HotelOptionCard({ hotel, onPick, disabled }) {
  const stars = '★'.repeat(hotel.star_rating || 0) + '☆'.repeat(Math.max(0, 5 - (hotel.star_rating || 0)))
  const currency = hotel.currency || 'VND'
  const formatPrice = (value) => new Intl.NumberFormat('vi-VN', { maximumFractionDigits: 0 }).format(value)
  const hasStayPrice = Number.isFinite(Number(hotel.average_nightly_price))

  return (
    <button
      className="w-full text-left bg-surface-background border border-border-subtle rounded-lg p-4 flex flex-col gap-2 shadow-sm hover:shadow-md hover:border-primary/40 transition-shadow disabled:opacity-60"
      disabled={disabled}
      onClick={() => onPick(String(hotel.index))}
      type="button"
    >
      <div className="flex items-center gap-2">
        <span className="w-6 h-6 shrink-0 rounded-full bg-primary-container text-on-primary-container text-xs font-semibold flex items-center justify-center">
          {hotel.index}
        </span>
        <span className="font-display font-semibold text-text-primary">{hotel.name}</span>
      </div>
      <div className="text-primary text-sm">{stars}</div>
      {hasStayPrice && (
        <div
          className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-sm text-text-primary"
          aria-label={S.hotelAverageNightly(formatPrice(hotel.average_nightly_price), currency)}
        >
          <strong className="text-primary font-semibold">
            {S.hotelAverageNightly(formatPrice(hotel.average_nightly_price), currency)}
          </strong>
          {Number.isFinite(Number(hotel.total_stay_price)) && hotel.stay_night_count > 0 && (
            <span className="text-xs text-text-secondary">
              {S.hotelTotalStay(hotel.stay_night_count, formatPrice(hotel.total_stay_price), currency)}
            </span>
          )}
        </div>
      )}
      {hotel.description && (
        <p className="text-sm text-text-secondary">{hotel.description}</p>
      )}
      {hotel.matched_rooms && hotel.matched_rooms.length > 0 && (
        <>
          <div className="text-xs font-medium text-text-secondary mt-1">{S.hotelRooms}</div>
          <div className="flex flex-wrap gap-1.5">
            {hotel.matched_rooms.map((room, i) => (
              <span key={i} className="px-2 py-0.5 bg-surface-muted text-text-secondary text-xs rounded-full">
                {room}
              </span>
            ))}
          </div>
        </>
      )}
      <div className="mt-2 text-center text-sm font-medium text-primary border-t border-border-subtle pt-2">
        {S.hotelPickBtn}
      </div>
    </button>
  )
}

/**
 * HotelOptionCards — renders the full hotel list.
 * Shown *instead of* plain chips when stage === "hotel_options".
 * Both views post an ordinal as a plain message — same backend verb.
 */
export default function HotelOptionCards({ hotelOptions, onPick, disabled }) {
  if (!hotelOptions || hotelOptions.length === 0) return null

  return (
    <div className="flex flex-col gap-3">
      {hotelOptions.map((hotel) => (
        <HotelOptionCard
          key={hotel.index}
          hotel={hotel}
          onPick={onPick}
          disabled={disabled}
        />
      ))}
    </div>
  )
}
