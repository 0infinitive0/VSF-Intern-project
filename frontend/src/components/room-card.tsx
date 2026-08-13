import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import RemoteImage from './remote-image'
import { formatCurrency } from '../lib/format-currency'
import type { RoomDetail } from '../types'

/**
 * RoomCard — the read-only room accordion (RoomCard.dc.html minus the removed
 * parts). Click anywhere on the card (or the toggle button) expands IN PLACE
 * to show the gallery / facilities / package details — no new screen, no
 * popup (Hotel Detail Focus.md §Room Detail). Opening smooth-scrolls down far
 * enough to reveal the newly-expanded details AND the "Chọn phòng"/"Chi tiết
 * phòng" buttons below them; closing smooth-scrolls the card back into view
 * — see the `open` effect below.
 *
 * "Chọn phòng" (`selected`/`onPick`) is display-only by design (plan.md "Phần
 * chưa làm" #4): the backend has no select-room verb, so picking a room here
 * never reaches it, never changes the hotel's total price or AI summary —
 * it's a local highlight the caller (hotel-detail-panel.tsx) tracks per
 * hotel, same as the design's `state.rooms[hid]`. No cancellation/payment
 * policy cells either (plan.md #21) — the tables have no such columns.
 *
 * The availability badge is honest: it maps from price.sold_out (real data),
 * shows only when a price row exists at all (price: null means "we don't
 * know", so no badge), and a null price renders the translated "giá theo yêu
 * cầu" label — never 0, never the hotel-level price.
 */
export default function RoomCard({
  room,
  delay,
  selected,
  onPick,
}: {
  room: RoomDetail
  delay: string
  selected: boolean
  onPick: () => void
}) {
  const { t, i18n } = useTranslation()
  const [open, setOpen] = useState(false)
  const cardRef = useRef<HTMLDivElement>(null)
  // Wraps the expandable details block AND the "Chọn phòng"/"Chi tiết
  // phòng" button row below it (see the JSX — this ref sits on their common
  // parent, not just the details block), so opening scrolls far enough to
  // reveal the buttons too, not just the top of the newly-expanded content.
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
                {price.sold_out ? t('roomSoldOut') : t('roomAvailable')}
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
            {room.room_facilities && room.room_facilities.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {room.room_facilities.map((facility) => (
                  <span
                    key={facility}
                    className="text-[11px] font-[450] px-2.5 py-1 rounded-full bg-fill text-on-surface-variant"
                  >
                    {facility}
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

        <div className="flex gap-2 mt-3">
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              onPick()
            }}
            className="flex-1 p-2.5 rounded-[14px] border-none text-[12.5px] font-[590] tracking-[-0.1px] cursor-pointer transition-all duration-200 active:scale-[0.985]"
            style={{
              background: selected ? 'var(--btn)' : 'var(--fill)',
              color: selected ? 'var(--btn-fg)' : 'var(--t2)',
            }}
          >
            {selected ? t('roomPickBtnSelected') : t('roomPickBtn')}
          </button>
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
