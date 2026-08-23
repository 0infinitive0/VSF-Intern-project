import { describe, expect, it } from 'vitest'
import { maxRoomsForParty } from './room-capacity'

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
