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

/**
 * Day-number + short-month tile, e.g. "18" / "THG 8" (vi) or "18" / "AUG"
 * (en) — the compact "date-strip" pattern used by both booking-modal.tsx's
 * done screen and booking-receipt-modal.tsx (a past booking's own read-only
 * view of the same data), so the two "here's your booking" screens render
 * dates identically instead of drifting apart. Returns null when the date
 * is missing/unparseable rather than a fabricated placeholder.
 */
export function formatDateTile(
  value: string | null | undefined,
  locale = 'en-US',
): { day: string; month: string } | null {
  const date = parseDate(value)
  if (!date) return null
  const intlLocale = locale === 'vi' ? 'vi-VN' : 'en-US'
  const day = new Intl.DateTimeFormat(intlLocale, { day: 'numeric' }).format(date)
  const month = new Intl.DateTimeFormat(intlLocale, { month: 'short' }).format(date).toUpperCase()
  return { day, month }
}

/** Whole nights between two ISO dates, clamped to a minimum of 1 (same
 * "never show 0 nights" floor booking-modal.tsx's checkout flow always
 * used) — shared so the date-strip's "N đêm" label matches between the
 * live checkout flow and the read-only past-booking receipt. */
export function nightsBetween(checkIn: string | null | undefined, checkOut: string | null | undefined): number {
  const start = parseDate(checkIn)
  const end = parseDate(checkOut)
  if (!start || !end) return 1
  const nights = Math.round((end.getTime() - start.getTime()) / 86_400_000)
  return nights > 0 ? nights : 1
}
