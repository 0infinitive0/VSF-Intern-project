/**
 * format-compact-vnd.ts — short VND amounts for chart axes and bar labels,
 * where the full `1.500.000 ₫` from `formatCurrency` doesn't fit. Vietnamese
 * magnitude suffixes: N (nghìn), tr (triệu), tỷ. Not locale-aware on purpose
 * — the admin portal is Vietnamese-only.
 */
export function formatCompactVnd(value: number): string {
  if (!Number.isFinite(value)) return ''
  const abs = Math.abs(value)
  const round1 = (n: number) => n.toLocaleString('vi-VN', { maximumFractionDigits: 1 })
  if (abs >= 1_000_000_000) return `${round1(value / 1_000_000_000)} tỷ`
  if (abs >= 1_000_000) return `${round1(value / 1_000_000)} tr`
  if (abs >= 1_000) return `${Math.round(value / 1_000).toLocaleString('vi-VN')} N`
  return Math.round(value).toLocaleString('vi-VN')
}
