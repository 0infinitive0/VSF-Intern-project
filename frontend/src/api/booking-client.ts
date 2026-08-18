/**
 * booking-client.ts — wraps the real hotel-room hold/confirm/cancel API
 * (backend/src/api/routes.py's POST /bookings, /bookings/{id}/confirm,
 * /bookings/{id}/cancel — backed by Supabase RPCs create_booking_reservation
 * / confirm_booking_reservation / cancel_booking; not a mock, not simulated).
 *
 * There is no payment gateway behind `confirm` yet (booking_service.py's
 * confirm_booking simply flips status to CONFIRMED, assuming payment already
 * happened) — see use-room-hold.ts and booking-modal.tsx for how the
 * checkout flow's simulated payment step still ends in a real confirm call.
 *
 * Mirrors chat-client.ts's request<T>() error/JSON handling rather than
 * place-client.ts's degrade-to-null one: a hold/confirm/cancel failure is
 * something the caller must surface (e.g. "this room just sold out"), not
 * something that can quietly disappear.
 */
import type { Booking, BookingOwnershipRequest, BookingReservationRequest } from '../types'
import { authHeaders } from './auth-headers'

const BASE = (import.meta.env.VITE_API_BASE || '') + '/api/v1'

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(BASE + path, {
    method,
    headers: { 'Content-Type': 'application/json', ...(await authHeaders()) },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })

  const text = await res.text()
  let data: unknown = null
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      throw new Error(`Non-JSON response (${res.status}): ${text.slice(0, 200)}`)
    }
  }

  if (!res.ok) {
    const detail =
      data && typeof data === 'object' && 'detail' in data
        ? (data as { detail?: unknown }).detail
        : undefined
    throw new Error(typeof detail === 'string' ? detail : detail != null ? JSON.stringify(detail) : text)
  }

  return data as T
}

/**
 * Hold one room type for `reservation.room_count` units — creates a Booking
 * with a real server-assigned `expires_at`, the hold countdown's only source
 * of truth. The wire contract has no multi-room-type verb, so a cart with
 * several distinct room types means one call per type (see use-room-hold.ts).
 */
export async function reserveBooking(reservation: BookingReservationRequest): Promise<Booking> {
  return request('POST', '/bookings', reservation)
}

/**
 * Flip a held booking to CONFIRMED. Real call, real DB row — but see the
 * module doc comment: nothing upstream of this verifies an actual payment
 * yet, so callers must only reach it after their own checkout step is done.
 */
export async function confirmBooking(
  bookingId: string,
  ownership: BookingOwnershipRequest,
): Promise<Booking> {
  return request('POST', `/bookings/${encodeURIComponent(bookingId)}/confirm`, ownership)
}

/** Release a held booking — an explicit "đổi ý", a hold that expired, or
 * cleanup for the rest of a hold group when one reservation in it failed. */
export async function cancelBooking(
  bookingId: string,
  ownership: BookingOwnershipRequest,
): Promise<Booking> {
  return request('POST', `/bookings/${encodeURIComponent(bookingId)}/cancel`, ownership)
}
