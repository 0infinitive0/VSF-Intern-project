import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { getBookingReceipt } from '../api/session-client'
import { formatCurrency } from '../lib/format-currency'
import { formatFullDate } from '../lib/format-trip-dates'
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
  const ci = receipt ? formatFullDate(receipt.check_in_date, i18n.language) : null
  const co = receipt ? formatFullDate(receipt.check_out_date, i18n.language) : null

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
        className="glass-panel relative z-10 w-full max-w-[420px] rounded-[26px] overflow-hidden text-on-surface p-6 flex flex-col items-center gap-4 text-center"
        style={{
          opacity: visible ? 1 : 0,
          transform: visible ? 'none' : 'scale(.96)',
          transition: 'opacity .2s ease, transform .2s ease',
        }}
      >
        {loadState === 'loading' && (
          <div className="py-8 text-[13px] text-on-surface-muted">{t('bookingReceiptLoading')}</div>
        )}

        {loadState === 'not-found' && (
          <>
            <div className="text-[13px] text-on-surface-muted py-4">{t('bookingReceiptNotFound')}</div>
            <button
              type="button"
              onClick={onClose}
              className="px-5 py-2.5 rounded-2xl border border-stroke bg-glass-2 text-on-surface-variant text-[13px] font-[530] cursor-pointer hover:bg-glass-3"
            >
              {t('bookingReceiptClose')}
            </button>
          </>
        )}

        {loadState === 'found' && receipt && (
          <>
            <div
              className="w-[58px] h-[58px] rounded-full flex items-center justify-center text-[24px] flex-none"
              style={{
                background: 'linear-gradient(145deg,#4FB3A5,#2A9187)',
                color: '#FCFDFE',
                boxShadow: '0 16px 34px -14px rgba(42,145,135,.7)',
              }}
              aria-hidden="true"
            >
              ✓
            </div>
            <div>
              <div className="text-[14.5px] font-[590] tracking-[-0.1px] text-on-surface">
                {t('holdBannerBookedTitle')}
              </div>
              {receipt.hotel_name && (
                <div className="text-[13px] text-on-surface-muted mt-1">{receipt.hotel_name}</div>
              )}
              {receipt.hotel_address && (
                <div className="text-[11.5px] text-on-surface-muted">{receipt.hotel_address}</div>
              )}
            </div>

            {code && (
              <div className="px-5 py-3 rounded-2xl bg-glass-2 border border-edge">
                <div className="text-[9.5px] font-[590] tracking-[0.1em] uppercase text-on-surface-muted">
                  {t('checkoutDoneCode')}
                </div>
                <div className="text-[18px] font-[590] tracking-[0.5px] tabular-nums mt-0.5 text-on-surface">
                  {code}
                </div>
              </div>
            )}

            <div className="grid grid-cols-2 gap-2.5 w-full">
              <div className="p-3 rounded-2xl bg-glass-2 border border-edge text-left">
                <div className="text-[9.5px] font-[590] tracking-[0.1em] uppercase text-on-surface-muted">
                  {t('policyCheckIn')}
                </div>
                <div className="text-[13px] font-[590] tracking-[-0.15px] mt-0.5 text-on-surface">{ci ?? '—'}</div>
              </div>
              <div className="p-3 rounded-2xl bg-glass-2 border border-edge text-left">
                <div className="text-[9.5px] font-[590] tracking-[0.1em] uppercase text-on-surface-muted">
                  {t('policyCheckOut')}
                </div>
                <div className="text-[13px] font-[590] tracking-[-0.15px] mt-0.5 text-on-surface">{co ?? '—'}</div>
              </div>
            </div>

            {receipt.rooms.length > 0 && (
              <div className="w-full flex flex-col gap-1.5">
                {receipt.rooms.map((room) => (
                  <div key={room.room_id} className="flex items-center gap-2.5 text-left">
                    <span className="w-[5px] h-[5px] rounded-full bg-primary flex-none" aria-hidden="true" />
                    <span className="flex-1 min-w-0 text-[12.5px] font-[530] text-on-surface truncate">
                      {room.name}
                    </span>
                    <span className="flex-none text-[11.5px] text-on-surface-muted">
                      {t('roomQtyLabel', { count: room.room_count })}
                    </span>
                    <span className="flex-none text-[12px] font-[530] tabular-nums text-on-surface">
                      {room.total_amount != null
                        ? formatCurrency(Number(room.total_amount), i18n.language)
                        : t('roomPriceOnRequest')}
                    </span>
                  </div>
                ))}
              </div>
            )}

            <div className="flex items-baseline gap-2 pt-2 mt-0.5 w-full border-t border-line">
              <span className="text-[11.5px] text-on-surface-muted">{t('holdTotal')}</span>
              <span className="flex-1" />
              <span className="text-[17px] font-[590] tracking-[-0.4px] tabular-nums text-on-surface">
                {formatCurrency(Number(receipt.total_amount), i18n.language)}
              </span>
            </div>

            <button
              type="button"
              onClick={onClose}
              className="mt-1 px-5 py-2.5 rounded-2xl border-none text-[13px] font-[590] cursor-pointer transition-transform duration-200 active:scale-[0.98]"
              style={{
                background: 'linear-gradient(135deg,#3A73DE,#2C5FC9)',
                color: 'var(--on-acc)',
                boxShadow: '0 10px 24px -10px rgba(44,95,201,.6)',
              }}
            >
              {t('bookingReceiptClose')}
            </button>
          </>
        )}
      </div>
    </div>
  )
}
