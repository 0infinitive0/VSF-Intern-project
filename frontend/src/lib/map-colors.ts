/**
 * map-colors.ts — single source of truth for the per-day / per-leg palette.
 * Values taken verbatim from trip_planner_components/scripts/constants/config.js
 * (DAY_COLORS, LEG_COLORS). The day colors drive the Overview-tab DayCard dots
 * AND (Phase 10) the map polylines — the fidelity checklist requires both to
 * come from one shared palette so the day card and the route on the map never
 * drift apart (design-fidelity-checklist.md §Phase 9 DayCard).
 */

export const DAY_COLORS = ['#3A73DE', '#2A9187', '#C8802F', '#8E6BC4'] as const

export const LEG_COLORS = ['#3A73DE', '#2A9187', '#C8802F', '#8E6BC4', '#C05E70', '#5E8F49'] as const

/** Color of day `dayNumber` (1-based) — cycles when a trip exceeds 4 days. */
export function dayColor(dayNumber: number): string {
  return DAY_COLORS[(dayNumber - 1) % DAY_COLORS.length]
}

/** Color of the `index`-th leg (0-based) — cycles independently of days. */
export function legColor(index: number): string {
  return LEG_COLORS[index % LEG_COLORS.length]
}

/**
 * Solid accent per itinerary kind — the PlaceDetail hero-badge color map
 * (PlaceDetail.dc.html badge; detailData kindColor, VP-OTA Planner.dc.html:938),
 * keyed by the backend's kind codes (trip_formatter.py:325) exactly like the
 * timeline thumbs. Unknown kinds fall back to the design's attraction blue.
 */
const KIND_ACCENTS: Record<string, string> = {
  attraction: '#3A73DE', // Tham quan
  breakfast: '#C8802F', // Ăn uống
  lunch: '#C8802F',
  dinner: '#C8802F',
  coffee: '#C8802F',
  transport: '#8E6BC4', // Di chuyển
  hotel: '#2A9187', // Khách sạn
}

export function kindAccent(kind?: string | null): string {
  return (kind && KIND_ACCENTS[kind]) || '#3A73DE'
}
