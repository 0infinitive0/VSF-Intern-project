import { useTranslation } from 'react-i18next'
import MatchScoreRing from './match-score-ring'
import MatchReasons from './match-reasons'
import RemoteImage from './remote-image'
import { formatCurrency } from '../lib/format-currency'
import { formatHotelStars } from '../lib/format-stars'
import type { HotelOption } from '../types'

const PRICE_LOCALE = (lang: string) => (lang === 'vi' ? 'vi-VN' : 'en-US')

/**
 * HotelOptionCard — the full-design premium glass card (HotelCard.dc.html).
 * Three distinct click zones, exactly as the design intends:
 *   card body / "Xem chi tiết" → onOpen (opens Hotel Detail Focus Mode)
 *   "Chọn"                     → onSelect — marks the card LOCALLY only
 *                                (stopPropagation so it never opens the panel)
 *
 * Phase 8 two-step pick: marking here sends NOTHING to the backend. The only
 * sender is the stage header's confirm button in stage-hotels.tsx, which posts
 * String(hotel.index) over the exact same wire as before (no new verb).
 *
 * HotelOption.id only exists once Phase 2 ships — without it there is no
 * /hotels/{id} to fetch, so the card simply doesn't open (cursor + detail
 * button hidden) while everything else still renders.
 */
function HotelOptionCard({
  hotel,
  selected,
  focused,
  delay,
  nights,
  onSelect,
  onOpen,
}: {
  hotel: HotelOption
  selected: boolean
  focused: boolean
  delay: string
  nights: number | null
  onSelect: (hotel: HotelOption) => void
  onOpen: (hotel: HotelOption) => void
}) {
  const { t, i18n } = useTranslation()
  const numFmt = new Intl.NumberFormat(PRICE_LOCALE(i18n.language))
  const canOpen = Boolean(hotel.id)

  // null/undefined and 0 all mean "no price known" — hide the price block
  // instead of rendering "0 ₫" (Number() coercion turns null into 0, so the
  // explicit nullish check matters).
  const hasNightly =
    hotel.average_nightly_price != null &&
    Number.isFinite(hotel.average_nightly_price) &&
    hotel.average_nightly_price > 0
  const showTotal = hasNightly && nights != null && nights > 0

  const stars =
    formatHotelStars(hotel.star_rating || 0) +
    '☆'.repeat(Math.max(0, 5 - (hotel.star_rating || 0)))

  return (
    <div
      onClick={canOpen ? () => onOpen(hotel) : undefined}
      className="hotel-card rounded-[26px] p-4 border"
      data-selected={selected ? 'true' : undefined}
      data-focused={focused ? 'true' : undefined}
      style={{
        cursor: canOpen ? 'pointer' : 'default',
        animation: `vFade .55s ${delay} ease both`,
      }}
    >
      <div className="flex gap-3.5">
        <RemoteImage
          src={hotel.image_url}
          alt={t('hotelImgAlt', { name: hotel.name })}
          className="w-[112px] h-[112px] rounded-[20px] flex-none"
          sheen="vSheen 6s 1.2s ease-in-out infinite"
        />
        <div className="flex-1 min-w-0">
          <div className="flex items-start gap-2.5">
            <div className="flex-1 min-w-0">
              <div className="text-[16px] font-[590] tracking-[-0.32px] text-on-surface truncate">
                {hotel.name}
              </div>
              {hotel.area_name && (
                <div className="text-[11.5px] text-on-surface-muted font-normal mt-0.5">
                  {hotel.area_name}
                </div>
              )}
              <div className="flex items-center gap-2 mt-1.5">
                {hotel.star_rating != null && (
                  <div className="text-[11px] text-warning tracking-[1px]" aria-hidden="true">
                    {stars}
                  </div>
                )}
                {hotel.review_score != null && (
                  <div className="text-[11.5px] font-[590] text-on-surface">
                    {new Intl.NumberFormat(PRICE_LOCALE(i18n.language), {
                      minimumFractionDigits: 1,
                      maximumFractionDigits: 1,
                    }).format(hotel.review_score)}
                  </div>
                )}
                {hotel.review_count != null && (
                  <div className="text-[11px] text-on-surface-muted font-normal">
                    {t('hotelReviewCount', { count: numFmt.format(hotel.review_count) })}
                  </div>
                )}
              </div>
            </div>
            {hasNightly && (
              <div className="flex-none text-right">
                <div className="text-[17px] font-normal tracking-[-0.5px] text-on-surface">
                  {formatCurrency(hotel.average_nightly_price!, i18n.language)}
                </div>
                <div className="text-[10.5px] font-normal tracking-[0.01em] text-on-surface-muted">
                  {showTotal
                    ? t('hotelNightlyTotal', {
                        total: formatCurrency(hotel.average_nightly_price! * nights!, i18n.language),
                      })
                    : t('perNight')}
                </div>
              </div>
            )}
          </div>
          {hotel.amenities && hotel.amenities.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mt-[9px]">
              {hotel.amenities.map((amenity) => (
                <span
                  key={amenity}
                  className="text-[10.5px] px-[9px] py-[3px] rounded-full bg-fill text-on-surface-variant"
                >
                  {amenity}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>

      {(hotel.match_score != null || (hotel.match_reasons?.length ?? 0) > 0) && (
        <div className="flex gap-3.5 items-start mt-3.5 pt-3.5 border-t border-line">
          <MatchScoreRing score={hotel.match_score} />
          <div className="flex-1 min-w-0">
            <MatchReasons reasons={hotel.match_reasons} />
          </div>
        </div>
      )}

      <div className="flex gap-2 mt-[13px]">
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation()
            onSelect(hotel)
          }}
          className="flex-1 p-[11px] rounded-[15px] border-none text-[13px] font-[590] tracking-[-0.12px] cursor-pointer transition-all duration-200"
          style={{
            background: selected ? 'var(--btn)' : 'var(--fill)',
            color: selected ? 'var(--btn-fg)' : 'var(--t2)',
          }}
        >
          {selected ? t('hotelPickBtnSelected') : t('hotelPickBtn')}
        </button>
        {canOpen && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              onOpen(hotel)
            }}
            className="flex-none px-[15px] py-[11px] rounded-[15px] border border-stroke bg-glass-2 text-on-surface-variant text-[13px] font-[530] tracking-[-0.1px] cursor-pointer transition-all duration-200 hover:bg-glass-3 hover:text-on-surface"
          >
            {t('viewDetail')}
          </button>
        )}
      </div>
    </div>
  )
}

/**
 * HotelOptionCards — the controlled card list for the hotels stage. The stage
 * (stage-hotels.tsx) owns selectedIndex because the header confirm button
 * reads it: the selection is now user-meaningful state that lives long enough
 * to open details, compare, then commit — not a transient optimistic flash.
 * (This comment supersedes the pre-Phase-8 "transient" note; the wire itself
 * is unchanged: only the header confirm posts String(hotel.index).)
 */
export default function HotelOptionCards({
  hotels,
  selectedIndex,
  focusedId,
  nights,
  onSelect,
  onOpen,
}: {
  hotels: HotelOption[]
  selectedIndex: number | null
  focusedId?: string | null
  nights: number | null
  onSelect: (hotel: HotelOption) => void
  onOpen: (hotel: HotelOption) => void
}) {
  if (!hotels || hotels.length === 0) return null

  return (
    <>
      {hotels.map((hotel, i) => (
        <HotelOptionCard
          key={hotel.id ?? hotel.index}
          hotel={hotel}
          selected={selectedIndex === hotel.index}
          focused={focusedId != null && hotel.id === focusedId}
          delay={`${i * 90}ms`}
          nights={nights}
          onSelect={onSelect}
          onOpen={onOpen}
        />
      ))}
    </>
  )
}
