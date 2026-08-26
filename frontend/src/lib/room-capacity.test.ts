import { describe, expect, it } from 'vitest'
import { maxRoomsForParty, remainingRoomsAllowed } from './room-capacity'

describe('maxRoomsForParty', () => {
  it('caps at the party size — the exact reported case', () => {
    // 3 travelers -> at most 3 rooms of any one type, regardless of that
    // room type's own capacity (previously ceil(3/5)=1 for a 5-guest room
    // type, which wrongly blocked a party wanting separate large rooms).
    expect(maxRoomsForParty(3)).toBe(3)
    expect(maxRoomsForParty(4)).toBe(4)
  })

  it('falls back to 1 when partySize is missing', () => {
    expect(maxRoomsForParty(null)).toBe(1)
    expect(maxRoomsForParty(undefined)).toBe(1)
    expect(maxRoomsForParty(0)).toBe(1)
  })

  it('rejects a negative party size the same as a missing one', () => {
    expect(maxRoomsForParty(-1)).toBe(1)
  })

  it('rounds a non-integer party size rather than truncating or throwing', () => {
    expect(maxRoomsForParty(3.5)).toBe(4)
  })
})

describe('remainingRoomsAllowed', () => {
  it('caps the TOTAL across every room type, not just this one — the reported bug', () => {
    // 2 guests, nothing in the cart yet: room A can take up to 2.
    expect(remainingRoomsAllowed(2, 0, 0)).toBe(2)
    // Room A now has 1 in the cart (cartTotalQty=1, ownQty=1 for A itself):
    // A can still go up to 2 total (its own qty doesn't shrink its own room).
    expect(remainingRoomsAllowed(2, 1, 1)).toBe(2)
    // Room B, evaluated with that same cart (A=1 already selected elsewhere):
    // only 1 more room total is allowed for the whole party, so B maxes at 1.
    expect(remainingRoomsAllowed(2, 1, 0)).toBe(1)
    // Cart already has 2 rooms total from OTHER types (A=1, C=1): a 3rd,
    // 4th, distinct room type (B, D) must be blocked entirely, not each
    // independently allowed up to 2 — this is exactly the bug: 2 guests
    // must not be able to add room A + room B + room C + room D.
    expect(remainingRoomsAllowed(2, 2, 0)).toBe(0)
  })

  it('never goes negative when the cart is already over the party cap', () => {
    expect(remainingRoomsAllowed(2, 5, 0)).toBe(0)
  })

  it('falls back to the same missing-party-size default as maxRoomsForParty (1)', () => {
    expect(remainingRoomsAllowed(null, 0, 0)).toBe(1)
  })
})
