/**
 * formatTripDateRange — formats a start/end ISO datetime pair into a short
 * "Oct 12 - Oct 18" style range. Returns null (never throws, never a
 * placeholder string) when either date is missing or fails to parse.
 */
export function formatTripDateRange(
  start: string | null | undefined,
  end: string | null | undefined,
): string | null {
  if (!start || !end) return null

  const startDate = new Date(start)
  const endDate = new Date(end)
  if (Number.isNaN(startDate.getTime()) || Number.isNaN(endDate.getTime())) return null

  const formatter = new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric' })
  return `${formatter.format(startDate)} - ${formatter.format(endDate)}`
}
