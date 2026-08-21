import { useTranslation } from 'react-i18next'
import MatchScoreRing from './match-score-ring'
import MatchReasons from './match-reasons'
import RemoteImage from './remote-image'
import { formatCurrency } from '../lib/format-currency'
import { formatHotelStars } from '../lib/format-stars'
import { displayAmenityLabels } from '../lib/hotel-filters'
import { hotelOptionSyncId } from '../lib/map-sync-id'
import type { AmenityCatalogOption, HotelOption } from '../types'

const PRICE_LOCALE = (lang: string) => (lang === 'vi' ? 'vi-VN' : 'en-US')

/**
 * HotelOptionCard — the full-design premium glass card (HotelCard.dc.html).
 * Four distinct click zones:
 *   card body     → no action (selection and detail have their own explicit controls)
 *   "Xem chi tiết"→ onOpen (opens Hotel Detail Focus Mode directly, bypassing preview)
 *   "Chọn"        → onSelect — marks the card LOCALLY only
 *                   (stopPropagation so it never triggers a preview)
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
  hotelAmenities,
  onOpen,
  hovered,
  onHoverChange,
}: {
  hotel: HotelOption
  selected: boolean
  focused: boolean
  delay: string
  nights: number | null
  hotelAmenities: AmenityCatalogOption[]
  onOpen: (hotel: HotelOption) => void
  /** Phase 10 map hover sync — optional so this component still works standalone. */
  hovered?: boolean
  onHoverChange?: (id: string | null) => void
}) {
  const { t, i18n } = useTranslation()
  const numFmt = new Intl.NumberFormat(PRICE_LOCALE(i18n.language))
  const canOpen = Boolean(hotel.id)
  const syncId = hotelOptionSyncId(hotel)
  const displayAmenities = displayAmenityLabels(hotel.display_amenities, hotelAmenities, i18n.language)

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
      className="hotel-card rounded-[26px] p-4 border"
      data-selected={selected ? 'true' : undefined}
      data-focused={focused ? 'true' : undefined}
      data-hovered={hovered ? 'true' : undefined}
      data-card={syncId}
      role={canOpen ? 'button' : undefined}
      tabIndex={canOpen ? 0 : undefined}
      onClick={() => {
        if (canOpen) onOpen(hotel)
      }}
      onKeyDown={(e) => {
        if (canOpen && (e.key === 'Enter' || e.key === ' ')) {
          e.preventDefault()
          onOpen(hotel)
        }
      }}
      onMouseEnter={() => onHoverChange?.(syncId)}
      onMouseLeave={() => onHoverChange?.(null)}
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
                  {showTotal
                    ? formatCurrency(hotel.average_nightly_price! * nights!, i18n.language)
                    : formatCurrency(hotel.average_nightly_price!, i18n.language)}
                </div>
                <div className="text-[10.5px] font-normal tracking-[0.01em] text-on-surface-muted">
                  {showTotal
                    ? t('hotelNightlyTotal', {
                        nightly: formatCurrency(hotel.average_nightly_price!, i18n.language),
                      })
                    : t('perNight')}
                </div>
              </div>
            )}
          </div>
          {displayAmenities.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mt-[9px]">
              {displayAmenities.map((amenity) => (
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

      <div className="flex items-center justify-between mt-3 pt-2.5 border-t border-line/60 text-[11.5px]">
        <span className="text-on-surface-muted flex items-center gap-1">
          <span className="material-symbols-outlined text-[14px] text-primary" aria-hidden="true">touch_app</span>
          <span>{t('hotelCardActionHint')}</span>
        </span>
        <span className="font-[590] text-primary flex items-center gap-0.5">
          <span>{t('hotelCardSelectRooms')}</span>
          <span className="material-symbols-outlined text-[14px]" aria-hidden="true">arrow_forward</span>
        </span>
      </div>
    </div>
  )
}

/**
 * HotelOptionCards — the controlled card list for the hotels stage.
 */
export default function HotelOptionCards({
  hotels,
  selectedIndex,
  focusedId,
  nights,
  hotelAmenities,
  onOpen,
  hoveredId,
  onHoverChange,
}: {
  hotels: HotelOption[]
  selectedIndex: number | null
  focusedId?: string | null
  nights: number | null
  hotelAmenities: AmenityCatalogOption[]
  onOpen: (hotel: HotelOption) => void
  /** Phase 10 map hover sync (lib/map-sync-id.ts ids) — optional so this component still works standalone. */
  hoveredId?: string | null
  onHoverChange?: (id: string | null) => void
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
          hotelAmenities={hotelAmenities}
          onOpen={onOpen}
          hovered={hoveredId != null && hoveredId === hotelOptionSyncId(hotel)}
          onHoverChange={onHoverChange}
        />
      ))}
    </>
  )
}
