/**
 * route-segments.ts — builds the ordered per-day list of map route segments
 * (hotel -> item[0] -> item[1] -> ... -> item[n-1] -> hotel), each backed by
 * a real decoded Mapbox polyline when available or a straight-line fallback
 * otherwise. Ported from the segment-construction algorithm in the
 * already-working Airflow dashboard reference
 * (backend/src/airflow/dashboard/templates/index.html:862-930) — the
 * ordering/fallback-priority logic is reused deliberately, not reinvented;
 * only the Leaflet-specific draw calls are left behind (Phase 10 renders
 * these via a Mapbox GL JS GeoJSON source + line-layers instead, in
 * map-view.tsx).
 *
 * Pure function, no map library, no DOM — testable with plain Vitest against
 * the real fixture data in frontend/mock/server.js.
 *
 * Rules, ported deliberately:
 *  - The hotel-anchored segment (hotel -> item[0]) only exists when the
 *    hotel's coordinates parse. No hotel coordinates -> no anchor point, no
 *    fake one substituted.
 *  - A segment between two items only exists when BOTH items' coordinates
 *    parse. A missing-coordinate item creates a genuine gap on both its
 *    sides — it is never bridged to its nearest valid neighbor. Bridging
 *    would silently invent adjacency between two points that weren't
 *    actually adjacent in the itinerary, which is exactly the kind of
 *    "graphics that lie" this project forbids for the curve()-bent fallback
 *    case (plan.md §"Cảnh báo: curve() là đồ hoạ nói dối") — the same
 *    principle applies here.
 *  - classifyRoute(route) === 'same-place' emits no segment at all — there's
 *    nothing meaningful to draw for a zero-distance hop.
 *  - Otherwise: decodePolyline(route.polyline) if present and it decodes to
 *    >=2 points -> a real route, isFallback=false; else a straight 2-point
 *    line -> isFallback=true. The fallback is ALWAYS a literal straight
 *    LineString — never bent into a curve (see the warning above).
 *  - A day with fewer than 2 parseable points naturally produces zero
 *    segments (every segment needs 2 valid endpoints), no separate gate
 *    needed.
 */
import { parseCoordinates, type LatLng } from './geo'
import { classifyRoute } from './leg'
import { decodePolyline } from './polyline'
import { itemSyncId, TRIP_HOTEL_SYNC_KEY } from './map-sync-id'
import type { Day, RouteInfo, RouteProfile } from '../types'

export interface RouteSegment {
  /** "d{dayNumber}-s{legIndex}" — also the GeoJSON Feature.id (required for setFeatureState). */
  segKey: string
  dayNumber: number
  /** 0 = hotel->item[0], 1..n-1 = item[i-1]->item[i], n = item[n-1]->hotel (n = items.length). */
  legIndex: number
  fromKey: string
  toKey: string
  /** >=2 points: a decoded real polyline, or a straight 2-point fallback. */
  points: LatLng[]
  isFallback: boolean
  profile: RouteProfile | null
}

type HotelLike = { coordinates?: string | null } | null | undefined

function pointsFor(route: RouteInfo | null | undefined, from: LatLng, to: LatLng): { points: LatLng[]; isFallback: boolean } {
  if (route?.polyline) {
    const decoded = decodePolyline(route.polyline)
    if (decoded.length >= 2) return { points: decoded, isFallback: false }
  }
  return { points: [from, to], isFallback: true }
}

export function buildDaySegments(day: Day, hotel: HotelLike): RouteSegment[] {
  const segments: RouteSegment[] = []
  const items = day.items
  const hotelPoint = parseCoordinates(hotel?.coordinates)
  const itemPoints = items.map((item) => parseCoordinates(item.coordinates))

  // Segment 0: hotel -> item[0]
  if (hotelPoint && items.length > 0 && itemPoints[0]) {
    const route = items[0].route_from_hotel
    if (classifyRoute(route) !== 'same-place') {
      const { points, isFallback } = pointsFor(route, hotelPoint, itemPoints[0])
      segments.push({
        segKey: `d${day.day_number}-s0`,
        dayNumber: day.day_number,
        legIndex: 0,
        fromKey: TRIP_HOTEL_SYNC_KEY,
        toKey: itemSyncId(day.day_number, items[0], 0),
        points,
        isFallback,
        profile: route?.profile ?? null,
      })
    }
  }

  // Segments between items: item[i] -> item[i+1]
  for (let i = 0; i < items.length - 1; i++) {
    const fromPoint = itemPoints[i]
    const toPoint = itemPoints[i + 1]
    if (!fromPoint || !toPoint) continue // genuine gap — never bridged across a missing point

    const route = items[i].route_to_next
    if (classifyRoute(route) === 'same-place') continue

    const { points, isFallback } = pointsFor(route, fromPoint, toPoint)
    segments.push({
      segKey: `d${day.day_number}-s${i + 1}`,
      dayNumber: day.day_number,
      legIndex: i + 1,
      fromKey: itemSyncId(day.day_number, items[i], i),
      toKey: itemSyncId(day.day_number, items[i + 1], i + 1),
      points,
      isFallback,
      profile: route?.profile ?? null,
    })
  }

  // Return segment: item[last] -> hotel
  if (hotelPoint && items.length > 0) {
    const lastIndex = items.length - 1
    const lastPoint = itemPoints[lastIndex]
    if (lastPoint) {
      const route = items[lastIndex].route_to_next
      if (classifyRoute(route) !== 'same-place') {
        const { points, isFallback } = pointsFor(route, lastPoint, hotelPoint)
        segments.push({
          segKey: `d${day.day_number}-s${items.length}`,
          dayNumber: day.day_number,
          legIndex: items.length,
          fromKey: itemSyncId(day.day_number, items[lastIndex], lastIndex),
          toKey: TRIP_HOTEL_SYNC_KEY,
          points,
          isFallback,
          profile: route?.profile ?? null,
        })
      }
    }
  }

  return segments
}

/** Flat-map of buildDaySegments across every day — used by the workspace "Tổng quan" tab. */
export function buildTripSegments(days: Day[], hotel: HotelLike): RouteSegment[] {
  return days.flatMap((day) => buildDaySegments(day, hotel))
}
