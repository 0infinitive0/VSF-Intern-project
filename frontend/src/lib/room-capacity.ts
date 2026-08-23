/**
 * How many units of ONE room type a party needs to all fit, from the trip's
 * party size and that room type's own `max_guests` capacity — e.g. 4
 * travelers and a 2-guest room type → `ceil(4 / 2) = 2` rooms (not 3: three
 * rooms would sleep 6, two more than the party actually has).
 *
 * Applied independently per room type (a different room type with a
 * different `max_guests` gets its own limit) — this never sums capacity
 * across different room types in the same cart.
 *
 * Missing data degrades to the conservative default of 1, never 0 — an
 * unknown party size or unknown room capacity must not silently block
 * booking a room, matching the "max_guests không có → 1 phòng" rule from
 * plans/260820-1126-chat-driven-room-booking/phase-01-booking-intent-and-proposal.md.
 */
export function roomsNeededForParty(
  partySize: number | null | undefined,
  maxGuests: number | null | undefined,
): number {
  if (!partySize || partySize <= 0 || !maxGuests || maxGuests <= 0) return 1
  return Math.max(1, Math.ceil(partySize / maxGuests))
}
