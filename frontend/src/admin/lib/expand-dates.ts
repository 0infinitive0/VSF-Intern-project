/**
 * expand-dates.ts — B6 (phase-11-room-prices.md) date-selection helpers.
 * PUT /rooms/{id}/prices takes a discrete list of nights, not a range
 * (`Chỉ T7 & CN` selects non-contiguous dates), so the backend never learns
 * about repeat rules -- these run entirely client-side before the request
 * is sent. All dates are `YYYY-MM-DD` strings throughout: lexicographic
 * comparison on that shape is chronological comparison, so no `Date` object
 * (and its local-timezone parsing footguns) is needed for ordering or the
 * past-date cutoff.
 */

const DAY_MS = 24 * 60 * 60 * 1000

function toUtcMidnight(isoDate: string): number {
  const [y, m, d] = isoDate.split('-').map(Number)
  return Date.UTC(y, m - 1, d)
}

function addDays(isoDate: string, days: number): string {
  return new Date(toUtcMidnight(isoDate) + days * DAY_MS).toISOString().slice(0, 10)
}

function isWeekend(isoDate: string): boolean {
  const day = new Date(toUtcMidnight(isoDate)).getUTCDay()
  return day === 0 || day === 6
}

/** `Chỉ T7 & CN` — keeps only Saturday/Sunday dates from the current selection. */
export function filterWeekendsOnly(dates: string[]): string[] {
  return dates.filter(isWeekend)
}

/**
 * `Lặp lại 4 tuần` — for every selected date, also selects +7/+14/+21 days,
 * dedupes, sorts, and drops anything before `today` (a past night can't be
 * re-selected by dragging, but a repeat could still project one forward
 * into the past relative to `today` if the base date is close to it — this
 * is the one place that's actually checked).
 */
export function repeatFourWeeks(dates: string[], today: string): string[] {
  const result = new Set<string>()
  for (const base of dates) {
    for (const weeks of [0, 1, 2, 3]) {
      const candidate = addDays(base, weeks * 7)
      if (candidate >= today) result.add(candidate)
    }
  }
  return Array.from(result).sort()
}

/** Inclusive date range between `a` and `b` regardless of which is earlier
 * — the shared primitive behind both drag-select (anchor..hover) and
 * keyboard shift-select (anchor..focus). */
export function dateRange(a: string, b: string): string[] {
  const [start, end] = a <= b ? [a, b] : [b, a]
  const dates: string[] = []
  for (let cursor = start; cursor <= end; cursor = addDays(cursor, 1)) {
    dates.push(cursor)
  }
  return dates
}
