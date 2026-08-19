import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import ConfirmDialog from './confirm-dialog'
import MatchReasons from './match-reasons'
import MatchScoreRing from './match-score-ring'
import RemoteImage from './remote-image'
import RoomCard from './room-card'
import { useHotelDetail } from '../hooks/use-hotel-detail'
import type { RoomHoldApi } from '../hooks/use-room-hold'
import { bookingErrorKey } from '../lib/booking-error'
import { formatCurrency } from '../lib/format-currency'
import { displayAmenityLabels } from '../lib/hotel-filters'
import { formatHotelStars } from '../lib/format-stars'
import { formatSourcePlatform } from '../lib/format-source-platform'
import { cartMatchesHeldBookings } from '../lib/room-cart-diff'
import type { AmenityCatalogOption, HotelOption, RoomDetail } from '../types'

/** Nights from the trip's real intake dates — same rule as stage-hotels.tsx's
 * own nightsFrom: never invented, null when either date is missing/invalid
 * or the diff isn't positive. Kept as a 1-night floor for the hold's price
 * math (a reservation always covers at least one night), unlike the display
 * copy elsewhere which shows nothing rather than guess. */
function nightsForHold(checkIn: string | null, checkOut: string | null): number {
  if (!checkIn || !checkOut) return 1
  const start = new Date(checkIn).getTime()
  const end = new Date(checkOut).getTime()
  if (!Number.isFinite(start) || !Number.isFinite(end)) return 1
  const nights = Math.round((end - start) / 86_400_000)
  return nights > 0 ? nights : 1
}

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
  roomHold,
  checkInDate,
  checkOutDate,
  onConfirmHotel,
  onSelectHotel,
  heldElsewhereHotelName,
  sessionBookedFromBackend,
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
  /** Owns the room cart + the real hold (reserve/confirm/cancel) — lifted to
   * App.tsx (see its doc comment) so the resulting hold survives this panel
   * closing and is visible from the workspace's hold banner too. */
  roomHold: RoomHoldApi
  /** ChatState.intake's real trip dates — null until intake is complete,
   * which gates the "Giữ phòng" button (never reserves with invented dates). */
  checkInDate: string | null
  checkOutDate: string | null
  /** Fires the EXISTING itinerary-build call once a hold succeeds — see
   * use-room-hold.ts's module doc comment on why room selection now gates it. */
  onConfirmHotel: (hotel: HotelOption) => void
  /** Selects this hotel in the hotel list when rooms are added. */
  onSelectHotel?: (index: number) => void
  /** Name of the hotel `roomHold.heldHotelId` currently points at, when
   * that's a DIFFERENT hotel than the one being viewed here — resolved by
   * the caller (stage-hotels.tsx) from the current session's hotel list,
   * since this component only has data for the hotel being viewed. null
   * when there's nothing held elsewhere, or the held hotel isn't in the
   * current session's list (roomHold is global, not session-scoped — see
   * use-room-hold.ts's module doc comment); the switch-hotel confirm
   * dialog falls back to generic copy in that case. */
  heldElsewhereHotelName?: string | null
  /** Whether the CURRENTLY ACTIVE chat session's booking is already paid
   * (App.tsx's sessionBookedFromBackend) — absolute lock on HoldFooter's
   * "Giữ phòng" button (plan 260819-lock-hotel-after-payment): re-selecting
   * a hotel here would rebuild the itinerary and destroy the one already
   * paid for. Independent of `roomHold` (global, not session-scoped —
   * `roomHold.status === 'BOOKED'` only tells you SOME session somewhere
   * just paid, not that THIS one did), and independent of which hotel is
   * being viewed — even re-picking the SAME paid hotel is blocked, to keep
   * the rule simple and absolute. */
  sessionBookedFromBackend: boolean
}) {
  const { t, i18n } = useTranslation()
  const { detail, status } = useHotelDetail(hotelId)
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
      <div className="glass-panel relative h-full flex flex-col rounded-[26px] overflow-hidden">
        {/* Sticky Close Button — stays fixed at top right even when scrolling */}
        <button
          type="button"
          onClick={onClose}
          aria-label={t('detailCloseLabel')}
          className="absolute top-4 right-4 z-30 w-[34px] h-[34px] rounded-full border border-stroke text-on-surface text-[14px] cursor-pointer transition-transform duration-200 hover:scale-[1.08] active:scale-[0.92] flex items-center justify-center"
          style={{
            background: 'var(--g3)',
            backdropFilter: 'blur(18px)',
            WebkitBackdropFilter: 'blur(18px)',
            boxShadow: '0 4px 16px -4px rgb(var(--shadow-rgb) / 0.35)',
          }}
        >
          ✕
        </button>

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
        ) : status === 'loading' ? (
          <div className="flex-1 min-h-0 overflow-y-auto custom-scrollbar">
            {/* Hero — 240px, vHero reveal, bottom fade */}
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

            <div className="px-5 pt-[18px] pb-5 flex flex-col gap-4">
              {/* Gallery skeleton */}
              <div className="grid grid-cols-4 gap-[9px]">
                {[0, 1, 2, 3].map((i) => (
                  <div key={i} className="shimmer-block h-[80px] rounded-[16px]" />
                ))}
              </div>

              {/* Rooms skeleton */}
              <div className="flex flex-col gap-2.5">
                <div className="shimmer-block h-[14px] w-[110px] rounded-[10px]" />
                {[0, 1].map((i) => (
                  <div
                    key={i}
                    className="rounded-[22px] p-3.5 border border-edge bg-glass-2 flex flex-col gap-3"
                  >
                    <div className="flex gap-[13px]">
                      <div className="shimmer-block w-[92px] h-[76px] rounded-[16px] flex-none" />
                      <div className="flex-1 flex flex-col justify-center gap-2">
                        <div className="shimmer-block h-[15px] w-[65%] rounded-[10px]" />
                        <div className="shimmer-block h-[11px] w-[45%] rounded-[8px]" />
                        <div className="shimmer-block h-[16px] w-[35%] rounded-[10px] mt-1" />
                      </div>
                    </div>
                  </div>
                ))}
              </div>

              {/* Policies/Distances skeleton */}
              <div className="p-4 rounded-[22px] bg-glass-2 border border-edge flex flex-col gap-2.5">
                <div className="shimmer-block h-[13px] w-[90px] rounded-[8px]" />
                <div className="shimmer-block h-[11px] w-[80%] rounded-[8px]" />
                <div className="shimmer-block h-[11px] w-[60%] rounded-[8px]" />
              </div>
            </div>
          </div>
        ) : (
          <>
            <div className="flex-1 min-h-0 overflow-y-auto custom-scrollbar">
              {/* Hero — 240px, vHero reveal, bottom fade */}
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

              {/* Rooms — accordion cards with a real quantity cart feeding
                  roomHold (use-room-hold.ts). Several distinct room types can
                  be in the cart at once; each becomes its own /bookings hold
                  when "Giữ phòng" fires below. */}
              {detail?.rooms && detail.rooms.length > 0 && (
                <div>
                  <div className={SECTION_EYEBROW}>{t('detailRooms')}</div>
                  <div className="flex flex-col gap-2.5">
                    {detail.rooms.map((room, i) => {
                      const roomKey = room.id ?? room.name ?? String(i)
                      const maxQty = room.price?.sold_out
                        ? 0
                        : Math.min(4, room.available_room_count ?? 4)
                      return (
                        <RoomCard
                          key={roomKey}
                          room={room}
                          delay={`${i * 90}ms`}
                          qty={room.id ? (roomHold.cartFor(hotelId)[room.id] ?? 0) : 0}
                          maxQty={maxQty}
                          onQtyChange={(next) => {
                            if (!room.id) return
                            roomHold.setQty(hotelId, room.id, next)
                            if (next > 0 && option != null && onSelectHotel) {
                              onSelectHotel(option.index)
                            }
                          }}
                          amenityDetails={detail.room_amenities ?? []}
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
            </div>

            {/* Cart summary + "Giữ phòng" — real hold, not a local
                pick (use-room-hold.ts). Docked at the bottom of the panel. */}
            {detail?.rooms && detail.rooms.length > 0 && (
              <HoldFooter
                hotelId={hotelId}
                rooms={detail.rooms}
                roomHold={roomHold}
                checkInDate={checkInDate}
                checkOutDate={checkOutDate}
                onConfirmHotel={onConfirmHotel}
                option={option}
                heldElsewhereHotelName={heldElsewhereHotelName ?? null}
                sessionBookedFromBackend={sessionBookedFromBackend}
              />
            )}
          </>
        )}
      </div>
    </div>
  )
}

/** Extracted so the (fairly involved) cart-total/hold-button logic doesn't
 * crowd HotelDetailPanel's already-long render — same reasoning as splitting
 * RoomCard out in the first place. */
function HoldFooter({
  hotelId,
  rooms,
  roomHold,
  checkInDate,
  checkOutDate,
  onConfirmHotel,
  option,
  heldElsewhereHotelName,
  sessionBookedFromBackend,
}: {
  hotelId: string
  rooms: RoomDetail[]
  roomHold: RoomHoldApi
  checkInDate: string | null
  checkOutDate: string | null
  onConfirmHotel: (hotel: HotelOption) => void
  option?: HotelOption
  heldElsewhereHotelName?: string | null
  sessionBookedFromBackend: boolean
}) {
  const { t, i18n } = useTranslation()
  const [confirmSwitchOpen, setConfirmSwitchOpen] = useState(false)
  const [updatedNotice, setUpdatedNotice] = useState(false)
  // HoldFooter isn't remounted when the guest browses to a different hotel
  // (no `key` on it) — reset any transient UI left over from the PREVIOUS
  // hotel's footer so a stale dialog/notice can't reappear here.
  useEffect(() => {
    setConfirmSwitchOpen(false)
    setUpdatedNotice(false)
  }, [hotelId])
  useEffect(() => {
    if (!updatedNotice) return
    const id = setTimeout(() => setUpdatedNotice(false), 4000)
    return () => clearTimeout(id)
  }, [updatedNotice])
  const cart = roomHold.cartFor(hotelId)
  const nights = nightsForHold(checkInDate, checkOutDate)
  const rows = Object.entries(cart)
    .filter(([, qty]) => qty > 0)
    .map(([roomId, qty]) => {
      const room = rooms.find((r) => r.id === roomId)
      const amount = room?.price?.amount
      const hasAmount = amount != null && Number.isFinite(amount) && amount > 0
      return {
        roomId,
        name: room?.name ?? roomId,
        qty,
        subtotal: hasAmount ? amount! * qty * nights : null,
      }
    })
  const cartCount = rows.reduce((n, r) => n + r.qty, 0)
  const total = rows.reduce((sum, r) => sum + (r.subtotal ?? 0), 0)
  const hasAnyPriced = rows.some((r) => r.subtotal != null)

  const heldHere = roomHold.status === 'HELD' && roomHold.heldHotelId === hotelId
  const heldElsewhere = roomHold.status === 'HELD' && roomHold.heldHotelId !== hotelId
  const busy = roomHold.status === 'HOLDING'
  // ERROR is retryable from right here (startHold already cleans up any
  // partial reservations before setting it — see use-room-hold.ts), so it
  // counts as startable same as IDLE. BOOKED counts as startable too: it
  // means a PREVIOUS hold's payment already completed, so there is nothing
  // left to protect — without this, a guest who finished one booking and
  // opens a brand new chat to plan a second trip gets told they're
  // "holding a room at another hotel" for a hold that's long since been
  // paid for (roomHold is a single global hold, not scoped to a chat
  // session — see use-room-hold.ts's module doc comment). EXPIRED counts
  // as startable too, for the same "nothing left to protect" reason (an
  // expired hold no longer reserves anything server-side either) — and
  // MUST be listed here, unlike ERROR/BOOKED: this panel has no "Kiểm tra
  // lại phòng" recheck affordance of its own (that only exists on
  // hold-banner.tsx, in the itinerary/workspace stage — unreachable while
  // still browsing hotels), so a guest whose hold quietly expired while
  // Browse-ing (e.g. an old hold left over from a deleted chat session)
  // would otherwise see the plain "Giữ phòng" label rendered permanently
  // disabled with no way to ever click it again. Every other non-idle
  // status (HELD/HOLDING) means a hold is still actually live and must be
  // resolved from its own state first (heldHere/heldElsewhere/busy above).
  const canStart =
    cartCount > 0 &&
    !!checkInDate &&
    !!checkOutDate &&
    (roomHold.status === 'IDLE' ||
      roomHold.status === 'ERROR' ||
      roomHold.status === 'BOOKED' ||
      roomHold.status === 'EXPIRED')
  // heldHere with an edited cart -> the guest is proposing a DIFFERENT room
  // selection for the hotel they're already holding (add/remove/change qty).
  // heldElsewhere with a fillable cart -> the guest wants to hold rooms at
  // THIS hotel instead, abandoning the other one. Both replace the whole
  // hold via roomHold.switchHold (plan 260818-vnpay-payment-and-email-
  // confirmation's addendum) rather than being permanently locked out.
  const cartChanged = heldHere && cartCount > 0 && !cartMatchesHeldBookings(cart, roomHold.bookings)
  const canSwitchHere = heldElsewhere && cartCount > 0 && !!checkInDate && !!checkOutDate

  const label = sessionBookedFromBackend
    ? t('holdCtaSessionPaid')
    : heldHere
      ? cartChanged
        ? t('holdCtaUpdate')
        : t('holdCtaHeld')
      : heldElsewhere
        ? canSwitchHere
          ? t('holdCtaSwitchHere')
          : t('holdCtaBlocked')
        : busy
          ? t('holdCtaBusy')
          : t('holdCta')
  const disabled =
    sessionBookedFromBackend ||
    busy ||
    (heldHere && !cartChanged) ||
    (heldElsewhere && !canSwitchHere) ||
    (!heldHere && !heldElsewhere && !canStart)

  const stay = { checkInDate: checkInDate!, checkOutDate: checkOutDate! }

  function handleClick() {
    if (sessionBookedFromBackend || busy || !option) return
    if (heldHere) {
      if (!cartChanged) return
      // Editing your own not-yet-paid cart doesn't warrant a confirm dialog
      // (nothing's been lost yet) — just a brief notice once the fresh hold
      // lands, since the timer silently resetting could otherwise look like
      // nothing happened. Deliberately does NOT call onConfirmHotel: that
      // fires a real "Chọn khách sạn X" chat turn, appropriate the first
      // time a hotel is confirmed, not on every room-count tweak.
      void roomHold.switchHold(hotelId, rooms, stay, () => setUpdatedNotice(true))
      return
    }
    if (heldElsewhere) {
      if (!canSwitchHere) return
      setConfirmSwitchOpen(true)
      return
    }
    if (!canStart) return
    void roomHold.startHold(hotelId, rooms, stay, () => onConfirmHotel(option))
  }

  function confirmSwitch() {
    setConfirmSwitchOpen(false)
    if (!option) return
    void roomHold.switchHold(hotelId, rooms, stay, () => onConfirmHotel(option))
  }

  return (
    <>
    <div
      className="flex-none px-5 pt-3.5 pb-4 flex flex-col gap-2.5"
      style={{
        background: 'var(--pop-bg, var(--g3))',
        backdropFilter: 'blur(26px) saturate(1.7)',
        WebkitBackdropFilter: 'blur(26px) saturate(1.7)',
        borderTop: '1px solid var(--edge)',
        boxShadow: '0 -16px 36px -18px rgb(var(--shadow-rgb) / 0.55)',
      }}
    >
      {cartCount > 0 ? (
        <div className="flex flex-col gap-1.5">
          {rows.map((row) => (
            <div key={row.roomId} className="flex items-center gap-2.5">
              <span className="w-[5px] h-[5px] rounded-full bg-primary flex-none" aria-hidden="true" />
              <span className="flex-1 min-w-0 text-[12.5px] font-[530] text-on-surface truncate">
                {row.name}
              </span>
              <span className="flex-none text-[11.5px] text-on-surface-muted">
                {t('roomQtyLabel', { count: row.qty })}
              </span>
              <span className="flex-none text-[12px] font-[530] tabular-nums text-on-surface">
                {row.subtotal != null ? formatCurrency(row.subtotal, i18n.language) : t('roomPriceOnRequest')}
              </span>
            </div>
          ))}
          {hasAnyPriced && (
            <div className="flex items-baseline gap-2 pt-2 mt-0.5 border-t border-line">
              <span className="text-[11.5px] text-on-surface-muted">{t('holdTotal')}</span>
              <span className="flex-1" />
              <span className="text-[18px] font-[590] tracking-[-0.45px] tabular-nums text-on-surface">
                {formatCurrency(total, i18n.language)}
              </span>
            </div>
          )}
        </div>
      ) : (
        <div className="text-[12px] font-[450] leading-[1.45]" style={{ color: 'var(--warn)' }}>
          {t('holdCartEmptyHint')}
        </div>
      )}
      {roomHold.status === 'ERROR' && roomHold.error && (
        <div role="alert" className="text-[11.5px] font-medium" style={{ color: 'var(--err)' }}>
          {t(bookingErrorKey(roomHold.error))}
        </div>
      )}
      {updatedNotice && (
        <div role="status" className="text-[11.5px] font-medium" style={{ color: 'var(--ok-ink)' }}>
          {t('holdUpdateSuccessNotice')}
        </div>
      )}
      <button
        type="button"
        disabled={disabled}
        onClick={handleClick}
        className="w-full py-3 rounded-2xl border-none text-[13.5px] font-[590] tracking-[-0.12px] text-center transition-all duration-200 active:not-disabled:scale-[0.99] disabled:cursor-not-allowed"
        style={{
          background: disabled ? 'var(--fill2)' : 'linear-gradient(135deg,#3A73DE,#2C5FC9)',
          color: disabled ? 'var(--t4)' : 'var(--on-acc)',
          boxShadow: disabled ? 'none' : '0 14px 30px -14px rgba(44,95,201,.7)',
        }}
      >
        {label}
      </button>
    </div>
    <ConfirmDialog
      open={confirmSwitchOpen}
      title={t('holdSwitchConfirmTitle')}
      message={
        heldElsewhereHotelName
          ? t('holdSwitchConfirmMessageNamed', {
              hotel: heldElsewhereHotelName,
              minutes: Math.max(1, Math.ceil(roomHold.holdLeftMs / 60_000)),
            })
          : t('holdSwitchConfirmMessageGeneric', {
              minutes: Math.max(1, Math.ceil(roomHold.holdLeftMs / 60_000)),
            })
      }
      confirmLabel={t('holdSwitchConfirmAction')}
      cancelLabel={t('holdSwitchConfirmCancel')}
      destructive
      onConfirm={confirmSwitch}
      onCancel={() => setConfirmSwitchOpen(false)}
    />
    </>
  )
}
