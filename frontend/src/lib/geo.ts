/**
 * geo.ts — coordinate parsing + great-circle distance. Shared by the timeline
 * fallback legs (Phase 9) and the map routes (Phase 10). Pure functions, no
 * DOM, no map library — ported from trip_planner_components/scripts/utils/geo.js
 * (`kmFrom`), which the plan explicitly says to take WITHOUT `curve()`.
 */

export interface LatLng {
  lat: number
  lng: number
}

/**
 * Parse a coordinate string into {lat,lng}, or null when it can't be parsed.
 *
 * Backend emission is verified as "lat,lng" (trip_formatter.py:328-331 — item
 * coordinates are joined with a comma; hotel/option coordinates are stored as
 * "lat,lng" in the DB, see types.ts on HotelOption.coordinates). WKT
 * ("POINT(lng lat)") is handled defensively because an older types.ts comment
 * flagged the DB column as possibly-WKT — both parsers in the backend only
 * split on ",", so accepting both keeps the frontend resilient to either
 * without guessing. Anything else returns null (never throws).
 */
export function parseCoordinates(value: string | null | undefined): LatLng | null {
  if (!value) return null

  const trimmed = value.trim()
  if (!trimmed) return null

  const comma = trimmed.split(',')
  if (comma.length === 2) {
    const lat = Number(comma[0].trim())
    const lng = Number(comma[1].trim())
    if (Number.isFinite(lat) && Number.isFinite(lng)) return { lat, lng }
    return null
  }

  const wkt = trimmed.match(/^\s*POINT\s*\(\s*([\d.+-]+)\s+([\d.+-]+)\s*\)\s*$/i)
  if (wkt) {
    const lng = Number(wkt[1])
    const lat = Number(wkt[2])
    if (Number.isFinite(lat) && Number.isFinite(lng)) return { lat, lng }
  }

  return null
}

/** Great-circle distance in km between two points (haversine). */
export function haversineKm(a: LatLng, b: LatLng): number {
  const R = 6371
  const dLat = ((b.lat - a.lat) * Math.PI) / 180
  const dLng = ((b.lng - a.lng) * Math.PI) / 180
  const la1 = (a.lat * Math.PI) / 180
  const la2 = (b.lat * Math.PI) / 180
  const x = Math.sin(dLat / 2) ** 2 + Math.cos(la1) * Math.cos(la2) * Math.sin(dLng / 2) ** 2
  return R * 2 * Math.atan2(Math.sqrt(x), Math.sqrt(1 - x))
}

/**
 * {lat,lng} -> Mapbox GL JS's [lng,lat] tuple order (Phase 10). This is the
 * OPPOSITE of this file's own {lat,lng} convention and of Leaflet's
 * [lat,lng] — get it backwards and every marker silently lands in the wrong
 * hemisphere with no error. Always go through this helper at the boundary
 * where a point is handed to mapboxgl, never inline `[p.lng, p.lat]`.
 */
export function toLngLat(point: LatLng): [number, number] {
  return [point.lng, point.lat]
}

/**
 * Bounding box of a set of points, or null when the list is empty. A single
 * point returns a degenerate box (sw === ne) — callers doing camera fitting
 * must special-case that (flyTo a center instead of fitBounds).
 */
export function boundsOf(points: LatLng[]): { sw: LatLng; ne: LatLng } | null {
  if (points.length === 0) return null
  let minLat = points[0].lat
  let maxLat = points[0].lat
  let minLng = points[0].lng
  let maxLng = points[0].lng
  for (const p of points) {
    if (p.lat < minLat) minLat = p.lat
    if (p.lat > maxLat) maxLat = p.lat
    if (p.lng < minLng) minLng = p.lng
    if (p.lng > maxLng) maxLng = p.lng
  }
  return { sw: { lat: minLat, lng: minLng }, ne: { lat: maxLat, lng: maxLng } }
}
