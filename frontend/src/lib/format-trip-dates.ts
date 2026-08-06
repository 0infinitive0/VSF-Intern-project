/**
 * format-trip-dates.ts — locale-aware date formatting.
 *
 * Internationalization spec (phase-06 plan, "Lịch chọn khoảng ngày"):
 *   - vi: `15/08/2026`   - en: `Aug 15, 2026`
 *
 * Both helpers return null (never throw, never a placeholder string) when the
 * date is missing or fails to parse. `locale` is driven by `i18n.language` at
 * the call sites.
 */
function parseDate(value: string | null | undefined): Date | null {
  if (!value) return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date
}

/**
 * Short range, e.g. "12 thg 8 - 18 thg 8" (vi) / "Aug 12 - Aug 18" (en).
 * Kept for the trip-parameters summary — restyled, not replaced.
 */
export function formatTripDateRange(
  start: string | null | undefined,
  end: string | null | undefined,
  locale = 'en-US',
): string | null {
  const startDate = parseDate(start)
  const endDate = parseDate(end)
  if (!startDate || !endDate) return null

  const formatter = new Intl.DateTimeFormat(locale, { month: 'short', day: 'numeric' })
  return `${formatter.format(startDate)} - ${formatter.format(endDate)}`
}

/**
 * Full date for the date-range picker's from/to chips.
 *   vi: `15/08/2026`  en: `Aug 15, 2026`
 */
export function formatFullDate(
  value: string | null | undefined,
  locale = 'en-US',
): string | null {
  const date = parseDate(value)
  if (!date) return null
  return new Intl.DateTimeFormat(locale, {
    day: 'numeric',
    month: locale === 'vi' ? '2-digit' : 'short',
    year: 'numeric',
  }).format(date)
}
