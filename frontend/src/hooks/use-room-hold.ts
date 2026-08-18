/**
 * use-room-hold.ts — owns the room-selection cart AND the resulting hold
 * (reserve → countdown → confirm/cancel) against the real
 * /api/v1/bookings* endpoints (backend/src/api/routes.py, booking-client.ts).
 * Every reservation/confirm/cancel call in this hook is a real network call
 * with a real server-assigned `expires_at`; payment is now real too — see
 * booking-modal.tsx and api/payment-client.ts for the VNPay handoff (plan
 * 260818-vnpay-payment-and-email-confirmation).
 *
 * One booking per distinct room TYPE in the cart, because
 * BookingReservationRequest takes a single room_id (+ room_count) — a cart
 * with 2 Superior + 1 Deluxe becomes two POST /bookings calls, tracked here
 * as one "hold group". The group's countdown uses the EARLIEST expires_at in
 * the group (whichever reservation lapses first ends the whole hold);
 * cancel/recheck releases every booking in the group.
 *
 * UI-only state, same as use-focus-mode.ts — there is no ChatState slot for
 * "which rooms are held" (lib/derive-stage.ts's StageView has no 5th
 * branch), so this hook is the source of truth. The caller (App.tsx) reacts
 * to `status` becoming 'HELD' to fire the EXISTING itinerary-build call
 * (selectHotel), which is otherwise untouched.
 *
 * Persisted to sessionStorage (heldHotelId + bookings, whenever a hold is
 * live) because paying with VNPay means a REAL browser navigation away from
 * the SPA and back — every in-memory React state would otherwise be gone by
 * the time the guest returns (see App.tsx's consumeVnpayReturn, which reads
 * the URL VNPay bounces the browser back to). sessionStorage, not
 * localStorage: a payment-in-flight marker should survive exactly this one
 * round trip within the same tab, not linger across unrelated future visits.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { cancelBooking, reserveBooking } from '../api/booking-client'
import { getGuestRef } from '../lib/guest-ref'
import type { Booking, RoomDetail } from '../types'

const STORAGE_KEY = 'vota_room_hold_v1'

interface PersistedHold {
  heldHotelId: string
  bookings: Booking[]
  /** Set right before the VNPay redirect (booking-modal.tsx) — the payment
   * this hold is mid-checkout for, if any. Persisted so App.tsx's
   * consumeVnpayReturn knows WHICH payment to poll after the guest comes
   * back, without needing to smuggle the id through VNPay's return URL. */
  paymentId: string | null
  /** True once markBooked() confirmed a real VNPay PAID result for this
   * hold. Every OTHER status re-derives safely on reload without being
   * persisted itself (HOLDING always resumes as HELD; a truly lapsed HELD
   * self-corrects to EXPIRED within one tick via the expiry effect below —
   * see the status-init comment) but BOOKED can't: nothing re-asserts "this
   * really got paid" from bookings/expires_at alone. Without this flag, a
   * reload of the post-payment "Done" screen would resume as HELD against
   * an expires_at that's almost always already in the past by then, and
   * immediately flip to EXPIRED — telling an already-paid guest their hold
   * expired. */
  booked: boolean
}

function loadPersistedHold(): PersistedHold | null {
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<PersistedHold>
    if (!parsed.heldHotelId || !Array.isArray(parsed.bookings) || parsed.bookings.length === 0) {
      return null
    }
    return {
      heldHotelId: parsed.heldHotelId,
      bookings: parsed.bookings,
      paymentId: parsed.paymentId ?? null,
      booked: parsed.booked ?? false,
    }
  } catch {
    return null
  }
}

function persistHold(data: PersistedHold | null) {
  try {
    if (data) window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(data))
    else window.sessionStorage.removeItem(STORAGE_KEY)
  } catch {
    // sessionStorage unavailable (private-mode edge cases) — the hold still
    // works for this tab's in-memory lifetime, it just won't survive a real
    // navigation away (VNPay's redirect). Nothing else degrades.
  }
}

export type HoldStatus = 'IDLE' | 'HOLDING' | 'HELD' | 'EXPIRED' | 'BOOKED' | 'ERROR'

export interface RoomStay {
  /** ISO date (YYYY-MM-DD), straight from ChatState.intake.start_date/end_date. */
  checkInDate: string
  checkOutDate: string
}

/** Local cart: room id -> unit count, for ONE hotel. Mirrors the design's
 * `state.sel[hotelId][roomId] = qty`. Kept one-per-hotel by the caller
 * (hotelId is always passed in) so switching the open hotel never mixes
 * carts — same guarantee hotel-detail-panel.tsx's old single-pick
 * `roomPicks` already gave. */
export type RoomCart = Record<string, number>

const MAX_QTY_PER_ROOM = 4
const DEFAULT_CHECK_IN_TIME = '14:00:00'
const DEFAULT_CHECK_OUT_TIME = '12:00:00'

function nightsBetween(checkIn: string, checkOut: string): number {
  const start = new Date(checkIn).getTime()
  const end = new Date(checkOut).getTime()
  if (!Number.isFinite(start) || !Number.isFinite(end)) return 1
  const nights = Math.round((end - start) / 86_400_000)
  return nights > 0 ? nights : 1
}

export function useRoomHold() {
  const [cartByHotel, setCartByHotel] = useState<Record<string, RoomCart>>({})
  const [heldHotelId, setHeldHotelId] = useState<string | null>(() => loadPersistedHold()?.heldHotelId ?? null)
  const [bookings, setBookings] = useState<Booking[]>(() => loadPersistedHold()?.bookings ?? [])
  // A hold restored from sessionStorage resumes as 'BOOKED' if it was
  // persisted that way (see PersistedHold.booked), else 'HELD' — HOLDING is
  // a transient, mid-request state that must never be trusted after a real
  // page reload (whatever request was in flight is gone). If a resumed HELD
  // actually expired while the guest was away, the expiry-detection effect
  // below flips it to EXPIRED within one tick; if it was actually already
  // PAID but this is the FIRST return trip (VNPay's IPN landed before the
  // guest even got back), App.tsx's consumeVnpayReturn calls markBooked()
  // to correct it — this initial guess is just what renders before that.
  const [status, setStatus] = useState<HoldStatus>(() => {
    const persisted = loadPersistedHold()
    if (!persisted) return 'IDLE'
    return persisted.booked ? 'BOOKED' : 'HELD'
  })
  const [paymentId, setPaymentId] = useState<string | null>(() => loadPersistedHold()?.paymentId ?? null)
  const [error, setError] = useState<string | null>(null)
  const [now, setNow] = useState(() => Date.now())
  const guestRefRef = useRef<string>('')
  if (!guestRefRef.current) guestRefRef.current = getGuestRef()

  // Keeps sessionStorage in sync with the live hold — cleared once there's
  // nothing worth restoring (IDLE: released/never started; ERROR: the
  // startHold that would have populated `bookings` already failed and rolled
  // back).
  useEffect(() => {
    if (heldHotelId && bookings.length > 0 && status !== 'IDLE' && status !== 'ERROR') {
      persistHold({ heldHotelId, bookings, paymentId, booked: status === 'BOOKED' })
    } else if (status === 'IDLE') {
      persistHold(null)
    }
  }, [heldHotelId, bookings, status, paymentId])

  // Ticks the countdown once a second, only while a hold is actually
  // counting down — no timer running in IDLE/HOLDING/BOOKED/EXPIRED.
  useEffect(() => {
    if (status !== 'HELD') return
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [status])

  const cartFor = useCallback((hotelId: string): RoomCart => cartByHotel[hotelId] ?? {}, [cartByHotel])

  const setQty = useCallback((hotelId: string, roomId: string, qty: number) => {
    setCartByHotel((prev) => {
      const current = { ...(prev[hotelId] ?? {}) }
      const clamped = Math.max(0, Math.min(MAX_QTY_PER_ROOM, qty))
      if (clamped === 0) delete current[roomId]
      else current[roomId] = clamped
      return { ...prev, [hotelId]: current }
    })
  }, [])

  const cartCount = useCallback(
    (hotelId: string) => Object.values(cartByHotel[hotelId] ?? {}).reduce((n, q) => n + q, 0),
    [cartByHotel],
  )

  // Earliest expires_at across the hold group — the group is only as
  // long-lived as its shortest-held reservation.
  const expiresAtMs = bookings.reduce<number | null>((earliest, b) => {
    if (!b.expires_at) return earliest
    const t = new Date(b.expires_at).getTime()
    if (!Number.isFinite(t)) return earliest
    return earliest == null ? t : Math.min(earliest, t)
  }, null)
  const holdLeftMs = expiresAtMs != null ? Math.max(0, expiresAtMs - now) : 0

  // The countdown reaching zero is a real transition, not just a display
  // fact — flip status here (once) so every consumer (hold banner, booking
  // modal) agrees on 'EXPIRED' instead of each re-deriving it from now/expiresAtMs.
  useEffect(() => {
    if (status === 'HELD' && expiresAtMs != null && now >= expiresAtMs) {
      setStatus('EXPIRED')
    }
  }, [status, expiresAtMs, now])

  /** The actual reserve-everything-in-the-cart mechanics, shared by
   * `startHold` and `switchHold` below. Deliberately has NO `status` check
   * of its own (only the empty-cart guard) — see `switchHold`'s doc comment
   * for why: calling through `startHold`'s own `status === 'HOLDING'` guard
   * from inside `switchHold` (i.e. right after `await releaseHold()`, in
   * the same tick) would read a STALE `status` closed over before
   * `releaseHold` ran, still 'HELD' at that point, and block itself. Every
   * caller of this helper is responsible for its own front-door guard. */
  const runReservation = useCallback(
    async (hotelId: string, rooms: RoomDetail[], stay: RoomStay, onHeld?: () => void) => {
      const cart = cartByHotel[hotelId] ?? {}
      const entries = Object.entries(cart).filter(([, qty]) => qty > 0)
      if (entries.length === 0) return
      setStatus('HOLDING')
      setError(null)
      const nights = nightsBetween(stay.checkInDate, stay.checkOutDate)
      const roomById = new Map(rooms.map((r) => [r.id, r]))
      const created: Booking[] = []
      try {
        for (const [roomId, qty] of entries) {
          const room = roomById.get(roomId)
          const amount = room?.price?.amount
          const booking = await reserveBooking({
            room_id: roomId,
            temporary_user_ref: guestRefRef.current,
            check_in_date: stay.checkInDate,
            check_in_time: DEFAULT_CHECK_IN_TIME,
            check_out_date: stay.checkOutDate,
            check_out_time: DEFAULT_CHECK_OUT_TIME,
            room_count: qty,
            // Only sent when the room actually has a real price (never 0,
            // never invented) — matches this app's "no fabricated data" rule
            // for anything shown back to the user later (booking summary).
            ...(amount != null && Number.isFinite(amount) && amount > 0
              ? { total_amount: amount * qty * nights, currency: room?.price?.currency ?? undefined }
              : {}),
          })
          created.push(booking)
        }
        setBookings(created)
        setHeldHotelId(hotelId)
        setStatus('HELD')
        setNow(Date.now())
        onHeld?.()
      } catch (err) {
        // Partial failure releases whatever DID get reserved — never leave
        // an orphaned hold the user can neither see nor release.
        await Promise.allSettled(
          created.map((b) => cancelBooking(b.id, { temporary_user_ref: guestRefRef.current }).catch(() => null)),
        )
        setBookings([])
        setHeldHotelId(null)
        setStatus('ERROR')
        setError(err instanceof Error ? err.message : String(err))
      }
    },
    [cartByHotel],
  )

  const startHold = useCallback(
    async (hotelId: string, rooms: RoomDetail[], stay: RoomStay, onHeld?: () => void) => {
      if (status === 'HOLDING') return
      await runReservation(hotelId, rooms, stay, onHeld)
    },
    [status, runReservation],
  )

  const releaseHold = useCallback(async () => {
    const toRelease = bookings
    setBookings([])
    setHeldHotelId(null)
    setStatus('IDLE')
    setError(null)
    setPaymentId(null)
    await Promise.allSettled(
      toRelease.map((b) => cancelBooking(b.id, { temporary_user_ref: guestRefRef.current }).catch(() => null)),
    )
  }, [bookings])

  /** "Kiểm tra lại phòng" — the expired-hold recovery path (design's
   * recheckRooms). Functionally the same release as releaseHold; kept as its
   * own name so callers read intent instead of a generic "release". */
  const recheckRooms = useCallback(async () => {
    await releaseHold()
  }, [releaseHold])

  /** Replaces whatever is currently held (same hotel with a different room
   * mix, OR an entirely different hotel) with a brand-new hold for
   * `hotelId`/`rooms`/`stay` — always a full release-then-reserve, so the
   * WHOLE new group gets a fresh 15-minute TTL (the backend has no
   * extend/partial-preserve capability; every reservation is a plain
   * INSERT — see backend/scripts/migrations/20260818_add_booking_reservation_rpcs.sql).
   * Calls `runReservation` directly rather than `releaseHold()` followed by
   * `startHold()` — see `runReservation`'s doc comment for the stale-closure
   * hazard that would otherwise cause this to block itself. Used by
   * hotel-detail-panel.tsx for both "update my room selection at the hotel
   * I'm already holding" and "switch my hold to a different hotel"
   * (the latter behind a confirm dialog — see plan
   * 260818-vnpay-payment-and-email-confirmation's addendum). */
  const switchHold = useCallback(
    async (hotelId: string, rooms: RoomDetail[], stay: RoomStay, onHeld?: () => void) => {
      if (status === 'HOLDING') return
      await releaseHold()
      await runReservation(hotelId, rooms, stay, onHeld)
    },
    [status, releaseHold, runReservation],
  )

  /** Called by booking-modal.tsx right before `window.location.href =
   * pay_url` — records WHICH payment this hold is now mid-checkout for, so
   * it survives the real navigation away (see the module doc comment) and
   * App.tsx's consumeVnpayReturn knows what to poll once the guest is back. */
  const setPendingPayment = useCallback((id: string) => {
    setPaymentId(id)
  }, [])

  /** Called once App.tsx's consumeVnpayReturn confirms (via GET
   * /payments/{id}) that a real VNPay payment PAID — the authoritative
   * confirmation always comes from that call, never from sessionStorage or
   * the return URL's own query params (see the module doc comment). Doesn't
   * need fresh Booking objects from the server: nothing downstream reads
   * `booking.status` off these (the done screen renders hotel/room/total
   * from `bookings` + a hotel-detail lookup, none of which depends on it),
   * so flipping the local `status` is the whole job. */
  const markBooked = useCallback(() => {
    setStatus('BOOKED')
  }, [])

  return {
    cartFor,
    setQty,
    cartCount,
    heldHotelId,
    bookings,
    status,
    error,
    holdLeftMs,
    paymentId,
    startHold,
    switchHold,
    releaseHold,
    recheckRooms,
    setPendingPayment,
    markBooked,
    guestRef: guestRefRef.current,
  }
}

export type RoomHoldApi = ReturnType<typeof useRoomHold>
