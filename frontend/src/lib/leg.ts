/**
 * leg.ts — the four-state leg semantics shared by the Phase 9 timeline pill
 * and the overview/day route totals (and reused by Phase 10's map).
 *
 * `route_to_next` on item[i] describes travel from item[i] to item[i+1]
 * (trip_formatter.py:320-323) — EXCEPT on the last item of a day, where the
 * backend instead persists the route back to the hotel (routing.py:250-256,
 * `ITEM_RPC_FIELDS` in itinerary_store.py:59). `legBetween(current, next)`
 * only ever reads it when `next` is a real item in the same day, so it never
 * surfaces that hotel-bound leg (no pill is rendered after the last item
 * either) — `dayRouteMetrics`/`tripRouteMetrics` deliberately total only the
 * inter-item legs actually shown in the timeline, not the return-to-hotel
 * distance. The four states are distinct and must never be merged (phase-09
 * plan §Timeline):
 *
 *   1. real route            → distance + duration + vehicle label (from profile)
 *   2. identical coordinates → {0, 0, "", null} ⇒ "cùng địa điểm" — never
 *                              "0 km · 0 phút"
 *   3. route null            → straight-line haversine fallback, NO vehicle,
 *                              NO duration (a duration cannot be guessed from
 *                              a crow-fly distance)
 *   4. coords missing        → nothing to show — the pill is omitted
 *
 * The overview/day totals reuse legBetween so the "≈ approximate" marker only
 * fires when at least one leg actually used the haversine fallback.
 */
import { parseCoordinates, haversineKm } from './geo'
import type { DayItem, RouteProfile } from '../types'

export type Leg =
  | { kind: 'route'; distanceKm: number; durationMins: number; profile: RouteProfile | null | undefined }
  | { kind: 'same-place' }
  | { kind: 'crow-fly'; distanceKm: number }
  | { kind: 'none' }

export function legBetween(current: DayItem, next: DayItem | null | undefined): Leg {
  if (!next) return { kind: 'none' }

  const r = current.route_to_next
  if (r) {
    // Identical-coordinates marker from routing.py:get_route_to_next —
    // {distance_km: 0, duration_mins: 0, polyline: "", profile: null}. A
    // polyline guard keeps a hypothetical real 0-distance route distinct.
    if ((r.distance_km ?? 0) === 0 && (r.duration_mins ?? 0) === 0 && !r.polyline) {
      return { kind: 'same-place' }
    }
    return {
      kind: 'route',
      distanceKm: r.distance_km ?? 0,
      durationMins: r.duration_mins ?? 0,
      profile: r.profile,
    }
  }

  const a = parseCoordinates(current.coordinates)
  const b = parseCoordinates(next.coordinates)
  if (!a || !b) return { kind: 'none' }
  return { kind: 'crow-fly', distanceKm: haversineKm(a, b) }
}

export interface RouteMetrics {
  distanceKm: number
  durationMins: number
  approximate: boolean
}

/** Sum of the day's legs (item → next item). approximate → a fallback leg was used. */
export function dayRouteMetrics(items: DayItem[]): RouteMetrics {
  let distanceKm = 0
  let durationMins = 0
  let approximate = false
  for (let i = 0; i < items.length - 1; i++) {
    const leg = legBetween(items[i], items[i + 1])
    if (leg.kind === 'route') {
      distanceKm += leg.distanceKm
      durationMins += leg.durationMins
    } else if (leg.kind === 'crow-fly') {
      distanceKm += leg.distanceKm
      approximate = true
    }
  }
  return { distanceKm, durationMins, approximate }
}

/** Trip-wide totals — sum of every day's legs. */
export function tripRouteMetrics(days: { items: DayItem[] }[]): RouteMetrics {
  const total: RouteMetrics = { distanceKm: 0, durationMins: 0, approximate: false }
  for (const day of days) {
    const m = dayRouteMetrics(day.items)
    total.distanceKm += m.distanceKm
    total.durationMins += m.durationMins
    total.approximate = total.approximate || m.approximate
  }
  return total
}
