import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { getBookingReceipt } from '../api/session-client'
import RemoteImage from './remote-image'
import { formatCurrency } from '../lib/format-currency'
import { formatDateTile, nightsBetween } from '../lib/format-trip-dates'
import type { BookingReceipt } from '../types'

const CLOSE_TRANSITION_MS = 200

type LoadState = 'loading' | 'found' | 'not-found'

/**
 * BookingReceiptModal — "reopen a past session's booking" (plan
 * 260818-vnpay-payment-and-email-confirmation's addendum 4). Opened from
 * hold-banner.tsx's fallback "Xem đặt phòng" button — the one shown for a
 * session whose booking is confirmed per the backend (sessionBookedFromBackend
 * in App.tsx) but which no longer owns the global `roomHold` object
 * (use-room-hold.ts's module doc comment), so booking-modal.tsx's existing
 * "done" screen has nothing real left to read from `roomHold` for it.
 *
 * Deliberately self-fetching (GET /chat/{sessionId}/booking-receipt,
 * session-client.ts) rather than taking the receipt as a prop: it only
 * ever needs `sessionId`, which App.tsx already has directly, so there's
 * no reason to thread fetched data back up through the same prop chain
 * hold-banner.tsx just came down through. Read-only — no wizard, no
 * "Thanh toán" affordance, unlike booking-modal.tsx: by the time this can
 * show anything at all, the booking is already CONFIRMED and paid.
 */
export default function BookingReceiptModal({
  open,
  onClose,
  sessionId,
}: {
  open: boolean
  onClose: () => void
  sessionId: string | null
}) {
  const { t, i18n } = useTranslation()

  const [render, setRender] = useState(open)
  const [visible, setVisible] = useState(false)
  useEffect(() => {
    if (open) {
      setRender(true)
      let raf2 = 0
      const raf1 = requestAnimationFrame(() => {
        raf2 = requestAnimationFrame(() => setVisible(true))
      })
      return () => {
        cancelAnimationFrame(raf1)
        cancelAnimationFrame(raf2)
      }
    }
    setVisible(false)
    const timer = setTimeout(() => setRender(false), CLOSE_TRANSITION_MS)
    return () => clearTimeout(timer)
  }, [open])

  const [loadState, setLoadState] = useState<LoadState>('loading')
  const [receipt, setReceipt] = useState<BookingReceipt | null>(null)

  useEffect(() => {
    if (!open || !sessionId) return
    let cancelled = false
    setLoadState('loading')
    setReceipt(null)
    getBookingReceipt(sessionId).then((data) => {
      if (cancelled) return
      if (data) {
        setReceipt(data)
        setLoadState('found')
      } else {
        setLoadState('not-found')
      }
    })
    return () => {
      cancelled = true
    }
  }, [open, sessionId])

  useEffect(() => {
    if (!open) return
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [open, onClose])

  if (!render) return null

  const code = receipt?.payment_id ? receipt.payment_id.slice(0, 8).toUpperCase() : null
  const ci = receipt ? formatDateTile(receipt.check_in_date, i18n.language) : null
  const co = receipt ? formatDateTile(receipt.check_out_date, i18n.language) : null
  const nights = receipt ? nightsBetween(receipt.check_in_date, receipt.check_out_date) : 1

  return (
    <div
      className="fixed inset-0 z-[70] flex items-center justify-center p-4"
      style={{
        background: 'rgba(12,18,30,.5)',
        backdropFilter: 'blur(10px)',
        WebkitBackdropFilter: 'blur(10px)',
        opacity: visible ? 1 : 0,
        transition: 'opacity .2s ease',
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t('holdBannerBookedTitle')}
        className="glass-panel relative z-10 w-full max-w-[420px] rounded-[26px] overflow-hidden text-on-surface flex flex-col items-center text-center"
        style={{
          opacity: visible ? 1 : 0,
          transform: visible ? 'none' : 'scale(.96)',
          transition: 'opacity .2s ease, transform .2s ease',
        }}
      >
        {loadState === 'loading' && (
          <div className="py-8 px-6 text-[13px] text-on-surface-muted">{t('bookingReceiptLoading')}</div>
        )}

        {loadState === 'not-found' && (
          <div className="p-6 flex flex-col items-center gap-4">
            <div className="text-[13px] text-on-surface-muted py-4">{t('bookingReceiptNotFound')}</div>
            <button
              type="button"
              onClick={onClose}
              className="px-5 py-2.5 rounded-2xl border border-stroke bg-glass-2 text-on-surface-variant text-[13px] font-[530] cursor-pointer hover:bg-glass-3"
            >
              {t('bookingReceiptClose')}
            </button>
          </div>
        )}

        {loadState === 'found' && receipt && (
          <>
            <div className="relative w-full h-[150px] flex-none overflow-hidden">
              <RemoteImage
                src={receipt.hotel_image_url}
                alt={receipt.hotel_name ?? ''}
                className="absolute inset-0"
              />
              <div
                className="absolute inset-x-0 bottom-0 h-[90px] pointer-events-none"
                style={{ background: 'linear-gradient(to top, var(--g3), transparent)' }}
                aria-hidden="true"
              />
              <button
                type="button"
                onClick={onClose}
                aria-label={t('bookingReceiptClose')}
                className="absolute top-3.5 right-3.5 w-[34px] h-[34px] rounded-full border border-edge text-on-surface text-[14px] cursor-pointer transition-transform duration-200 hover:scale-[1.08] active:scale-[0.92]"
                style={{
                  background: 'var(--g3)',
                  backdropFilter: 'blur(18px)',
                  WebkitBackdropFilter: 'blur(18px)',
                  boxShadow: '0 10px 24px -10px rgb(var(--shadow-rgb) / 0.5)',
                }}
              >
                ✕
              </button>
            </div>
            <div className="relative z-10 px-6 pb-6 -mt-[29px] flex flex-col items-center gap-4 w-full">
              <div
                className="relative z-10 w-[58px] h-[58px] rounded-full flex items-center justify-center text-[24px] flex-none"
                style={{
                  background: 'linear-gradient(145deg,#4FB3A5,#2A9187)',
                  color: '#FCFDFE',
                  boxShadow: '0 16px 34px -14px rgba(42,145,135,.7)',
                  border: '4px solid var(--g3)',
                }}
                aria-hidden="true"
              >
                ✓
              </div>
              <div className="-mt-1">
                <div className="text-[15.5px] font-[590] tracking-[-0.1px] text-on-surface">
                  {t('checkoutDoneTitle')}
                </div>
                {receipt.hotel_name && (
                  <div className="text-[13px] text-on-surface-muted mt-1 font-medium">{receipt.hotel_name}</div>
                )}
              </div>

              <div
                className="flex w-full rounded-2xl overflow-hidden border border-edge"
                style={{ background: 'var(--g2)' }}
              >
                <div className="flex-1 px-5 py-3.5 text-left border-r border-line">
                  <div className="text-[9.5px] font-[590] tracking-[0.1em] uppercase text-on-surface-muted">
                    {t('checkoutDoneCode')}
                  </div>
                  <div className="text-[16px] font-[590] tracking-[0.4px] tabular-nums mt-0.5 text-on-surface">
                    {code ?? '—'}
                  </div>
                </div>
                <div className="flex-1 px-5 py-3.5 text-left">
                  <div className="text-[9.5px] font-[590] tracking-[0.1em] uppercase text-on-surface-muted">
                    {t('holdTotal')}
                  </div>
                  <div
                    className="text-[16px] font-[590] tracking-[-0.2px] tabular-nums mt-0.5"
                    style={{ color: 'var(--acc)' }}
                  >
                    {formatCurrency(Number(receipt.total_amount), i18n.language)}
                  </div>
                </div>
              </div>

              <div className="w-full rounded-2xl border border-edge px-5 py-4" style={{ background: 'var(--g2)' }}>
                <div className="flex items-center gap-3">
                  <div className="text-center">
                    <div className="text-[20px] font-[590] tracking-[-0.5px] leading-none text-on-surface">
                      {ci?.day ?? '—'}
                    </div>
                    <div className="text-[9px] font-[590] tracking-[0.09em] text-on-surface-muted mt-[3px]">
                      {ci?.month ?? ''}
                    </div>
                  </div>
                  <div className="flex-1 flex flex-col items-center gap-1">
                    <div className="text-[10px] font-[450] text-on-surface-muted whitespace-nowrap">
                      {nights} {t('nightsWord')}
                    </div>
                    <div className="w-full h-px" style={{ background: 'var(--stroke)' }} />
                  </div>
                  <div className="text-center">
                    <div className="text-[20px] font-[590] tracking-[-0.5px] leading-none text-on-surface">
                      {co?.day ?? '—'}
                    </div>
                    <div className="text-[9px] font-[590] tracking-[0.09em] text-on-surface-muted mt-[3px]">
                      {co?.month ?? ''}
                    </div>
                  </div>
                </div>
              </div>

              {receipt.rooms.length > 0 && (
                <div className="w-full flex flex-col gap-2 text-left">
                  <div className="text-[9.5px] font-[590] tracking-[0.1em] uppercase text-on-surface-muted px-1">
                    {t('checkoutDoneRoomsLabel')}
                  </div>
                  {receipt.rooms.map((room) => (
                    <div
                      key={room.room_id}
                      className="flex items-center gap-3 p-2.5 rounded-2xl bg-glass-2 border border-edge"
                      style={{ boxShadow: '0 10px 24px -18px rgb(var(--shadow-rgb) / 0.5)' }}
                    >
                      <RemoteImage src={room.image_url} alt={room.name} className="w-[52px] h-[52px] rounded-xl flex-none" />
                      <div className="flex-1 min-w-0">
                        <div className="text-[12.5px] font-[590] text-on-surface truncate">{room.name}</div>
                        <div className="text-[11px] text-on-surface-muted">
                          {t('roomQtyLabel', { count: room.room_count })}
                        </div>
                      </div>
                      <span className="flex-none text-[12.5px] font-[590] tabular-nums text-on-surface">
                        {room.total_amount != null
                          ? formatCurrency(Number(room.total_amount), i18n.language)
                          : t('roomPriceOnRequest')}
                      </span>
                    </div>
                  ))}
                </div>
              )}

              <button
                type="button"
                onClick={onClose}
                className="w-full sm:w-auto px-8 h-[44px] rounded-2xl border-none text-[14px] font-[590] text-white cursor-pointer transition-all duration-200 hover:opacity-95 active:scale-[0.98] mt-2"
                style={{
                  background: 'linear-gradient(135deg,#3A73DE,#2C5FC9)',
                  boxShadow: '0 12px 26px -10px rgba(44,95,201,.6)',
                }}
              >
                {t('bookingReceiptClose')}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
