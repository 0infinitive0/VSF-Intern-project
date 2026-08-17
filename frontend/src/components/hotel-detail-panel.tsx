import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import MatchReasons from './match-reasons'
import MatchScoreRing from './match-score-ring'
import RemoteImage from './remote-image'
import RoomCard from './room-card'
import { useHotelDetail } from '../hooks/use-hotel-detail'
import { formatCurrency } from '../lib/format-currency'
import { displayAmenityLabels } from '../lib/hotel-filters'
import { formatHotelStars } from '../lib/format-stars'
import { formatSourcePlatform } from '../lib/format-source-platform'
import type { AmenityCatalogOption, HotelOption } from '../types'

const NUM_LOCALE = (lang: string) => (lang === 'vi' ? 'vi-VN' : 'en-US')

const SECTION_EYEBROW =
  'text-[10px] font-[590] tracking-[0.1em] uppercase text-on-surface-muted mb-[9px]'

/**
 * HotelDetailPanel — the third flex sibling of the hotels split view (list |
 * map | detail). NOT a modal, NOT an overlay: it is a real layout column, per
 * Hotel Detail Focus.md, and per the phase-8 checklist it shares the ChatPanel
 * surface (bg --g1, blur 32, radius 26 — the glass-panel utility).
 *
 * Data sources are deliberately split:
 *   - option (HotelOption): match_score / match_reasons — they belong to the
 *     RANKING, so they come from the list payload, not the detail endpoint;
 *   - GET /hotels/{id} via useHotelDetail: everything else, cached per id.
 *
 * Every section with no data hides entirely — no empty headings. Removed from
 * the design on purpose (plan.md "Phần chưa làm" #17/#18/#21, phase-08): no
 * top-reviews block, no contact block, no "Phòng đã chọn" cell, and no
 * duration column in the distances list (km only, formatted from distance_km
 * — never the DB's pre-formatted VI distance_text).
 */
export default function HotelDetailPanel({
  hotelId,
  option,
  hotelAmenities,
  selectedAmenityIds,
  onClose,
}: {
  /** null while no hotel has ever been focused yet this session (the caller
   * keeps mounting this component always — see stage-hotels.tsx's
   * lastFocusedId — so this only happens transiently, before the first open). */
  hotelId: string | null
  option?: HotelOption
  /** Shared catalog returned alongside the current hotel list. */
  hotelAmenities: AmenityCatalogOption[]
  /** Canonical amenity filters currently active in the hotel list. */
  selectedAmenityIds: string[]
  onClose: () => void
}) {
  const { t, i18n } = useTranslation()
  const { detail, status } = useHotelDetail(hotelId)
  // "Chọn phòng" is display-only (see room-card.tsx's doc comment) — one pick
  // per hotel, keyed by hotelId so it survives closing/reopening the SAME
  // hotel (matches the design's `state.rooms[hid]`, which never resets it
  // either) while a different hotel naturally shows nothing picked.
  const [roomPicks, setRoomPicks] = useState<Record<string, string>>({})
  const [expandedAmenitiesHotelId, setExpandedAmenitiesHotelId] = useState<string | null>(null)

  if (hotelId == null) return <div className="flex-1 min-w-0" />
  const numFmt = new Intl.NumberFormat(NUM_LOCALE(i18n.language))

  const heroSrc = detail?.image_url ?? detail?.images?.[0] ?? option?.image_url
  const name = detail?.name ?? option?.name ?? ''
  const areaName = detail?.area_name ?? option?.area_name
  const starRating = detail?.star_rating ?? option?.star_rating
  // Number(x) coerces null → 0, so never wrap: null/undefined and 0 both mean
  // "no price" — hide the cell entirely rather than render "0 ₫ / đêm".
  const hasLowestPrice =
    detail?.lowest_price != null && Number.isFinite(detail.lowest_price) && detail.lowest_price > 0

  const distanceRows = (detail?.nearby_attractions ?? []).filter(
    (place) => place && typeof place === 'object' && place.name,
  )
  const amenities =
    detail?.amenities && detail.amenities.length > 0
      ? detail.amenities
      : detail?.amenity_groups
        ? // `amenity_groups` is a crawled jsonb column typed `dict[str, Any]`:
          // narrow at runtime rather than assuming string[] and rendering
          // `[object Object]` the first time a row disagrees.
          Object.values(detail.amenity_groups)
            .flat()
            .filter((value): value is string => typeof value === 'string')
        : []
  const labelForAmenity = (amenityId: string) =>
    displayAmenityLabels([amenityId], hotelAmenities, i18n.language)[0] ?? amenityId
  const displayAmenityIds = [...new Set(option?.display_amenities ?? [])]
  const allAmenityIds = [...new Set([
    ...displayAmenityIds,
    ...(option?.amenities ?? []),
    ...amenities,
  ])]
  const displayAmenityItems = displayAmenityIds.map((id) => ({ id, label: labelForAmenity(id) }))
  const allAmenityItems = allAmenityIds
    .map((id) => ({ id, label: labelForAmenity(id) }))
    .sort((left, right) => left.label.localeCompare(right.label, i18n.language.startsWith('vi') ? 'vi' : 'en'))
  const amenitiesExpanded = expandedAmenitiesHotelId === hotelId
  const visibleAmenityItems = amenitiesExpanded || displayAmenityItems.length === 0
    ? allAmenityItems
    : displayAmenityItems
  const canExpandAmenities = allAmenityItems.length > displayAmenityItems.length
  const policies = [
    { label: t('policyCheckIn'), value: detail?.check_in_time
        ? detail.check_in_time + (detail.check_in_until ? `–${detail.check_in_until}` : '')
        : null },
    { label: t('policyCheckOut'), value: detail?.check_out_time ?? null },
    { label: t('policyReception'), value: detail?.reception_open_until ?? null },
  ].filter((p) => p.value)

  return (
    <div className="min-w-0 h-full">
      <div className="glass-panel relative h-full overflow-y-auto custom-scrollbar rounded-[26px]">
        {status === 'error' ? (
          <div className="h-full flex flex-col items-center justify-center gap-3 p-8 text-center">
            <span className="material-symbols-outlined text-4xl text-on-surface-faint" aria-hidden="true">
              hotel
            </span>
            <div className="text-sm text-on-surface-variant max-w-[260px]">{t('detailNoInfo')}</div>
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 rounded-[13px] border border-stroke bg-glass-2 text-on-surface-variant text-[13px] font-[530] cursor-pointer hover:bg-glass-3"
            >
              {t('detailCloseLabel')}
            </button>
          </div>
        ) : (
          <>
            {/* Hero — 240px, vHero reveal, bottom fade, close ✕ */}
            <div className="relative h-[240px] overflow-hidden animate-[vHero_0.9s_cubic-bezier(0.22,1,0.36,1)_both]">
              <RemoteImage
                src={heroSrc}
                alt={t('hotelImgAlt', { name })}
                className="absolute inset-0"
              />
              <div
                className="absolute inset-x-0 bottom-0 h-[120px] pointer-events-none"
                style={{ background: 'linear-gradient(to top, var(--g3), transparent)' }}
                aria-hidden="true"
              />
              <button
                type="button"
                onClick={onClose}
                aria-label={t('detailCloseLabel')}
                className="absolute top-4 right-4 w-[34px] h-[34px] rounded-full border border-edge text-on-surface text-[14px] cursor-pointer transition-transform duration-200 hover:scale-[1.08] active:scale-[0.92]"
                style={{
                  background: 'var(--g3)',
                  backdropFilter: 'blur(18px)',
                  WebkitBackdropFilter: 'blur(18px)',
                  boxShadow: '0 10px 24px -10px rgb(var(--shadow-rgb) / 0.5)',
                }}
              >
                ✕
              </button>
              <div className="absolute left-5 bottom-4 right-[70px]">
                {starRating != null && (
                  <div className="flex items-center gap-2 mb-1.5">
                    <span className="text-[11px] font-[530] text-on-surface-variant px-[9px] py-[3px] rounded-full bg-glass-3">
                      {formatHotelStars(starRating)}
                    </span>
                  </div>
                )}
                <div className="text-[26px] font-[590] tracking-[-0.9px] leading-[1.1] text-on-surface">
                  {name}
                </div>
                {areaName && (
                  <div className="text-[12.5px] font-[450] text-on-surface-variant mt-[3px]">
                    {areaName}
                  </div>
                )}
              </div>
            </div>

            <div className="px-5 pt-[18px] pb-[22px] flex flex-col gap-4">
              {/* Info row — review | price from | match ring. NO "Phòng đã chọn"
                  cell (plan.md #21 — no select-room verb exists). */}
              {(detail?.review_score != null || hasLowestPrice || option?.match_score != null) && (
                <div className="flex items-center gap-4 flex-wrap">
                  {detail?.review_score != null && (
                    <div className="flex items-baseline gap-1.5">
                      <span className="text-[19px] font-[590] tracking-[-0.5px] text-on-surface">
                        {numFmt.format(detail.review_score)}
                      </span>
                      {detail.review_count != null && (
                        <span className="text-[11px] font-[450] text-on-surface-muted">
                          {t('hotelReviewCount', { count: numFmt.format(detail.review_count) })}
                        </span>
                      )}
                    </div>
                  )}
                  {detail?.review_score != null && hasLowestPrice && (
                    <div className="w-px h-[22px] bg-stroke" aria-hidden="true" />
                  )}
                  {hasLowestPrice && (
                    <div>
                      <div className={SECTION_EYEBROW + ' mb-0.5'}>{t('detailPriceFrom')}</div>
                      <div className="text-[13px] font-[530] tracking-[-0.12px] text-on-surface">
                        {formatCurrency(detail!.lowest_price!, i18n.language)} {t('perNightSep')}
                      </div>
                    </div>
                  )}
                  <div className="flex-1" />
                  <MatchScoreRing score={option?.match_score} variant="panel" />
                </div>
              )}

              {/* Handoff — opens the hotel's original OTA listing (Agoda/Booking.com)
                  in a new tab. Hidden when the row has no source_url (e.g. detail
                  fetch failed or an older crawl predates the column). */}
              {detail?.source_url && detail?.source_platform && (
                <a
                  href={detail.source_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center justify-center gap-1.5 px-4 py-[11px] rounded-[16px] border border-stroke bg-glass-2 text-on-surface text-[13px] font-[530] transition-colors hover:bg-glass-3"
                >
                  {t('detailHandoff', {
                    platform: formatSourcePlatform(detail.source_platform),
                  })}
                  <span className="material-symbols-outlined text-[16px]" aria-hidden="true">
                    open_in_new
                  </span>
                </a>
              )}

              {/* Gallery — up to 4 thumbs, vFade staggered like the design */}
              {detail?.images && detail.images.length > 0 && (
                <div className="grid grid-cols-4 gap-[9px]">
                  {detail.images.slice(0, 4).map((url, i) => (
                    <div key={url} style={{ animation: `vFade .5s ${i * 90}ms ease both` }}>
                      <RemoteImage
                        src={url}
                        alt={t('galleryImgAlt', { index: i + 1, name })}
                        className="h-[80px] rounded-[16px]"
                      />
                    </div>
                  ))}
                </div>
              )}

              {/* "Vì sao" accent panel — ranking reasons from the option */}
              {option?.match_reasons && option.match_reasons.length > 0 && (
                <div className="p-4 rounded-[22px] bg-primary-soft border border-edge">
                  <div className="flex items-center gap-[9px] mb-2.5">
                    <div className="w-[22px] h-[22px] rounded-lg flex items-center justify-center text-on-primary text-[10px] font-[590] bg-gradient-to-br from-[#5C93EE] to-[#2C5FC9]">
                      V
                    </div>
                    <div className="text-[12.5px] font-[590] tracking-[-0.1px] text-on-surface">
                      {t('detailWhy')}
                    </div>
                  </div>
                  <MatchReasons reasons={option.match_reasons} variant="panel" />
                </div>
              )}

              {/* Rooms — accordion cards with a display-only "Chọn phòng"
                  pick (see room-card.tsx's doc comment for why it never
                  reaches the backend). */}
              {detail?.rooms && detail.rooms.length > 0 && (
                <div>
                  <div className={SECTION_EYEBROW}>{t('detailRooms')}</div>
                  <div className="flex flex-col gap-2.5">
                    {detail.rooms.map((room, i) => {
                      const roomKey = room.id ?? room.name ?? String(i)
                      return (
                        <RoomCard
                          key={roomKey}
                          room={room}
                          delay={`${i * 90}ms`}
                          selected={roomPicks[hotelId] === roomKey}
                          onPick={() => setRoomPicks((prev) => ({ ...prev, [hotelId]: roomKey }))}
                        />
                      )
                    })}
                  </div>
                </div>
              )}

              {/* Distances — two columns only (name · km). km is rebuilt from
                  distance_km per locale; distance_text (a DB VI string) is
                  never rendered. No minutes column — the data has none. */}
              {distanceRows.length > 0 && (
                <div>
                  <div className={SECTION_EYEBROW}>{t('detailNearby')}</div>
                  <div className="flex flex-col gap-1.5">
                    {distanceRows.map((place) => (
                      <div
                        key={`${place.name}-${place.distance_km ?? 'na'}`}
                        className="flex items-center gap-2.5 px-3 py-[9px] rounded-[16px] bg-glass-2 border border-edge"
                      >
                        <div className="w-1.5 h-1.5 rounded-full bg-primary flex-none" aria-hidden="true" />
                        <div className="flex-1 min-w-0 text-[12.5px] font-[450] text-on-surface-variant">
                          {place.name}
                          {place.category && (
                            <span className="text-on-surface-muted"> · {place.category}</span>
                          )}
                        </div>
                        {place.distance_km != null && (
                          <div className="text-[12px] font-[530] tabular-nums text-on-surface">
                            {t('distanceKm', {
                              km: numFmt.format(place.distance_km),
                            })}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Check-in / check-out policies — only cells with real data */}
              {policies.length > 0 && (
                <div className="flex gap-2.5">
                  {policies.map((p) => (
                    <div
                      key={p.label}
                      className="flex-1 p-[12px] px-[13px] rounded-[18px] bg-glass-2 border border-edge"
                    >
                      <div className={SECTION_EYEBROW + ' mb-[3px]'}>{p.label}</div>
                      <div className="text-[13.5px] font-[590] tracking-[-0.2px] text-on-surface">
                        {p.value}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* Amenities */}
              {visibleAmenityItems.length > 0 && (
                <div>
                  <div className={SECTION_EYEBROW}>{t('detailAmen')}</div>
                  <div className="flex flex-wrap gap-[7px]">
                    {visibleAmenityItems.map((amenity) => (
                      <span
                        key={amenity.id}
                        className={`text-[11.5px] font-[450] px-[11px] py-[5px] rounded-full ${
                          selectedAmenityIds.includes(amenity.id)
                            ? 'bg-primary text-on-primary'
                            : 'bg-fill text-on-surface-variant'
                        }`}
                      >
                        {amenity.label}
                      </span>
                    ))}
                  </div>
                  {canExpandAmenities && (
                    <button
                      type="button"
                      aria-expanded={amenitiesExpanded}
                      onClick={() => setExpandedAmenitiesHotelId(amenitiesExpanded ? null : hotelId)}
                      className="mt-3 inline-flex items-center gap-1 text-[12px] font-[530] text-primary cursor-pointer bg-transparent border-0 p-0 hover:text-primary-strong"
                    >
                      {t(amenitiesExpanded ? 'detailAmenShowLess' : 'detailAmenShowAll')}
                      <span className="material-symbols-outlined text-[16px]" aria-hidden="true">
                        {amenitiesExpanded ? 'expand_less' : 'expand_more'}
                      </span>
                    </button>
                  )}
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
