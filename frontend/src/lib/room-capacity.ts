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

/**
 * Upper bound for ONE room type's qty stepper, given how much of the
 * party's total room allowance (`maxRoomsForParty`) every OTHER room type
 * already selected in the same hotel's cart has used up.
 *
 * `maxRoomsForParty` alone is a per-room-type number — applied identically
 * to every room type in a hotel's room list, it caps each type on its own
 * but never the sum across types. A party of 2 could then add 1 of room A,
 * 1 of room B, 1 of room C, etc., each individually within the cap, and end
 * up holding far more rooms than travelers. This function is the fix: it
 * subtracts what's already used elsewhere in the cart before capping this
 * room type, so the TOTAL across every type in the cart never exceeds
 * `maxRoomsForParty(partySize)`.
 *
 * `ownQty` (this room type's own current qty, part of `cartTotalQty`) is
 * excluded from "already used" — otherwise a room type's own selector would
 * shrink its own headroom as it goes up, blocking it from ever reaching the
 * full party allowance by itself.
 */
export function remainingRoomsAllowed(
  partySize: number | null | undefined,
  cartTotalQty: number,
  ownQty: number,
): number {
  const roomsAllowed = maxRoomsForParty(partySize)
  const otherRoomsQty = cartTotalQty - ownQty
  return Math.max(0, roomsAllowed - otherRoomsQty)
}
