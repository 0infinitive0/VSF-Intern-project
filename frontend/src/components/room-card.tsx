import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import RemoteImage from './remote-image'
import { formatCurrency } from '../lib/format-currency'
import type { RoomDetail } from '../types'

/**
 * RoomCard — the read-only room accordion (RoomCard.dc.html minus the removed
 * parts). Click anywhere on the card (or the toggle button) expands IN PLACE
 * to show the gallery / facilities / package details — no new screen, no
 * popup (Hotel Detail Focus.md §Room Detail).
 *
 * Removed from the design on purpose (plan.md "Phần chưa làm" #4/#21):
 *   - no "Chọn phòng" button — there is no select-room verb on the backend;
 *   - no cancellation/payment policy cells — the tables have no such columns.
 *
 * The availability badge is honest: it maps from price.sold_out (real data),
 * shows only when a price row exists at all (price: null means "we don't
 * know", so no badge), and a null price renders the translated "giá theo yêu
 * cầu" label — never 0, never the hotel-level price.
 */
export default function RoomCard({
  room,
  delay,
}: {
  room: RoomDetail
  delay: string
}) {
  const { t, i18n } = useTranslation()
  const [open, setOpen] = useState(false)

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
      onClick={() => setOpen((o) => !o)}
      className="rounded-[22px] p-3.5 bg-glass-2 border border-edge cursor-pointer"
      style={{
        boxShadow: '0 10px 26px -20px rgb(var(--shadow-rgb) / 0.5)',
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
          sheen="vSheen 6.5s 1.6s ease-in-out infinite"
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
                style={
                  price.sold_out
                    ? { background: 'var(--color-error-soft)', color: 'var(--color-error-ink)' }
                    : { background: 'rgba(42,145,135,.14)', color: 'var(--ok)' }
                }
              >
                {price.sold_out ? t('roomSoldOut') : t('roomAvailable')}
              </span>
            </div>
          )}
        </div>
      </div>

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
            <div className="text-[12px] font-[450] text-on-surface-variant">
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
            setOpen((o) => !o)
          }}
          aria-expanded={open}
          className="flex-none px-3.5 py-2.5 rounded-[14px] border border-stroke bg-glass-2 text-on-surface-variant text-[12.5px] font-[530] cursor-pointer transition-all duration-200 hover:bg-glass-3 hover:text-on-surface"
        >
          <span className="material-symbols-outlined text-[14px] align-[-2px] mr-1" aria-hidden="true">
            {open ? 'expand_less' : 'expand_more'}
          </span>
          {open ? t('roomCollapse') : t('roomExpand')}
        </button>
      </div>
    </div>
  )
}
