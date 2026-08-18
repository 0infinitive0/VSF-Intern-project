export type DayStayPoint = {
  position: 'start' | 'end'
  hotelName: string
}

type CurrentHotel = { name?: string | null } | null | undefined

/** The selected hotel anchors every displayed itinerary day. */
export function dayStayPoints(hotel: CurrentHotel): DayStayPoint[] {
  const hotelName = hotel?.name?.trim()
  if (!hotelName) return []

  return [
    { position: 'start', hotelName },
    { position: 'end', hotelName },
  ]
}
