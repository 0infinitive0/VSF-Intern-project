import type { Suggestion } from '../types'

/**
 * Real destinations backed by live data today — verified against Supabase's
 * `destinations` table via `_get_destination_names()` (backend/src/services/trip_planner.py),
 * the same source `intake.available_destinations` draws from. Kept as a static
 * snapshot here (not fetched) because it only changes when a new region's data
 * pipeline run lands, not per-request.
 */
export const QUICK_START_DESTINATIONS: Suggestion[] = [
  { label: 'Hà Nội', value: 'Hà Nội' },
  { label: 'Đà Nẵng', value: 'Đà Nẵng' },
  { label: 'Huế', value: 'Huế' },
  { label: 'Nha Trang', value: 'Nha Trang' },
  { label: 'Hồ Chí Minh', value: 'Hồ Chí Minh' },
]
