/**
 * polyline.ts — Google Encoded Polyline decoder (precision 1e5), the format
 * Mapbox Directions v5 returns by default (`geometries` unset — matches OSRM,
 * see plans/260805-1022-claude-design-ui-integration/phase-12-be-mapbox-routing.md
 * §"Vì sao migration này nhỏ"). Ported verbatim from the already-working
 * Airflow dashboard reference implementation
 * (backend/src/airflow/dashboard/templates/index.html:769-797) rather than
 * reinvented, and rather than adding an @mapbox/polyline dependency (YAGNI —
 * a working ~25-line port already exists to copy).
 *
 * Returns {lat,lng} (this project's convention, see lib/geo.ts), not the
 * source's [lat,lng] tuples — callers pass points through lib/geo.ts's
 * toLngLat() before handing them to Mapbox GL JS.
 */
import type { LatLng } from './geo'

export function decodePolyline(encoded: string): LatLng[] {
  if (!encoded) return []

  const len = encoded.length
  let index = 0
  let lat = 0
  let lng = 0
  const points: LatLng[] = []

  while (index < len) {
    let b: number
    let shift = 0
    let result = 0
    do {
      b = encoded.charCodeAt(index++) - 63
      result |= (b & 0x1f) << shift
      shift += 5
    } while (b >= 0x20)
    const dlat = result & 1 ? ~(result >> 1) : result >> 1
    lat += dlat

    shift = 0
    result = 0
    do {
      b = encoded.charCodeAt(index++) - 63
      result |= (b & 0x1f) << shift
      shift += 5
    } while (b >= 0x20)
    const dlng = result & 1 ? ~(result >> 1) : result >> 1
    lng += dlng

    points.push({ lat: lat / 1e5, lng: lng / 1e5 })
  }

  return points
}
