import { useTranslation } from 'react-i18next'
import ImageGallery from './image-gallery'
import RemoteImage from './remote-image'
import { useBookedRooms } from '../hooks/use-booked-rooms'
import { useHotelDetail } from '../hooks/use-hotel-detail'
import type { RoomHoldApi } from '../hooks/use-room-hold'
import { formatCurrency } from '../lib/format-currency'
import { displayAmenityLabels } from '../lib/hotel-filters'
import { formatHotelStars } from '../lib/format-stars'
import { formatSourcePlatform } from '../lib/format-source-platform'
import type { AmenityCatalogOption, Hotel } from '../types'

const NUM_LOCALE = (lang: string) => (lang === 'vi' ? 'vi-VN' : 'en-US')

const SECTION_EYEBROW =
  'text-[10px] font-[590] tracking-[0.1em] uppercase text-on-surface-muted mb-[9px]'

/**
 * HotelStayPanel — "Hotel Detail Focus Mode" for the itinerary tab, the
 * hotel-focused counterpart of PlaceDetailPanel (same always-mounted flex-
 * sibling contract; stage-workspace.tsx swaps between the two based on
 * `lastFocus.kind`). Unlike hotel-detail-panel.tsx (the interactive search-
 * flow panel with a room cart + "Giữ phòng" hold), this is deliberately
 * read-only: by the time a guest is looking at their built itinerary, room
 * selection is a past decision, not one being made here. No RoomCard, no
 * quantity stepper, no HoldFooter, no ranking-only sections (match score,
 * "Vì sao đề xuất") — just the hotel's own profile plus whichever room(s)
 * are actually booked/held for this stay (useBookedRooms; never the full
 * room catalog, see that hook's own doc comment for why matched_rooms is
 * NOT used here — it's a ranking-time "suggested rooms" field, not a record
 * of what got booked).
 *
 * Sections below intentionally mirror hotel-detail-panel.tsx's own JSX
 * (hero/gallery/info row/handoff/distances/policies/amenities) so the two
 * panels read as the same design language — see that file for the "hide
 * when empty, never invent" rules each section follows.
 */
export default function HotelStayPanel({
  hotelId,
  hotel,
  hotelAmenities,
  sessionId,
  roomHold,
  holdBelongsToSession,
  onClose,
}: {
  /** null while no hotel has ever been focused yet this session (the caller
   * keeps mounting this component always — see stage-workspace.tsx's
   * lastFocus — so this only happens transiently, before the first open). */
  hotelId: string | null
  /** tripPlan.hotel — fallback name/image/star while GET /hotels/{id} loads,
   * same role option: HotelOption plays in hotel-detail-panel.tsx, but
   * sourced from the trip's own confirmed hotel record rather than a
   * ranked search candidate (there's no HotelOption here at all). */
  hotel?: Hotel | null
  /** Shared catalog for displayAmenityLabels — StageRouter's hotelFilterData. */
  hotelAmenities: AmenityCatalogOption[]
  /** ChatState.sessionId — feeds useBookedRooms's booking-receipt fallback. */
  sessionId: string | null
  /** Real room hold (use-room-hold.ts) — read-only here: only `bookings` /
   * `heldHotelId` / `status` are read, never `setQty`/`startHold`/etc. */
  roomHold: RoomHoldApi
  /** Whether roomHold's current hold was created by THIS chat session — see
   * app-shell.tsx's doc comment on the same prop. */
  holdBelongsToSession: boolean
  onClose: () => void
}) {
  const { t, i18n } = useTranslation()
  const { detail, status } = useHotelDetail(hotelId)
  const booked = useBookedRooms(hotelId, sessionId, roomHold, holdBelongsToSession, detail)

  if (hotelId == null) return <div className="min-w-0 h-full" />
  const numFmt = new Intl.NumberFormat(NUM_LOCALE(i18n.language))

  const heroSrc = detail?.image_url ?? detail?.images?.[0] ?? hotel?.image_url
  const name = detail?.name ?? hotel?.name ?? ''
  const areaName = detail?.area_name
  const starRating = detail?.star_rating ?? hotel?.star_rating
  const description = detail?.description ?? hotel?.description
  // Number(x) coerces null → 0, so never wrap: null/undefined and 0 both mean
  // "no price" — hide the cell entirely rather than render "0 ₫ / đêm".
  const hasLowestPrice =
    detail?.lowest_price != null && Number.isFinite(detail.lowest_price) && detail.lowest_price > 0

  const distanceRows = (detail?.nearby_attractions ?? []).filter(
    (place) => place && typeof place === 'object' && place.name,
  )
  const rawAmenities =
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
  const amenityItems = [...new Set(rawAmenities)]
    .map((id) => ({ id, label: labelForAmenity(id) }))
    .sort((left, right) => left.label.localeCompare(right.label, i18n.language.startsWith('vi') ? 'vi' : 'en'))
  const policies = [
    { label: t('policyCheckIn'), value: detail?.check_in_time
        ? detail.check_in_time + (detail.check_in_until ? `–${detail.check_in_until}` : '')
        : null },
    { label: t('policyCheckOut'), value: detail?.check_out_time ?? null },
    { label: t('policyReception'), value: detail?.reception_open_until ?? null },
  ].filter((p) => p.value)

  if (status === 'error') {
    return (
      <div className="min-w-0 h-full">
        <div className="glass-panel h-full rounded-[26px] flex flex-col items-center justify-center gap-3 p-8 text-center">
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
      </div>
    )
  }

  return (
    <div className="relative min-w-0 h-full">
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

      <div className="glass-panel relative h-full overflow-y-auto custom-scrollbar rounded-[26px]">
        {/* Hero — 250px, vHero reveal, bottom fade */}
        <div className="relative h-[250px] overflow-hidden animate-[vHero_0.9s_cubic-bezier(0.22,1,0.36,1)_both]">
          <RemoteImage
            src={heroSrc}
            alt={t('hotelImgAlt', { name })}
            className="absolute inset-0"
            icon="hotel"
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
          {/* Info row — review score + price from. No match-score ring (that's
              ranking data, and there's no HotelOption in the itinerary). */}
          {(detail?.review_score != null || hasLowestPrice) && (
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
            </div>
          )}

          {description && (
            <div className="text-[14px] leading-[1.6] tracking-[-0.08px] text-on-surface-variant text-pretty">
              {description}
            </div>
          )}

          {/* Handoff — opens the hotel's original OTA listing in a new tab. */}
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

          {/* Gallery — 4 thumbs, the rest behind the "+N" badge's lightbox */}
          {detail?.images && detail.images.length > 0 && (
            <ImageGallery
              images={detail.images}
              maxThumbs={4}
              columns={4}
              thumbClassName="h-[80px] rounded-[16px]"
              altFor={(i) => t('galleryImgAlt', { index: i + 1, name })}
            />
          )}

          {/* Phòng đã đặt — read-only, from useBookedRooms. Never the full
              room catalog: no stepper, no "Giữ phòng" button anywhere here. */}
          {booked.status === 'ready' && booked.rows.length > 0 && (
            <div>
              <div className={SECTION_EYEBROW}>{t('checkoutDoneRoomsLabel')}</div>
              <div className="flex flex-col gap-2">
                {booked.rows.map((room) => (
                  <div
                    key={room.id}
                    className="flex items-center gap-3 p-2.5 rounded-2xl bg-glass-2 border border-edge"
                  >
                    <RemoteImage
                      src={room.image}
                      alt={t('roomImgAlt', { name: room.name })}
                      icon="king_bed"
                      className="w-[52px] h-[52px] rounded-xl flex-none"
                    />
                    <div className="flex-1 min-w-0">
                      <div className="text-[12.5px] font-[590] text-on-surface truncate">{room.name}</div>
                      <div className="text-[11px] text-on-surface-muted">
                        {t('roomQtyLabel', { count: room.qty })}
                      </div>
                    </div>
                    <span className="flex-none text-[12.5px] font-[590] tabular-nums text-on-surface">
                      {room.total != null ? formatCurrency(room.total, i18n.language) : t('roomPriceOnRequest')}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Distances — name · km only, rebuilt from distance_km per locale. */}
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
                        {t('distanceKm', { km: numFmt.format(place.distance_km) })}
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

          {/* Amenities — the full list; no curated/expandable subset here
              (that split only exists for HotelOption.display_amenities, a
              search-ranking field this context has no equivalent of). */}
          {amenityItems.length > 0 && (
            <div>
              <div className={SECTION_EYEBROW}>{t('detailAmen')}</div>
              <div className="flex flex-wrap gap-[7px]">
                {amenityItems.map((amenity) => (
                  <span
                    key={amenity.id}
                    className="text-[11.5px] font-[450] px-[11px] py-[5px] rounded-full bg-fill text-on-surface-variant"
                  >
                    {amenity.label}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
