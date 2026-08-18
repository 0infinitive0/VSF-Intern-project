/**
 * room-cart-diff.ts — compares a local room cart (use-room-hold.ts's
 * `RoomCart`) against the room-type/quantity composition of a live hold's
 * bookings. Used by hotel-detail-panel.tsx to decide whether viewing the
 * already-held hotel with an edited cart should offer an "update selection"
 * action, or whether the cart still matches what's already held (nothing to
 * submit) — see plan 260818-vnpay-payment-and-email-confirmation's addendum
 * on editing/switching an active hold.
 */
import type { RoomCart } from '../hooks/use-room-hold'
import type { Booking } from '../types'

/** True iff `cart` (zero-qty entries ignored) has exactly the same set of
 * room_id -> room_count pairs as `bookings`. An empty cart against an empty
 * booking list is trivially true, but callers only care about this
 * comparison once the cart is non-empty (see hotel-detail-panel.tsx's
 * `cartChanged`, which also requires `cartCount > 0`). */
export function cartMatchesHeldBookings(cart: RoomCart, bookings: Booking[]): boolean {
  const cartEntries = Object.entries(cart).filter(([, qty]) => qty > 0)
  if (cartEntries.length !== bookings.length) return false
  const heldQtyByRoom = new Map(bookings.map((b) => [b.room_id, b.room_count]))
  return cartEntries.every(([roomId, qty]) => heldQtyByRoom.get(roomId) === qty)
}
