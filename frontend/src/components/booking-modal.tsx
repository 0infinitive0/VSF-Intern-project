import { Fragment, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import AuthTextField from '../auth/auth-text-field'
import { EMAIL_RE } from '../auth/email-pattern'
import { isValidPhone } from '../auth/phone-pattern'
import RemoteImage from './remote-image'
import { useHotelDetail } from '../hooks/use-hotel-detail'
import type { RoomHoldApi } from '../hooks/use-room-hold'
import { createVnpayPayment } from '../api/payment-client'
import { bookingErrorKey } from '../lib/booking-error'
import { formatCurrency } from '../lib/format-currency'
import { formatDateTile, formatFullDate, nightsBetween } from '../lib/format-trip-dates'

const CLOSE_TRANSITION_MS = 380
// Design's client-computed 10% (V-OTA Planner.dc.html: `tax = sub * 0.1`) —
// no backend tax field exists, so this stays a display-only markup on top of
// the real per-room subtotal, not something sent to the reservation API.
const TAX_RATE = 0.1

type Step = 'guest' | 'pay' | 'done'

function mmss(ms: number): string {
  const totalSeconds = Math.max(0, Math.round(ms / 1000))
  return `${String(Math.floor(totalSeconds / 60)).padStart(2, '0')}:${String(totalSeconds % 60).padStart(2, '0')}`
}

/**
 * BookingModal — the checkout flow added by the V-OTA Planner design update:
 * guest details → payment → done, opened from hold-banner.tsx's "Đặt phòng".
 * A centered glass dialog over a backdrop (this app's existing modal
 * convention — ConfirmDialog, ProfilePasswordModal) rather than the design's
 * full-page takeover (user decision 260818: the centered-dialog framing
 * reads better here than a page swap).
 *
 * Payment step (plan 260818-vnpay-payment-and-email-confirmation): "Thanh
 * toán qua VNPay" calls POST /payments/vnpay (api/payment-client.ts) and
 * then does a REAL full-page redirect (`window.location.href = pay_url`) —
 * VNPay's own hosted page handles method selection (ATM/QR/international
 * card), not this app. There is no more in-app QR/demo simulation: the
 * booking only actually becomes CONFIRMED once VNPay's IPN webhook reaches
 * the backend server-to-server (routes.py's vnpay_ipn) — this component
 * never confirms anything itself. See App.tsx's consumeVnpayReturn for how
 * the guest coming BACK from VNPay (a fresh page load — everything here
 * remounts) ends up back on this modal's Done screen.
 *
 * Step state (guest fields) is local and resets only when the underlying
 * hold group changes (a fresh set of booking ids) — so closing this view
 * mid-flow and reopening from the hold banner picks up exactly where the
 * user left off, since NOTHING about closing it touches the hold itself
 * (the hold lives in roomHold, independent of whether this UI is open).
 */
export default function BookingModal({
  open,
  onClose,
  roomHold,
  holdBelongsToSession,
  sessionResolved,
  hotelName,
  hotelArea,
  checkInDate,
  checkOutDate,
  guestsLabel,
}: {
  open: boolean
  onClose: () => void
  roomHold: RoomHoldApi
  /** Whether `roomHold`'s current hold/booking was created by the CURRENTLY
   * ACTIVE chat session (App.tsx: `roomHold.heldSessionId === state.
   * sessionId`) — roomHold is a single global hold, not scoped per session
   * (see use-room-hold.ts's module doc comment), so this is the only thing
   * standing between this modal and paying for/viewing the wrong hotel's
   * booking. hold-banner.tsx's own copy of this check already keeps its
   * "Đặt phòng" button from ever opening this modal for a hold that isn't
   * the active session's — the effect below is the narrower safety net for
   * the rarer case where the modal was ALREADY open when the hold moved to
   * a different session out from under it. */
  holdBelongsToSession: boolean
  /** True once `state.sessionId` (App.tsx) has resolved past its initial
   * `null` — use-chat-session.ts's bootstrap is async (a real network
   * round trip), so `state.sessionId` is briefly null on EVERY mount,
   * including right after the guest returns from VNPay's redirect (a full
   * page reload — everything here remounts, see App.tsx's
   * consumeVnpayReturn). Without gating the auto-close effect below on
   * this, `holdBelongsToSession` reads as false during that transient
   * window (heldSessionId, a real id, can never equal null) and the
   * "thanh toán thành công" modal consumeVnpayReturn just opened would
   * close itself before the bootstrap even finishes — the guest lands back
   * on the app with no success modal at all, even though the payment (and
   * the session it belongs to) were both actually fine. */
  sessionResolved: boolean
  hotelName: string
  hotelArea?: string | null
  checkInDate: string | null
  checkOutDate: string | null
  /** ChatState.intake.people — already a backend-formatted string ("2
   * người"), rendered verbatim per types/index.ts's own note on that field. */
  guestsLabel?: string | null
}) {
  const { t, i18n } = useTranslation()
  const { detail: hotelDetail } = useHotelDetail(roomHold.heldHotelId)

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

  useEffect(() => {
    if (open && sessionResolved && !holdBelongsToSession) onClose()
  }, [open, sessionResolved, holdBelongsToSession, onClose])

  const [step, setStep] = useState<'guest' | 'pay'>('guest')
  const [guestTouched, setGuestTouched] = useState(false)
  const [guestName, setGuestName] = useState('')
  const [guestEmail, setGuestEmail] = useState('')
  const [guestPhone, setGuestPhone] = useState('')
  const [guestNote, setGuestNote] = useState('')

  const [creatingPayment, setCreatingPayment] = useState(false)
  const [paymentError, setPaymentError] = useState<string | null>(null)

  // Resets the wizard only when the HOLD GROUP itself changes (a fresh set
  // of booking ids from a new startHold), not on every open/close — so
  // guest info typed before an accidental close survives reopening.
  const bookingIdsKey = roomHold.bookings.map((b) => b.id).join(',')
  const prevKeyRef = useRef(bookingIdsKey)
  useEffect(() => {
    if (bookingIdsKey === prevKeyRef.current || bookingIdsKey === '') return
    prevKeyRef.current = bookingIdsKey
    setStep('guest')
    setGuestTouched(false)
    setCreatingPayment(false)
    setPaymentError(null)
  }, [bookingIdsKey])

  // No leave-confirmation dialog: closing this modal never touches the
  // hold (see the module doc comment) and, unlike the old in-app QR
  // simulation, there's no local "payment in progress" moment to protect
  // once "Thanh toán qua VNPay" is clicked — the browser has already
  // navigated away by then.
  function requestClose() {
    onClose()
  }

  useEffect(() => {
    if (!open) return
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') requestClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  if (!render) return null

  const booked = roomHold.status === 'BOOKED'
  const effectiveStep: Step = booked ? 'done' : step
  const stepIndex: Record<Step, number> = { guest: 1, pay: 2, done: 3 }
  const currentStepN = stepIndex[effectiveStep]
  const guestValid =
    guestName.trim().length > 2 && EMAIL_RE.test(guestEmail.trim()) && isValidPhone(guestPhone)

  const rows = roomHold.bookings.map((b) => {
    const room = hotelDetail?.rooms?.find((r) => r.id === b.room_id)
    return {
      id: b.id,
      name: room?.name ?? b.room_id,
      image: room?.images?.[0],
      qty: b.room_count,
      total: b.total_amount != null ? Number(b.total_amount) : null,
    }
  })
  const hasAnyTotal = rows.some((r) => r.total != null)
  const subtotal = rows.reduce((sum, r) => sum + (r.total ?? 0), 0)
  const tax = subtotal * TAX_RATE
  const grandTotal = subtotal + tax
  const nights = nightsBetween(checkInDate, checkOutDate)
  const ci = formatDateTile(checkInDate, i18n.language)
  const co = formatDateTile(checkOutDate, i18n.language)
  const ciFull = formatFullDate(checkInDate, i18n.language)
  const coFull = formatFullDate(checkOutDate, i18n.language)
  // Prefer the PAYMENT's code once one exists — it's what the confirmation
  // email shows too (backend/src/api/routes.py's _send_confirmation_email_
  // best_effort uses the same `payment.id[:8].upper()`), so the guest sees
  // one consistent code in both places. Falls back to a booking id only for
  // the brief pre-payment window where no payment exists yet.
  const bookedCode = roomHold.paymentId
    ? roomHold.paymentId.slice(0, 8).toUpperCase()
    : roomHold.bookings[0]?.id
      ? roomHold.bookings[0].id.slice(0, 8).toUpperCase()
      : '—'
  const hotelAddress = hotelDetail?.address ?? hotelArea ?? null

  // Step-pill visual state — mirrors the design's `steps` builder exactly
  // (V-OTA Planner.dc.html: completed = ok-green + check, active = dark
  // "btn" fill + ring, upcoming = faint fill).
  const stepMeta = (
    [
      ['guest', t('checkoutStepGuest')],
      ['pay', t('checkoutStepPay')],
      ['done', t('checkoutStepDone')],
    ] as const
  ).map(([key, label], i) => {
    const idx = i + 1
    const completed = idx < currentStepN
    const active = idx === currentStepN
    return {
      key,
      label,
      n: completed ? '✓' : String(idx),
      bg: completed ? 'var(--ok)' : active ? 'var(--btn)' : 'var(--fill2)',
      fg: completed ? 'var(--on-acc)' : active ? 'var(--btn-fg)' : 'var(--t2)',
      ring: active ? '0 8px 20px -8px rgb(var(--shadow-rgb) / 0.55)' : 'none',
      labelColor: active ? 'var(--t1)' : 'var(--t2)',
      weight: active ? 590 : 500,
      lineBg: completed ? 'var(--ok)' : 'var(--stroke)',
    }
  })

  function goPay() {
    setGuestTouched(true)
    if (!guestValid) return
    setStep('pay')
  }

  /** Creates the real VNPay payment, then navigates the whole browser away —
   * see the module doc comment. Guest details were already validated on
   * step 1 (goPay's guestValid gate), so they're trusted here without
   * re-checking. */
  async function handlePayWithVnpay() {
    if (roomHold.bookings.length === 0) return
    setCreatingPayment(true)
    setPaymentError(null)
    try {
      const { payment_id, pay_url } = await createVnpayPayment({
        booking_ids: roomHold.bookings.map((b) => b.id),
        temporary_user_ref: roomHold.guestRef,
        guest_name: guestName.trim(),
        guest_email: guestEmail.trim(),
        guest_phone: guestPhone.trim() || undefined,
      })
      roomHold.setPendingPayment(payment_id)
      window.location.href = pay_url
    } catch (err) {
      setCreatingPayment(false)
      setPaymentError(err instanceof Error ? err.message : String(err))
    }
  }

  return (
    <div
      className="fixed inset-0 z-[70] flex items-start justify-center overflow-y-auto p-4 py-6"
      style={{
        background: 'rgba(12,18,30,.5)',
        backdropFilter: 'blur(10px)',
        WebkitBackdropFilter: 'blur(10px)',
        opacity: visible ? 1 : 0,
        transition: 'opacity .34s ease',
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) requestClose()
      }}
    >
    <div
      role="dialog"
      aria-modal="true"
      aria-label={t('checkoutTitle')}
      className="glass-panel relative z-10 w-full max-w-[1040px] rounded-[28px] overflow-hidden text-on-surface"
      style={{
        opacity: visible ? 1 : 0,
        transform: visible ? 'none' : 'translateY(18px) scale(.98)',
        transition: 'opacity .34s cubic-bezier(.22,1,.36,1), transform .44s cubic-bezier(.22,1,.36,1)',
      }}
    >
      <header className="flex items-center gap-3 px-5 py-3.5 border-b border-line">
        <div
          className="w-[30px] h-[30px] flex-none rounded-[10px] flex items-center justify-center text-on-primary font-[590] text-[14px] bg-gradient-to-br from-[#5C93EE] to-[#2C5FC9]"
          style={{ boxShadow: '0 6px 16px -5px rgba(44,95,201,.6)' }}
          aria-hidden="true"
        >
          V
        </div>
        <div className="min-w-0 flex flex-col gap-0.5">
          <div className="text-[9.5px] font-[590] tracking-[0.1em] uppercase text-on-surface-muted whitespace-nowrap">
            V‑OTA · {t('checkoutTitle')}
          </div>
          <div className="text-[14px] font-[590] tracking-[-0.25px] text-on-surface truncate">{hotelName}</div>
        </div>
        <div className="flex-1" />
        {effectiveStep !== 'done' && roomHold.status === 'HELD' && (
          <div
            className="hidden sm:flex flex-none items-center gap-2 px-3.5 py-[7px] rounded-xl border border-stroke whitespace-nowrap"
            style={{ background: 'var(--fill)' }}
          >
            <span className="material-symbols-outlined text-[16px] text-on-surface-variant leading-none" aria-hidden="true">
              schedule
            </span>
            <span className="text-[9.5px] font-[590] tracking-[0.09em] uppercase text-on-surface-muted">
              {t('holdBannerHeldLabel')}
            </span>
            <span className="text-[14px] font-[590] tabular-nums text-on-surface">{mmss(roomHold.holdLeftMs)}</span>
          </div>
        )}
        <button
          type="button"
          onClick={requestClose}
          aria-label={t('checkoutCloseAria')}
          className="w-[34px] h-[34px] flex-none rounded-full border border-edge text-on-surface-variant text-[13px] cursor-pointer transition-transform duration-200 hover:scale-[1.08] active:scale-[0.92]"
          style={{ background: 'var(--g3)' }}
        >
          ✕
        </button>
      </header>

      <div className="relative px-5" style={{ paddingTop: 20, paddingBottom: 24 }}>
        {/* Step indicator — circles + eyebrow/label */}
        <div
          className="flex items-center mb-[18px] px-5 py-3.5 rounded-[22px]"
          style={{
            background: 'var(--g1)',
            border: '1px solid var(--edge)',
            boxShadow: '0 18px 44px -30px rgb(var(--shadow-rgb) / 0.4)',
            backdropFilter: 'blur(24px) saturate(1.6)',
            WebkitBackdropFilter: 'blur(24px) saturate(1.6)',
          }}
        >
          {stepMeta.map((st, i) => {
            const clickable = !booked && i + 1 < currentStepN && (st.key === 'guest' || st.key === 'pay')
            return (
              <Fragment key={st.key}>
                <button
                  type="button"
                  disabled={!clickable}
                  onClick={() => clickable && setStep(st.key as 'guest' | 'pay')}
                  className="flex items-center gap-2.5 flex-none min-w-0 border-none bg-transparent p-0 text-left disabled:cursor-default"
                  style={{ cursor: clickable ? 'pointer' : 'default' }}
                >
                  <div
                    className="w-7 h-7 flex-none rounded-full flex items-center justify-center text-[12px] font-[590]"
                    style={{ background: st.bg, color: st.fg, boxShadow: st.ring, transition: 'all .35s cubic-bezier(.34,1.4,.64,1)' }}
                  >
                    {st.n}
                  </div>
                  <div className="min-w-0">
                    <div className="text-[9px] font-[590] tracking-[0.1em] uppercase text-on-surface-muted">
                      {t('checkoutStepEyebrow', { n: i + 1 })}
                    </div>
                    <div
                      className="text-[12.5px] tracking-[-0.1px] whitespace-nowrap overflow-hidden text-ellipsis"
                      style={{ fontWeight: st.weight, color: st.labelColor, transition: 'color .3s' }}
                    >
                      {st.label}
                    </div>
                  </div>
                </button>
                {i < stepMeta.length - 1 && (
                  <div
                    className="flex-1 h-0.5 rounded-full mx-4"
                    style={{ background: st.lineBg, transition: 'background .45s' }}
                  />
                )}
              </Fragment>
            )
          })}
        </div>

        <div className="flex flex-wrap items-start gap-[18px]">
          <main className="flex-1 basis-[460px] min-w-0 flex flex-col gap-4">
            {effectiveStep === 'guest' && (
              <section
                className="p-6 rounded-[26px] flex flex-col gap-5"
                style={{
                  background: 'var(--g1)',
                  border: '1px solid var(--edge)',
                  boxShadow: '0 22px 52px -32px rgb(var(--shadow-rgb) / 0.36), inset 0 1px 0 var(--gloss)',
                  backdropFilter: 'blur(28px) saturate(1.7)',
                  WebkitBackdropFilter: 'blur(28px) saturate(1.7)',
                  animation: 'vRise .5s cubic-bezier(.22,1,.36,1) both',
                }}
              >
                <div>
                  <div className="text-[17px] font-[590] tracking-[-0.4px] text-on-surface">{t('guestTitle')}</div>
                  <div className="text-[12.5px] text-on-surface-muted mt-1">{t('guestSub')}</div>
                </div>
                <div className="grid sm:grid-cols-2 gap-4">
                  <div className="sm:col-span-2">
                    <AuthTextField
                      label={t('authNameLabel')}
                      type="text"
                      dense
                      autoComplete="name"
                      placeholder={t('authNamePlaceholder')}
                      value={guestName}
                      onChange={(e) => setGuestName(e.target.value)}
                    />
                  </div>
                  <AuthTextField
                    label={t('authEmailLabel')}
                    type="email"
                    dense
                    autoComplete="email"
                    placeholder="you@email.com"
                    value={guestEmail}
                    onChange={(e) => setGuestEmail(e.target.value)}
                  />
                  <AuthTextField
                    label={t('authPhoneLabel')}
                    type="tel"
                    dense
                    autoComplete="tel"
                    placeholder={t('authPhonePlaceholder')}
                    value={guestPhone}
                    onChange={(e) => setGuestPhone(e.target.value)}
                  />
                  <div className="sm:col-span-2 flex flex-col gap-1.5">
                    <span className="text-[10.5px] font-semibold tracking-wide uppercase text-on-surface-muted">
                      {t('guestNoteLabel')}
                    </span>
                    <textarea
                      value={guestNote}
                      onChange={(e) => setGuestNote(e.target.value)}
                      rows={2}
                      className="rounded-[14px] border bg-glass-2 px-3.5 py-2.5 text-[14px] text-on-surface outline-none transition-[box-shadow,background-color,border-color] duration-200 focus:border-primary focus:bg-glass-3 placeholder:text-on-surface-muted resize-y"
                      style={{ borderColor: 'var(--stroke)' }}
                    />
                  </div>
                </div>
                <div className="flex flex-col gap-3 pt-1 border-t border-line">
                  {guestTouched && !guestValid && (
                    <div role="alert" className="text-[12px] font-medium pt-3" style={{ color: 'var(--err)' }}>
                      {t('guestErr')}
                    </div>
                  )}
                  <button
                    type="button"
                    onClick={goPay}
                    className="w-full h-[50px] rounded-2xl border-none text-[14px] font-[590] tracking-[-0.12px] cursor-pointer transition-all duration-200 hover:opacity-95 active:scale-[0.99]"
                    style={{
                      background: 'linear-gradient(135deg,#3A73DE,#2C5FC9)',
                      color: 'var(--on-acc)',
                      boxShadow: '0 14px 30px -14px rgba(44,95,201,.7)',
                    }}
                  >
                    {t('guestNext')}
                  </button>
                </div>
              </section>
            )}

            {effectiveStep === 'pay' && (
              <section
                className="p-5 rounded-[26px] flex flex-col gap-4"
                style={{
                  background: 'var(--g1)',
                  border: '1px solid var(--edge)',
                  boxShadow: '0 22px 52px -32px rgb(var(--shadow-rgb) / 0.36), inset 0 1px 0 var(--gloss)',
                  backdropFilter: 'blur(28px) saturate(1.7)',
                  WebkitBackdropFilter: 'blur(28px) saturate(1.7)',
                  animation: 'vRise .5s cubic-bezier(.22,1,.36,1) both',
                }}
              >
                <div>
                  <div className="text-[17px] font-[590] tracking-[-0.4px] text-on-surface">{t('paymentTitle')}</div>
                  <div className="text-[12.5px] text-on-surface-muted mt-1">{t('paymentSub')}</div>
                </div>

                <div
                  className="flex items-center gap-3.5 p-4 rounded-2xl border"
                  style={{ background: 'var(--g2)', borderColor: 'var(--edge)' }}
                >
                  <span
                    className="w-[42px] h-[42px] flex-none rounded-[14px] flex items-center justify-center text-[13px] font-[700]"
                    style={{ background: 'var(--acc)', color: 'var(--on-acc)' }}
                  >
                    VN
                  </span>
                  <span className="flex-1 min-w-0">
                    <span className="block text-[14px] font-[590] tracking-[-0.15px] text-on-surface">
                      {t('paymentVnpay')}
                    </span>
                    <span className="block text-[11.5px] text-on-surface-muted mt-0.5">{t('paymentVnpaySub')}</span>
                  </span>
                </div>

                {paymentError && (
                  <div role="alert" className="text-[12px] font-medium" style={{ color: 'var(--err)' }}>
                    {t(bookingErrorKey(paymentError))}
                  </div>
                )}

                <button
                  type="button"
                  disabled={creatingPayment}
                  onClick={() => void handlePayWithVnpay()}
                  className="w-full p-[14px] rounded-2xl border-none text-[13.5px] font-[590] tracking-[-0.12px] cursor-pointer transition-all duration-200 hover:opacity-95 active:not-disabled:scale-[0.99] disabled:cursor-progress"
                  style={{
                    background: 'linear-gradient(135deg,#3A73DE,#2C5FC9)',
                    color: 'var(--on-acc)',
                    boxShadow: '0 16px 34px -16px rgba(44,95,201,.7)',
                  }}
                >
                  {creatingPayment ? t('paymentCreating') : t('paymentPayWithVnpay')}
                </button>

                <div className="flex flex-wrap gap-3.5 justify-center pt-1">
                  {[t('paymentTrust1'), t('paymentTrust2'), t('paymentTrust3')].map((label) => (
                    <div key={label} className="flex items-center gap-1.5">
                      <span
                        className="w-3.5 h-3.5 rounded-full flex items-center justify-center text-[8px]"
                        style={{ background: 'var(--ok-soft)', color: 'var(--ok-ink)' }}
                      >
                        ✓
                      </span>
                      <span className="text-[11px] text-on-surface-variant">{label}</span>
                    </div>
                  ))}
                </div>
              </section>
            )}

            {effectiveStep === 'done' && (
              <section
                className="rounded-[28px] flex flex-col items-center text-center overflow-hidden"
                style={{
                  background: 'var(--g1)',
                  border: '1px solid var(--edge)',
                  boxShadow: '0 26px 60px -34px rgb(var(--shadow-rgb) / 0.4), inset 0 1px 0 var(--gloss)',
                  backdropFilter: 'blur(30px) saturate(1.7)',
                  WebkitBackdropFilter: 'blur(30px) saturate(1.7)',
                  animation: 'vRise .55s cubic-bezier(.22,1,.36,1) both',
                }}
              >
                <div className="relative w-full h-[172px] flex-none">
                  <RemoteImage
                    src={hotelDetail?.image_url ?? hotelDetail?.images?.[0]}
                    alt={t('hotelImgAlt', { name: hotelName })}
                    className="absolute inset-0"
                  />
                  <div
                    className="absolute inset-x-0 bottom-0 h-[72px] pointer-events-none"
                    style={{ background: 'linear-gradient(to top, var(--g1), transparent)' }}
                    aria-hidden="true"
                  />
                </div>
                <div className="px-8 pb-8 -mt-[34px] flex flex-col items-center gap-5 w-full">
                  <div
                    className="w-[68px] h-[68px] rounded-full flex items-center justify-center text-[28px] flex-none"
                    style={{
                      background: 'linear-gradient(145deg,#4FB3A5,#2A9187)',
                      color: '#FCFDFE',
                      boxShadow: '0 18px 38px -16px rgba(42,145,135,.7)',
                      border: '4px solid var(--g1)',
                      animation: 'vPop .6s .1s cubic-bezier(.34,1.5,.64,1) both',
                    }}
                  >
                    ✓
                  </div>
                  <div className="-mt-2">
                    <div className="text-[24px] font-[590] tracking-[-0.6px] text-on-surface">{t('checkoutDoneTitle')}</div>
                    <div className="text-[13px] text-on-surface-muted mt-1">{t('checkoutDoneSub')}</div>
                  </div>

                  <div
                    className="flex w-full max-w-[380px] rounded-2xl overflow-hidden border border-edge"
                    style={{ background: 'var(--g2)' }}
                  >
                    <div className="flex-1 px-5 py-3.5 text-left border-r border-line">
                      <div className="text-[9.5px] font-[590] tracking-[0.1em] uppercase text-on-surface-muted">
                        {t('checkoutDoneCode')}
                      </div>
                      <div className="text-[16px] font-[590] tracking-[0.4px] tabular-nums mt-0.5 text-on-surface">
                        {bookedCode}
                      </div>
                    </div>
                    <div className="flex-1 px-5 py-3.5 text-left">
                      <div className="text-[9.5px] font-[590] tracking-[0.1em] uppercase text-on-surface-muted">
                        {t('holdTotal')}
                      </div>
                      <div className="text-[16px] font-[590] tracking-[-0.2px] tabular-nums mt-0.5" style={{ color: 'var(--acc)' }}>
                        {hasAnyTotal ? formatCurrency(grandTotal, i18n.language) : '—'}
                      </div>
                    </div>
                  </div>

                  <div
                    className="w-full max-w-[380px] rounded-2xl border border-edge px-5 py-4"
                    style={{ background: 'var(--g2)' }}
                  >
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
                    {guestsLabel && (
                      <div className="flex items-center justify-center gap-1.5 pt-3 mt-3 border-t border-line">
                        <span className="material-symbols-outlined text-[13px] text-on-surface-muted leading-none" aria-hidden="true">
                          group
                        </span>
                        <span className="text-[11.5px] font-[450] text-on-surface-variant">{guestsLabel}</span>
                      </div>
                    )}
                  </div>

                  {rows.length > 0 && (
                    <div className="w-full max-w-[380px] flex flex-col gap-2 text-left">
                      <div className="text-[9.5px] font-[590] tracking-[0.1em] uppercase text-on-surface-muted px-1">
                        {t('checkoutDoneRoomsLabel')}
                      </div>
                      {rows.map((row) => (
                        <div
                          key={row.id}
                          className="flex items-center gap-3 p-2.5 rounded-2xl bg-glass-2 border border-edge"
                          style={{ boxShadow: '0 10px 24px -18px rgb(var(--shadow-rgb) / 0.5)' }}
                        >
                          <RemoteImage
                            src={row.image}
                            alt={row.name}
                            className="w-[52px] h-[52px] rounded-xl flex-none"
                          />
                          <div className="flex-1 min-w-0">
                            <div className="text-[12.5px] font-[590] text-on-surface truncate">{row.name}</div>
                            <div className="text-[11px] text-on-surface-muted">{t('roomQtyLabel', { count: row.qty })}</div>
                          </div>
                          <div className="flex-none text-[12.5px] font-[590] tabular-nums text-on-surface">
                            {row.total != null ? formatCurrency(row.total, i18n.language) : t('roomPriceOnRequest')}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </section>
            )}
          </main>

          {effectiveStep !== 'done' && (
            <aside className="w-full lg:flex-none lg:w-[344px] flex flex-col gap-3">
              <div
                className="rounded-[24px] overflow-hidden"
                style={{
                  background: 'var(--g1)',
                  border: '1px solid var(--edge)',
                  boxShadow: '0 20px 48px -30px rgb(var(--shadow-rgb) / 0.4), inset 0 1px 0 var(--gloss)',
                  backdropFilter: 'blur(26px) saturate(1.7)',
                  WebkitBackdropFilter: 'blur(26px) saturate(1.7)',
                }}
              >
                <div className="relative h-[132px] overflow-hidden">
                  <RemoteImage
                    src={hotelDetail?.image_url ?? hotelDetail?.images?.[0]}
                    alt={hotelName}
                    className="absolute inset-0"
                  />
                  <div
                    className="absolute inset-x-0 bottom-0 h-[88px] pointer-events-none"
                    style={{ background: 'linear-gradient(to top, var(--g3), transparent)' }}
                    aria-hidden="true"
                  />
                  <div className="absolute left-[18px] right-[18px] bottom-3">
                    <div className="text-[16px] font-[590] tracking-[-0.35px] truncate text-on-surface">{hotelName}</div>
                    {hotelAddress && (
                      <div className="text-[11.5px] font-[450] text-on-surface-variant mt-px truncate">
                        {hotelAddress}
                      </div>
                    )}
                  </div>
                </div>

                <div className="flex flex-col gap-3.5 px-[18px] pt-4 pb-[18px]">
                  {(ci || co) && (
                    <div className="flex items-center gap-3">
                      <div className="text-center">
                        <div className="text-[20px] font-[590] tracking-[-0.5px] leading-none text-on-surface">{ci?.day ?? '—'}</div>
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
                        <div className="text-[20px] font-[590] tracking-[-0.5px] leading-none text-on-surface">{co?.day ?? '—'}</div>
                        <div className="text-[9px] font-[590] tracking-[0.09em] text-on-surface-muted mt-[3px]">
                          {co?.month ?? ''}
                        </div>
                      </div>
                    </div>
                  )}

                  {rows.length > 0 && (
                    <div className="flex flex-col gap-2.5">
                      {rows.map((row, i) => (
                        <div
                          key={row.id}
                          className="flex items-center gap-2.5"
                          style={{ animation: `vFade .4s ${i * 70}ms ease both` }}
                        >
                          <RemoteImage
                            src={row.image}
                            alt={row.name}
                            icon="king_bed"
                            className="w-10 h-10 flex-none rounded-[13px]"
                          />
                          <div className="flex-1 min-w-0">
                            <div className="text-[12.5px] font-[530] tracking-[-0.1px] text-on-surface truncate">
                              {row.name}
                            </div>
                            <div className="text-[10.5px] font-[450] text-on-surface-muted mt-px">
                              {t('roomQtyLabel', { count: row.qty })}
                            </div>
                          </div>
                          <span className="flex-none text-[12px] font-[530] tabular-nums text-on-surface">
                            {row.total != null ? formatCurrency(row.total, i18n.language) : t('roomPriceOnRequest')}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}

                  {hasAnyTotal && (
                    <div className="flex flex-col gap-1.5 pt-3 border-t border-line">
                      <div className="flex justify-between text-[12.5px]">
                        <span className="text-on-surface-variant">{t('checkoutSubtotalLabel')}</span>
                        <span className="font-[450] tabular-nums text-on-surface">{formatCurrency(subtotal, i18n.language)}</span>
                      </div>
                      <div className="flex justify-between text-[12.5px]">
                        <span className="text-on-surface-variant">{t('checkoutTaxesLabel')}</span>
                        <span className="font-[450] tabular-nums text-on-surface">{formatCurrency(tax, i18n.language)}</span>
                      </div>
                      <div className="flex items-baseline justify-between pt-[11px] border-t border-line">
                        <span className="text-[12px] font-[590] tracking-[0.06em] uppercase text-on-surface-muted">
                          {t('holdTotal')}
                        </span>
                        <span className="text-[19px] font-[590] tracking-[-0.5px] tabular-nums text-on-surface">
                          {formatCurrency(grandTotal, i18n.language)}
                        </span>
                      </div>
                    </div>
                  )}

                  <div className="flex flex-col gap-1.5 pt-3 border-t border-line">
                    {ciFull && (
                      <div className="flex items-baseline gap-2.5">
                        <span className="flex-none w-[88px] text-[11px] text-on-surface-muted">
                          {t('policyCheckIn')}
                        </span>
                        <span className="flex-1 min-w-0 text-[12px] font-medium text-on-surface">{ciFull}</span>
                      </div>
                    )}
                    {coFull && (
                      <div className="flex items-baseline gap-2.5">
                        <span className="flex-none w-[88px] text-[11px] text-on-surface-muted">
                          {t('policyCheckOut')}
                        </span>
                        <span className="flex-1 min-w-0 text-[12px] font-medium text-on-surface">{coFull}</span>
                      </div>
                    )}
                    {guestsLabel && (
                      <div className="flex items-baseline gap-2.5">
                        <span className="flex-none w-[88px] text-[11px] text-on-surface-muted">
                          {t('checkoutGuestsLabel')}
                        </span>
                        <span className="flex-1 min-w-0 text-[12px] font-medium text-on-surface">{guestsLabel}</span>
                      </div>
                    )}
                    <div className="flex items-baseline gap-2.5">
                      <span className="flex-none w-[88px] text-[11px] text-on-surface-muted">
                        {t('checkoutPolicyLabel')}
                      </span>
                      <span className="flex-1 min-w-0 text-[12px] font-medium text-on-surface text-pretty">
                        {t('checkoutPolicyValue')}
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            </aside>
          )}
        </div>
      </div>
    </div>
    </div>
  )
}
