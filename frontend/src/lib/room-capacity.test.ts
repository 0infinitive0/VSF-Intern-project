import { describe, expect, it } from 'vitest'
import { roomsNeededForParty } from './room-capacity'

describe('roomsNeededForParty', () => {
  it('divides evenly', () => {
    expect(roomsNeededForParty(4, 2)).toBe(2)
  })

  it('rounds a remainder up rather than down (never leaves someone without a bed)', () => {
    // 5 travelers, 2 per room -> 2 rooms sleeps only 4, so 3 rooms are needed.
    expect(roomsNeededForParty(5, 2)).toBe(3)
  })

  it('never returns fewer rooms than the party needs — the exact reported case', () => {
    // 4 travelers, room capacity 2: 2 rooms is correct (sleeps exactly 4);
    // 3 rooms would sleep 6, two more seats than the party has.
    expect(roomsNeededForParty(4, 2)).toBe(2)
  })

  it('a party smaller than one room capacity still needs at least 1 room, not 0', () => {
    expect(roomsNeededForParty(1, 4)).toBe(1)
  })

  it('falls back to 1 when partySize is missing', () => {
    expect(roomsNeededForParty(null, 2)).toBe(1)
    expect(roomsNeededForParty(undefined, 2)).toBe(1)
    expect(roomsNeededForParty(0, 2)).toBe(1)
  })

  it('falls back to 1 when maxGuests is missing', () => {
    expect(roomsNeededForParty(4, null)).toBe(1)
    expect(roomsNeededForParty(4, undefined)).toBe(1)
    expect(roomsNeededForParty(4, 0)).toBe(1)
  })

  it('falls back to 1 when both are missing', () => {
    expect(roomsNeededForParty(null, null)).toBe(1)
  })

  it('rejects negative inputs the same as missing ones', () => {
    expect(roomsNeededForParty(-1, 2)).toBe(1)
    expect(roomsNeededForParty(4, -1)).toBe(1)
  })
})
