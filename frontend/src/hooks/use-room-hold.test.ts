import { describe, expect, it } from 'vitest'
import { applyCartQty, shouldReleaseHoldForDeletedSession } from './use-room-hold'

describe('applyCartQty', () => {
  it('sets a fresh hotel entry when the cart was empty', () => {
    const next = applyCartQty({}, 'hotel-a', 'room-1', 2, null)
    expect(next).toEqual({ 'hotel-a': { 'room-1': 2 } })
  })

  it('clears an unrelated draft-only hotel when editing a different one', () => {
    const prev = { 'hotel-a': { 'room-1': 2 } }
    const next = applyCartQty(prev, 'hotel-b', 'room-9', 1, null)
    expect(next).toEqual({ 'hotel-b': { 'room-9': 1 } })
    expect(next['hotel-a']).toBeUndefined()
  })

  it('preserves the HELD hotel entry when editing a different (draft-only) hotel', () => {
    const prev = { 'hotel-a': { 'room-1': 2 } }
    // hotel-a is the one actually held — browsing hotel-b (never touched
    // before) and adding a room to its cart must not wipe hotel-a's entry
    // (it mirrors a real booking, not draft state — see
    // hotel-detail-panel.tsx's RoomCard/cartChanged, which would otherwise
    // misread the held hotel as "nothing selected").
    const next = applyCartQty(prev, 'hotel-b', 'room-9', 3, 'hotel-a')
    expect(next).toEqual({ 'hotel-a': { 'room-1': 2 }, 'hotel-b': { 'room-9': 3 } })
  })

  it('drops every OTHER draft hotel, keeping only the held one and the one being edited', () => {
    const prev = { 'hotel-a': { 'room-1': 2 }, 'hotel-b': { 'room-5': 1 }, 'hotel-c': { 'room-7': 1 } }
    const next = applyCartQty(prev, 'hotel-b', 'room-5', 2, 'hotel-a')
    expect(next).toEqual({ 'hotel-a': { 'room-1': 2 }, 'hotel-b': { 'room-5': 2 } })
    expect(next['hotel-c']).toBeUndefined()
  })

  it('editing the held hotel itself does not duplicate or drop its own entry', () => {
    const prev = { 'hotel-a': { 'room-1': 2 } }
    const next = applyCartQty(prev, 'hotel-a', 'room-1', 3, 'hotel-a')
    expect(next).toEqual({ 'hotel-a': { 'room-1': 3 } })
  })

  it('clamps quantity to [0, MAX_QTY_PER_ROOM] and removes the room entry at 0', () => {
    const next = applyCartQty({}, 'hotel-a', 'room-1', 0, null)
    expect(next).toEqual({ 'hotel-a': {} })

    const overMax = applyCartQty({}, 'hotel-a', 'room-1', 99, null)
    expect(overMax).toEqual({ 'hotel-a': { 'room-1': 4 } })

    const negative = applyCartQty({}, 'hotel-a', 'room-1', -5, null)
    expect(negative).toEqual({ 'hotel-a': {} })
  })

  it('a heldHotelId matching the hotel being edited is not treated as "another" hotel to preserve', () => {
    const prev = { 'hotel-a': { 'room-1': 2 } }
    const next = applyCartQty(prev, 'hotel-a', 'room-2', 1, 'hotel-a')
    expect(next).toEqual({ 'hotel-a': { 'room-1': 2, 'room-2': 1 } })
  })
})

describe('shouldReleaseHoldForDeletedSession', () => {
  it('is true when HELD and the deleted session is the one holding', () => {
    expect(shouldReleaseHoldForDeletedSession('HELD', 'session-a', 'session-a')).toBe(true)
  })

  it('is false when the deleted session is a DIFFERENT session', () => {
    expect(shouldReleaseHoldForDeletedSession('HELD', 'session-a', 'session-b')).toBe(false)
  })

  it('is false for BOOKED even if the session matches — a paid booking must survive session deletion', () => {
    expect(shouldReleaseHoldForDeletedSession('BOOKED', 'session-a', 'session-a')).toBe(false)
  })

  it('is false for every other status (IDLE/HOLDING/EXPIRED/ERROR) even if the session matches', () => {
    expect(shouldReleaseHoldForDeletedSession('IDLE', 'session-a', 'session-a')).toBe(false)
    expect(shouldReleaseHoldForDeletedSession('HOLDING', 'session-a', 'session-a')).toBe(false)
    expect(shouldReleaseHoldForDeletedSession('EXPIRED', 'session-a', 'session-a')).toBe(false)
    expect(shouldReleaseHoldForDeletedSession('ERROR', 'session-a', 'session-a')).toBe(false)
  })

  it('is false when heldSessionId is null (hold created outside any session)', () => {
    expect(shouldReleaseHoldForDeletedSession('HELD', null, 'session-a')).toBe(false)
  })
})
