import { describe, expect, it } from 'vitest'
import { dayStayPoints } from './day-stay-points'

describe('dayStayPoints', () => {
  it('uses the current hotel as both the start and end point of a day', () => {
    expect(dayStayPoints({ name: 'Hotel Majestic Saigon' })).toEqual([
      { position: 'start', hotelName: 'Hotel Majestic Saigon' },
      { position: 'end', hotelName: 'Hotel Majestic Saigon' },
    ])
  })

  it('does not invent stay points when no hotel name is available', () => {
    expect(dayStayPoints(null)).toEqual([])
    expect(dayStayPoints({ name: '   ' })).toEqual([])
  })
})
