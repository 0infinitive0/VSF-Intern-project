import { describe, expect, it } from 'vitest'
import type { Booking } from '../types'
import { cartMatchesHeldBookings } from './room-cart-diff'

function makeBooking(roomId: string, roomCount: number): Booking {
  return {
    id: `booking-${roomId}`,
    room_id: roomId,
    check_in_date: '2026-09-01',
    check_in_time: '14:00:00',
    check_out_date: '2026-09-03',
    check_out_time: '12:00:00',
    room_count: roomCount,
    status: 'RESERVED',
    expires_at: '2026-09-01T00:15:00Z',
    total_amount: null,
    currency: null,
  }
}

describe('cartMatchesHeldBookings', () => {
  it('is true when the cart exactly matches the held room_id/room_count pairs', () => {
    const bookings = [makeBooking('room-a', 2), makeBooking('room-b', 1)]
    expect(cartMatchesHeldBookings({ 'room-a': 2, 'room-b': 1 }, bookings)).toBe(true)
  })

  it('ignores order and zero-quantity cart entries', () => {
    const bookings = [makeBooking('room-a', 2), makeBooking('room-b', 1)]
    expect(cartMatchesHeldBookings({ 'room-b': 1, 'room-c': 0, 'room-a': 2 }, bookings)).toBe(true)
  })

  it('is false when a room quantity differs', () => {
    const bookings = [makeBooking('room-a', 2)]
    expect(cartMatchesHeldBookings({ 'room-a': 3 }, bookings)).toBe(false)
  })

  it('is false when the cart has an extra room type not in the hold', () => {
    const bookings = [makeBooking('room-a', 2)]
    expect(cartMatchesHeldBookings({ 'room-a': 2, 'room-c': 1 }, bookings)).toBe(false)
  })

  it('is false when the cart is missing a room type the hold has', () => {
    const bookings = [makeBooking('room-a', 2), makeBooking('room-b', 1)]
    expect(cartMatchesHeldBookings({ 'room-a': 2 }, bookings)).toBe(false)
  })

  it('is true for an empty cart against an empty hold (degenerate case)', () => {
    expect(cartMatchesHeldBookings({}, [])).toBe(true)
  })
})
