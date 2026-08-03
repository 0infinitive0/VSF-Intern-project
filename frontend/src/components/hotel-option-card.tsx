import { useEffect, useState } from 'react'
import { S } from '../strings'
import type { HotelOption } from '../types'

/**
 * HotelOptionCard — shown when stage === "hotel_options".
 * Clicking sends String(hotel.index) as the next message, which is the ordinal
 * already expected by select_hotel on the backend — no new verb needed.
 */
function HotelOptionCard({
  hotel,
  onPick,
  disabled,
  selected,
}: {
  hotel: HotelOption
  onPick: (value: string) => void
  disabled: boolean
  selected: boolean
}) {
  const stars =
    '★'.repeat(hotel.star_rating || 0) + '☆'.repeat(Math.max(0, 5 - (hotel.star_rating || 0)))
  const currency = hotel.currency || 'VND'
  const formatPrice = (value: number) =>
    new Intl.NumberFormat('vi-VN', { maximumFractionDigits: 0 }).format(value)
  const hasStayPrice = Number.isFinite(Number(hotel.average_nightly_price))

  return (
    <div
      className={`relative bg-surface-background border rounded-xl p-3 transition-shadow ${
        selected ? 'border-primary ring-1 ring-primary' : 'border-outline-variant hover:shadow-md'
      }`}
    >
      {selected && (
        <span
          className="material-symbols-outlined absolute -top-2 -right-2 text-primary bg-surface-background rounded-full text-[20px]"
          aria-hidden="true"
        >
          check_circle
        </span>
      )}
      <div className="flex gap-3">
        <div className="w-16 h-16 rounded-lg bg-surface-container-high shrink-0 flex items-center justify-center">
          <span className="material-symbols-outlined text-on-surface-variant" aria-hidden="true">
            hotel
          </span>
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="w-5 h-5 shrink-0 rounded-full bg-primary-container text-on-primary-container text-[10px] font-semibold flex items-center justify-center">
              {hotel.index}
            </span>
            <span className="font-display font-medium text-sm text-on-surface truncate">
              {hotel.name}
            </span>
          </div>
          <div className="text-xs text-primary mt-1">{stars}</div>
          {hasStayPrice && (
            <div
              className="text-sm text-on-surface mt-1"
              aria-label={S.hotelAverageNightly(formatPrice(hotel.average_nightly_price!), currency)}
            >
              {S.hotelAverageNightly(formatPrice(hotel.average_nightly_price!), currency)}
              {Number.isFinite(Number(hotel.total_stay_price)) && (hotel.stay_night_count ?? 0) > 0 && (
                <span className="text-xs text-on-surface-variant ml-1">
                  ({S.hotelTotalStay(hotel.stay_night_count!, formatPrice(hotel.total_stay_price!), currency)})
                </span>
              )}
            </div>
          )}
          {hotel.matched_rooms && hotel.matched_rooms.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-1.5">
              {hotel.matched_rooms.map((room, i) => (
                <span
                  key={i}
                  className="px-2 py-0.5 bg-surface-muted text-on-surface-variant text-[10px] rounded-full"
                >
                  {room}
                </span>
              ))}
            </div>
          )}
          <button
            className="mt-2 bg-surface-container-high text-on-surface px-3 py-1 rounded-md text-xs hover:bg-primary hover:text-on-primary disabled:opacity-60 transition-colors"
            disabled={disabled}
            onClick={() => onPick(String(hotel.index))}
            type="button"
          >
            {S.hotelPickBtn}
          </button>
        </div>
      </div>
    </div>
  )
}

/**
 * HotelOptionCards — renders the full hotel list.
 * Shown *instead of* plain chips when stage === "hotel_options".
 * Both views post an ordinal as a plain message — same backend verb.
 *
 * `selectedIndex` is a transient, optimistic UI state — hotel_options clears
 * on the next turn regardless of outcome, so there is no server-backed
 * "selected" concept to persist here.
 */
export default function HotelOptionCards({
  hotelOptions,
  onPick,
  disabled,
}: {
  hotelOptions: HotelOption[]
  onPick: (value: string) => void
  disabled: boolean
}) {
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null)

  useEffect(() => {
    setSelectedIndex(null)
  }, [hotelOptions])

  if (!hotelOptions || hotelOptions.length === 0) return null

  function handlePick(hotel: HotelOption) {
    setSelectedIndex(hotel.index)
    onPick(String(hotel.index))
  }

  return (
    <div className="flex flex-col gap-3">
      {hotelOptions.map((hotel) => (
        <HotelOptionCard
          key={hotel.index}
          hotel={hotel}
          onPick={() => handlePick(hotel)}
          disabled={disabled}
          selected={selectedIndex === hotel.index}
        />
      ))}
    </div>
  )
}
