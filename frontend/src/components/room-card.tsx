import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import RemoteImage from './remote-image'
import { amenityPresentationItems } from '../lib/amenity-presentation'
import { formatCurrency } from '../lib/format-currency'
import type { AmenityCatalogOption, RoomDetail } from '../types'

/**
 * RoomCard — the room accordion, now with a real quantity stepper (VP-OTA
 * Planner design update: room selection now feeds an actual hold, not a
 * local highlight — see use-room-hold.ts). Click anywhere on the card (or
 * the toggle button) expands IN PLACE to show the gallery / facilities /
 * package details — no new screen, no popup (Hotel Detail Focus.md §Room
 * Detail). Opening smooth-scrolls down far enough to reveal the
 * newly-expanded details AND the quantity/detail buttons below them;
 * closing smooth-scrolls the card back into view — see the `open` effect
 * below.
 *
 * `qty`/`onQtyChange` replace the old display-only `selected`/`onPick`: a
 * hotel can now hold several different room TYPES at once (the design's
 * cart), each with its own count up to `maxQty` — the caller
 * (hotel-detail-panel.tsx) derives this from the trip's party size alone
 * (room-capacity.ts's maxRoomsForParty — deliberately NOT this room type's
 * own `max_guests`, see that file's doc comment for why), further capped by
 * `available_room_count` when known. Still
 * no cancellation/payment policy cells — the tables have no such columns,
 * and this app never invents policy text for real data it doesn't have.
 *
 * The availability badge is honest: it maps from price.sold_out (real data),
 * shows only when a price row exists at all (price: null means "we don't
 * know", so no badge), and a null price renders the translated "giá theo yêu
 * cầu" label — never 0, never the hotel-level price. A sold-out room forces
 * maxQty to 0 (caller's job — see hotel-detail-panel.tsx) so the add button
 * is disabled rather than silently capped at a phantom count.
 */
export default function RoomCard({
  room,
  delay,
  qty,
  maxQty,
  onQtyChange,
  amenityDetails,
  selectedAmenityIds,
  sessionBookedFromBackend,
  onAttemptAddRoom,
}: {
  room: RoomDetail
  delay: string
  /** Units of this room type currently in the cart (0 = not selected). */
  qty: number
  /** Upper bound for `qty` — 0 disables the add button entirely. */
  maxQty: number
  onQtyChange: (nextQty: number) => void
  /** Shared room/both catalog data from the surrounding hotel-detail response. */
  amenityDetails: AmenityCatalogOption[]
  /** Required hotel amenities currently active in the list, highlighted when this room has them. */
  selectedAmenityIds: string[]
  sessionBookedFromBackend?: boolean
  onAttemptAddRoom?: () => void
}) {
  const { t, i18n } = useTranslation()
  const [open, setOpen] = useState(false)
  const cardRef = useRef<HTMLDivElement>(null)
  // Wraps the expandable details block AND the quantity/detail button row
  // below it (see the JSX — this ref sits on their common parent, not just
  // the details block), so opening scrolls far enough to reveal the buttons
  // too, not just the top of the newly-expanded content.
  const bodyRef = useRef<HTMLDivElement>(null)
  // Skips the scroll on mount — this effect exists purely to react to the
  // user actually toggling `open`, not to move anything on first render.
  const skipNextScroll = useRef(true)

  // Expanding can reveal content (gallery/facilities/package details, then
  // the button row) below the fold of HotelDetailPanel's own scroll
  // container; collapsing can leave the view scrolled to where that content
  // used to be. scrollIntoView finds the nearest scrollable ancestor on its
  // own, so neither branch needs to know about HotelDetailPanel's scroll div
  // specifically.
  //   - open: 'nearest' on `bodyRef` — scrolls the minimum needed to reveal
  //     the whole details+buttons block, prioritizing its bottom (the
  //     buttons) once it's taller than the viewport.
  //   - close: 'center' on the card itself, not 'nearest' — the card is
  //     usually ALREADY inside the viewport once collapsed (only the
  //     content below it moved), so 'nearest' would just no-op instead of
  //     giving the "hiệu ứng cuộn nhẹ nhàng" a collapse is supposed to have.
  useEffect(() => {
    if (skipNextScroll.current) {
      skipNextScroll.current = false
      return
    }
    const frame = requestAnimationFrame(() => {
      if (open) bodyRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
      else cardRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    })
    return () => cancelAnimationFrame(frame)
  }, [open])

  const meta = [
    room.room_size_sqm != null ? t('roomSqm', { n: room.room_size_sqm }) : null,
    room.max_guests != null ? t('roomSleeps', { count: room.max_guests }) : null,
    room.bed_description || null,
    room.view ? t('roomViewPrefix', { view: room.view }) : null,
  ]
    .filter(Boolean)
    .join(' · ')

  const price = room.price ?? null
  // A missing/zero amount means "giá theo yêu cầu" — never render 0 ₫ and
  // never borrow the hotel-level price. (Number(x) coerces null → 0, so the
  // null check must come first, without coercion.)
  const hasPriceAmount =
    price?.amount != null && Number.isFinite(price.amount) && price.amount > 0
  const roomFacilityItems = amenityPresentationItems(
    room.room_facilities ?? [],
    amenityDetails,
    i18n.language,
    selectedAmenityIds,
  )
  const selected = qty > 0
  const canAdd = maxQty > 0 && qty < maxQty

  return (
    <div
      ref={cardRef}
      onClick={() => setOpen((o) => !o)}
      className="rounded-[22px] p-3.5 border cursor-pointer"
      style={{
        background: selected ? 'var(--g3)' : 'var(--g2)',
        borderColor: selected ? 'var(--acc)' : 'var(--edge)',
        boxShadow: selected
          ? '0 18px 38px -20px rgb(var(--shadow-rgb) / 0.55), 0 0 0 3px var(--acc-soft)'
          : '0 8px 20px -18px rgb(var(--shadow-rgb) / 0.6)',
        transition: 'all .34s cubic-bezier(.34,1.3,.64,1)',
        animation: `vFade .5s ${delay} ease both`,
      }}
    >
      <div className="flex gap-[13px]">
        <RemoteImage
          src={room.images?.[0]}
          alt={t('roomImgAlt', { name: room.name ?? '' })}
          icon="king_bed"
          className="w-[92px] h-[76px] rounded-[16px] flex-none"
        />
        <div className="flex-1 min-w-0">
          <div className="flex items-start gap-2.5">
            <div className="flex-1 min-w-0">
              <div className="text-[14px] font-[590] tracking-[-0.2px] text-on-surface">
                {room.name}
              </div>
              {meta && (
                <div className="text-[11px] font-[450] text-on-surface-muted mt-0.5">{meta}</div>
              )}
            </div>
            <div className="flex-none text-right">
              {hasPriceAmount ? (
                <>
                  <div className="text-[15px] font-[590] tracking-[-0.3px] text-on-surface">
                    {formatCurrency(price!.amount!, i18n.language)}
                  </div>
                  <div className="text-[10px] font-[450] text-on-surface-muted">{t('perNight')}</div>
                </>
              ) : (
                <div className="text-[11px] font-[530] text-on-surface-muted">
                  {t('roomPriceOnRequest')}
                </div>
              )}
            </div>
          </div>
          {price != null && (
            <div className="flex items-center gap-2 mt-[7px] flex-wrap">
              <span
                className="text-[10.5px] font-[530] px-[9px] py-[3px] rounded-full"
                // Was a literal rgba(42,145,135,.14) (the light-theme value
                // of --ok-soft/--color-success-soft) — never switched to the
                // brighter dark-theme tint like its sold_out sibling below
                // already correctly does via --color-error-soft.
                style={
                  price.sold_out
                    ? { background: 'var(--color-error-soft)', color: 'var(--color-error-ink)' }
                    : { background: 'var(--color-success-soft)', color: 'var(--ok)' }
                }
              >
                {price.sold_out
                  ? t('roomSoldOut')
                  : room.available_room_count != null && room.available_room_count > 0
                    ? t('roomAvailableCount', { count: room.available_room_count })
                    : t('roomAvailable')}
              </span>
            </div>
          )}
        </div>
      </div>

      <div ref={bodyRef}>
        {open && (
          <div
            className="mt-3 pt-3 border-t border-line flex flex-col gap-[11px] animate-[vFade_0.35s_ease_both]"
          >
            {room.images && room.images.length > 0 && (
              <div className="grid grid-cols-3 gap-2">
                {room.images.slice(0, 3).map((url, i) => (
                  <RemoteImage
                    key={url}
                    src={url}
                    alt={t('galleryImgAlt', { index: i + 1, name: room.name ?? '' })}
                    icon="king_bed"
                    className="h-[70px] rounded-[14px]"
                  />
                ))}
              </div>
            )}
            {roomFacilityItems.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {roomFacilityItems.map((facility) => (
                  <span
                    key={facility.id}
                    className={`text-[11px] font-[450] px-2.5 py-1 rounded-full ${
                      facility.matchesPreference
                        ? 'bg-primary text-on-primary font-[590]'
                        : 'bg-fill text-on-surface-variant'
                    }`}
                    aria-label={facility.matchesPreference
                      ? t('roomAmenityMatchesPreference', { amenity: facility.label })
                      : undefined}
                  >
                    {facility.matchesPreference && <span aria-hidden="true">✓ </span>}
                    {facility.label}
                  </span>
                ))}
              </div>
            )}
            {price?.package_details && (
              <div className="text-[13px] font-normal leading-[1.55] text-on-surface-variant text-pretty">
                {price.package_details}
              </div>
            )}
          </div>
        )}

        <div className="flex gap-2 mt-3 items-center">
          {sessionBookedFromBackend ? (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation()
                onAttemptAddRoom?.()
              }}
              className="flex-1 p-2.5 rounded-[14px] border border-amber-500/20 text-[12.5px] font-[590] tracking-[-0.1px] cursor-not-allowed transition-all duration-200 opacity-70 flex items-center justify-center gap-1.5 active:scale-95"
              style={{ background: 'rgba(234, 179, 8, 0.08)', color: 'var(--t2)' }}
            >
              <span className="material-symbols-outlined text-[14px] text-amber-500" aria-hidden="true">
                lock
              </span>
              <span>{t('roomAddBtn')}</span>
            </button>
          ) : selected ? (
            <div
              className="flex-1 flex items-center gap-1 h-11 p-1 rounded-[14px]"
              style={{ background: 'var(--acc-soft)', border: '1px solid var(--acc)' }}
              onClick={(e) => e.stopPropagation()}
            >
              <button
                type="button"
                aria-label={t('roomQtyDecrease')}
                onClick={() => onQtyChange(qty - 1)}
                className="w-[34px] h-[34px] flex-none rounded-[11px] border-none text-on-surface text-[15px] cursor-pointer flex items-center justify-center transition-colors duration-200 hover:bg-white/60"
                style={{ background: 'var(--g3)' }}
              >
                −
              </button>
              <div className="flex-1 text-center text-[12.5px] font-[590] tracking-[-0.1px] text-on-surface tabular-nums">
                ✓ {t('roomQtyLabel', { count: qty })}
              </div>
              <button
                type="button"
                aria-label={t('roomQtyIncrease')}
                disabled={!canAdd}
                onClick={() => onQtyChange(qty + 1)}
                className="w-[34px] h-[34px] flex-none rounded-[11px] border-none text-[15px] cursor-pointer flex items-center justify-center transition-transform duration-200 active:scale-90 disabled:cursor-not-allowed disabled:opacity-40"
                style={{ background: 'var(--acc)', color: 'var(--on-acc)' }}
              >
                +
              </button>
            </div>
          ) : (
            <button
              type="button"
              disabled={!canAdd}
              onClick={(e) => {
                e.stopPropagation()
                onQtyChange(1)
              }}
              className="flex-1 p-2.5 rounded-[14px] border-none text-[12.5px] font-[590] tracking-[-0.1px] cursor-pointer transition-all duration-200 active:scale-[0.985] disabled:cursor-not-allowed disabled:opacity-50"
              style={{ background: 'var(--fill)', color: 'var(--t2)' }}
            >
              {/* "Hết phòng" is reserved for an ACTUALLY sold-out room
                  (price.sold_out, real data) — when maxQty is merely 0
                  because the party-size cap across the cart's other room
                  types is already used up (hotel-detail-panel.tsx's
                  remainingRoomsAllowed), the button still reads "Thêm
                  phòng", just disabled/dimmed via `canAdd` above — telling
                  a guest "hết phòng" for a room type that's actually still
                  available would be misleading. */}
              {price?.sold_out ? t('roomSoldOut') : t('roomAddBtn')}
            </button>
          )}
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              setOpen((o) => !o)
            }}
            aria-expanded={open}
            className="inline-flex flex-none items-center justify-center gap-1 px-3.5 py-2.5 rounded-[14px] border border-stroke bg-glass-2 text-on-surface-variant text-[12.5px] font-[530] cursor-pointer transition-all duration-200 hover:bg-glass-3 hover:text-on-surface"
          >
            <span className="material-symbols-outlined text-[14px]" aria-hidden="true">
              {open ? 'expand_less' : 'expand_more'}
            </span>
            {t('roomExpand')}
          </button>
        </div>
      </div>
    </div>
  )
}
