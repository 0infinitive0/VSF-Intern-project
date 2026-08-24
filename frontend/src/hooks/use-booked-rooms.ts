import { useEffect, useState } from 'react'
import { getBookingReceipt } from '../api/session-client'
import type { RoomHoldApi } from './use-room-hold'
import type { HotelDetail } from '../types'

export interface BookedRoomRow {
  id: string
  name: string
  image?: string | null
  qty: number
  total: number | null
}

export type BookedRoomsStatus = 'loading' | 'ready' | 'none'

/**
 * useBookedRooms — "which room(s) is this itinerary's hotel actually
 * holding/booked for", for the read-only HotelStayPanel (never the full
 * room catalog — HotelDetailPanel's own Rooms section is the place for
 * that). Two sources, tried in order, because neither one alone covers
 * every state the guest can be in:
 *
 *   1. The live roomHold (use-room-hold.ts), when it's actually holding
 *      THIS hotel for THIS session — covers both "just held, itinerary
 *      just built, unpaid" and "paid, same tab", with zero extra network
 *      call. `Booking.room_id` has no name/image of its own, so each row is
 *      cross-referenced against `hotelDetail.rooms` by id — the exact
 *      pattern booking-modal.tsx's own "done" screen already uses
 *      (`rows = roomHold.bookings.map(...)`, lines ~277-286).
 *   2. GET /chat/{sessionId}/booking-receipt (session-client.ts), which is
 *      CONFIRMED-only server-side (payment_service.get_booking_receipt_for_session
 *      filters status == "CONFIRMED") but scoped by session_id independent
 *      of the global roomHold — recovers a paid booking once roomHold has
 *      moved on to a different hotel/session (a different chat held rooms
 *      elsewhere in the same tab, or this is an older, already-paid trip
 *      being reopened). `receipt.rooms` already carry name/image_url, no
 *      cross-reference needed.
 *
 * Neither source found → 'none', empty rows: the caller hides the whole
 * "Phòng đã đặt" section rather than rendering an empty state, matching
 * this codebase's existing convention (HotelDetailPanel/PlaceDetailPanel
 * hide every section with nothing to show).
 *
 * Deliberately does not import roomHold.cartFor/setQty/startHold/switchHold
 * — keeping the draft cart and reserve/switch machinery out of this file
 * entirely means this read-only view can never grow a stepper or a "Giữ
 * phòng" affordance by accident.
 */
export function useBookedRooms(
  hotelId: string | null,
  sessionId: string | null,
  roomHold: RoomHoldApi,
  holdBelongsToSession: boolean,
  hotelDetail: HotelDetail | null,
): { rows: BookedRoomRow[]; status: BookedRoomsStatus } {
  const liveHeld =
    hotelId != null &&
    roomHold.heldHotelId === hotelId &&
    holdBelongsToSession &&
    (roomHold.status === 'HELD' || roomHold.status === 'BOOKED')

  const liveRows: BookedRoomRow[] = liveHeld
    ? roomHold.bookings.map((b) => {
        const room = hotelDetail?.rooms?.find((r) => r.id === b.room_id)
        return {
          id: b.id,
          name: room?.name ?? b.room_id,
          image: room?.images?.[0],
          qty: b.room_count,
          total: b.total_amount != null ? Number(b.total_amount) : null,
        }
      })
    : []

  const [receiptRows, setReceiptRows] = useState<BookedRoomRow[]>([])
  const [receiptStatus, setReceiptStatus] = useState<'idle' | 'loading' | 'done'>('idle')

  useEffect(() => {
    // Only worth fetching when the live source came up empty — the receipt
    // is a fallback, not something to reconcile against the live one.
    if (liveHeld || hotelId == null || sessionId == null) {
      setReceiptRows([])
      setReceiptStatus('idle')
      return
    }
    let cancelled = false
    setReceiptStatus('loading')
    getBookingReceipt(sessionId).then((receipt) => {
      if (cancelled) return
      setReceiptRows(
        receipt && receipt.rooms.length > 0
          ? receipt.rooms.map((r) => ({
              id: r.room_id,
              name: r.name,
              image: r.image_url,
              qty: r.room_count,
              total: r.total_amount != null ? Number(r.total_amount) : null,
            }))
          : [],
      )
      setReceiptStatus('done')
    })
    return () => {
      cancelled = true
    }
  }, [liveHeld, hotelId, sessionId])

  if (liveHeld) return { rows: liveRows, status: 'ready' }
  // 'idle' means the fetch will never run at all (no hotelId/sessionId yet) —
  // that's "nothing to show", not "still loading".
  if (receiptStatus === 'loading') return { rows: [], status: 'loading' }
  return receiptRows.length > 0 ? { rows: receiptRows, status: 'ready' } : { rows: [], status: 'none' }
}
