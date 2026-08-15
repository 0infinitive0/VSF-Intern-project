/**
 * item-duration.ts — timeline item time-window formatting.
 *
 * The backend's `start_time`/`end_time` are always "HH:MM:SS" —
 * `_minutes_to_time` (backend/src/services/trip_scheduler.py) unconditionally
 * appends ":00" seconds, which nothing downstream ever populates with a real
 * value. `stripSeconds` drops that dead trailing field for display.
 *
 * `minutesBetween` + `formatItemDuration` replace a literal "07:00 – 08:00"
 * range in the timeline meta line with a human duration ("1 tiếng" /
 * "1 hour"), per the design's `it.meta`.
 */

/** "07:00:00" -> "07:00". Passes anything that doesn't match through unchanged rather than guessing. */
export function stripSeconds(value: string): string {
  const match = /^(\d{1,2}:\d{2})(?::\d{2})?$/.exec(value)
  return match ? match[1] : value
}

function parseTimeToMinutes(value: string | null | undefined): number | null {
  if (!value) return null
  const match = /^(\d{1,2}):(\d{2})/.exec(value)
  if (!match) return null
  return Number(match[1]) * 60 + Number(match[2])
}

/** Whole minutes from start to end, or null when either is missing/unparseable or end isn't after start (never a guessed/negative duration). */
export function minutesBetween(start: string | null | undefined, end: string | null | undefined): number | null {
  const startMin = parseTimeToMinutes(start)
  const endMin = parseTimeToMinutes(end)
  if (startMin == null || endMin == null || endMin <= startMin) return null
  return endMin - startMin
}

/** "{{n}} tiếng {{n}} phút" style duration, e.g. 60 -> "1 tiếng" / "1 hour", 90 -> "1 tiếng 30 phút" / "1 hour 30 mins". Empty string when there's nothing to show. */
export function formatItemDuration(
  totalMinutes: number,
  t: (key: string, options?: Record<string, unknown>) => string,
): string {
  const minutes = Math.round(totalMinutes)
  if (minutes <= 0) return ''
  const hours = Math.floor(minutes / 60)
  const mins = minutes % 60
  const parts = [
    hours > 0 ? t(hours === 1 ? 'durationHoursOne' : 'durationHoursOther', { count: hours }) : '',
    mins > 0 ? t(mins === 1 ? 'durationMinutesOne' : 'durationMinutesOther', { count: mins }) : '',
  ].filter(Boolean)
  return parts.join(' ')
}
