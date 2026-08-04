/**
 * format-stars.ts — renders a hotel's star rating as a repeated '★' glyph.
 * A rendering utility with no language/content dependency, so it does not
 * belong in the locale JSON (see strings.ts → i18n migration).
 */
export function formatHotelStars(n: number): string {
  return '★'.repeat(n)
}