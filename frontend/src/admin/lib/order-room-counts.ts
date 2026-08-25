import type { OrderDetailResponse } from '../api/orders-client'

/** order-room-counts.ts — shared "how many rooms would this action touch"
 * math for D2/D3 (phase-06-order-actions.md): the confirm/cancel dialogs'
 * "Xác nhận {n} phòng"/"Huỷ {n} phòng" button labels, and the header's
 * decision to show either button at all, must agree on the same `n` --
 * `sum(room_count)` of the still-actionable bookings, not `rooms.length`. */

export function confirmableRoomCount(order: OrderDetailResponse): number {
  return order.rooms.filter((room) => room.status === 'RESERVED').reduce((sum, room) => sum + room.room_count, 0)
}

export function cancellableRoomCount(order: OrderDetailResponse): number {
  return order.rooms
    .filter((room) => room.status !== 'CANCELLED' && room.status !== 'EXPIRED')
    .reduce((sum, room) => sum + room.room_count, 0)
}

/** `booking_id -> room_count` -- confirm/cancel's response `results[]` is
 * per-booking, but the plan's result banners talk in rooms ("Đã xác nhận N
 * phòng"), same unit as the button label. Lets callers turn a list of
 * booking ids into the room count they actually cover. */
export function roomCountByBookingId(order: OrderDetailResponse): Record<string, number> {
  return Object.fromEntries(order.rooms.map((room) => [room.booking_id, room.room_count]))
}

export function sumRoomCounts(order: OrderDetailResponse, bookingIds: string[]): number {
  const counts = roomCountByBookingId(order)
  return bookingIds.reduce((sum, id) => sum + (counts[id] ?? 0), 0)
}

export function orderHotelNames(order: OrderDetailResponse): string {
  const names = Array.from(new Set(order.rooms.map((room) => room.hotel_name).filter((name): name is string => !!name)))
  return names.join(', ') || '—'
}
