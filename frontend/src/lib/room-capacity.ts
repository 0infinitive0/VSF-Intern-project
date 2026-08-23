/**
 * Max units of ONE room type a party is allowed to select, from the trip's
 * party size alone — e.g. 3 travelers → at most 3 rooms of any given type, 4
 * travelers → at most 4.
 *
 * Deliberately NOT `ceil(partySize / room.max_guests)`: that computes the
 * MINIMUM rooms needed if everyone packs in to full capacity, which is the
 * wrong number to use as a MAXIMUM allowed — it over-restricts large-capacity
 * rooms (3 travelers + a 5-guest room type would cap at ceil(3/5)=1, blocking
 * a party that wants 2-3 separate large rooms even though inventory allows
 * it). No party legitimately needs more than one room of a given type per
 * traveler (the extreme case is everyone in their own room), so party size
 * itself is the correct upper bound, independent of that room type's own
 * capacity. `room.max_guests` keeps its existing role — the "Ngủ được N
 * khách" display line (room-card.tsx) — it's just no longer part of this
 * calculation.
 *
 * Applied independently per room type; real inventory (`available_room_count`)
 * and the cart's own absolute safety ceiling still cap it further at the
 * call site (hotel-detail-panel.tsx, use-room-hold.ts).
 *
 * Missing/invalid party size degrades to the conservative default of 1,
 * never 0 or unlimited — an unknown party size must not silently unlock an
 * unrestricted quantity, but also must never block booking a room entirely.
 */
export function maxRoomsForParty(partySize: number | null | undefined): number {
  if (!partySize || partySize <= 0) return 1
  return Math.max(1, Math.round(partySize))
}
