/**
 * format-currency.ts — locale-aware VND amount formatting.
 *
 * Internationalization spec (phase-06 plan, step 2):
 *   - vi: `1.500.000 ₫`
 *   - en: `VND 1,500,000`
 *
 * The spec's two shapes differ in more than the number separator — the currency
 * symbol goes *after* the number in vi ("₫") and *before* in en ("VND …"), so a
 * single `Intl.NumberFormat(locale, {style:'currency', currency:'VND'})` is not
 * enough (it renders both with the ₫ affix position). The locale drives which
 * branch is used; callers pass `i18n.language`.
 */
export function formatCurrency(value: number, locale: string): string {
  if (!Number.isFinite(value)) return ''
  const rounded = Math.round(value)
  const number = new Intl.NumberFormat(locale === 'vi' ? 'vi-VN' : 'en-US', {
    maximumFractionDigits: 0,
  }).format(rounded)
  return locale === 'vi' ? `${number} ₫` : `VND ${number}`
}
