import { formatCurrency } from '../../lib/format-currency'

/** Admin portal is Vietnamese-only (no i18next) -- always the `vi` shape,
 * `1.500.000 ₫`, right-aligned tabular figures wherever it's used in a table. */
export function Money({ value }: { value: number }) {
  return <span className="tabular-nums">{formatCurrency(value, 'vi')}</span>
}
