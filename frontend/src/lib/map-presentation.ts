import { formatCurrency } from './format-currency'
import { parseCoordinates, type LatLng } from './geo'
import type { RouteSegment } from './route-segments'
import type { HotelDetail, HotelOption } from '../types'

export interface HotelMapFields {
  priceLabel?: string
  matchLabel?: string
}

export interface HotelMapRay {
  name: string
  coordinates: LatLng
  distanceKm: number
}

/** Presentation-only fields for the hotel map marker; never invents a price or score. */
export function hotelMapFields(hotel: HotelOption, language: string): HotelMapFields {
  const price = hotel.average_nightly_price != null && hotel.average_nightly_price > 0
    ? formatCurrency(hotel.average_nightly_price, language)
    : undefined
  const match = hotel.match_score != null && Number.isFinite(hotel.match_score)
    ? `${Math.round(hotel.match_score * 100)}%`
    : undefined
  return { priceLabel: price, matchLabel: match }
}

/** Keeps the distance-ray layer honest: each ray needs a real name, coordinate, and non-negative distance. */
export function hotelMapRays(detail: HotelDetail | null | undefined): HotelMapRay[] {
  return (detail?.nearby_attractions ?? []).flatMap((place) => {
    const coordinates = parseCoordinates(place?.coordinates)
    if (!place?.name || !coordinates || place.distance_km == null || !Number.isFinite(place.distance_km) || place.distance_km < 0) {
      return []
    }
    return [{ name: place.name, coordinates, distanceKm: place.distance_km }]
  })
}

/** Legend hover wins over item/marker hover because it names one exact leg. */
export function highlightedRouteKeys(segments: RouteSegment[], hoveredId: string | null, hoveredSegmentKey: string | null): Set<string> {
  if (hoveredSegmentKey) return new Set([hoveredSegmentKey])
  return new Set(segments.filter((segment) => segment.fromKey === hoveredId || segment.toKey === hoveredId).map((segment) => segment.segKey))
}
