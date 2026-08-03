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
      className="hotel-card"
      disabled={disabled}
      onClick={() => onPick(String(hotel.index))}
      type="button"
    >
      <div className="hotel-card__header">
        <span className="hotel-card__index">{hotel.index}</span>
        <span className="hotel-card__name">{hotel.name}</span>
      </div>
      <div className="hotel-card__stars">{stars}</div>
      {hasStayPrice && (
        <div className="hotel-card__price" aria-label={S.hotelAverageNightly(formatPrice(hotel.average_nightly_price), currency)}>
          <strong>{S.hotelAverageNightly(formatPrice(hotel.average_nightly_price), currency)}</strong>
          {Number.isFinite(Number(hotel.total_stay_price)) && hotel.stay_night_count > 0 && (
            <span>{S.hotelTotalStay(hotel.stay_night_count, formatPrice(hotel.total_stay_price), currency)}</span>
          )}
        </div>
      )}
      {hotel.description && (
        <p className="hotel-card__desc">{hotel.description}</p>
      )}
      {hotel.matched_rooms && hotel.matched_rooms.length > 0 && (
        <>
          <div className="hotel-card__rooms-label">{S.hotelRooms}</div>
          <div className="hotel-card__rooms">
            {hotel.matched_rooms.map((room, i) => (
              <span key={i} className="hotel-card__room-tag">{room}</span>
            ))}
          </div>
        </>
      )}
      <div className="hotel-card__pick-btn">{S.hotelPickBtn}</div>
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
    <div className="hotel-cards">
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
