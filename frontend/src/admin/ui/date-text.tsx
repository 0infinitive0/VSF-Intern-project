const FORMATTER = new Intl.DateTimeFormat('vi-VN', { day: '2-digit', month: '2-digit', year: 'numeric' })
const FORMATTER_WITH_TIME = new Intl.DateTimeFormat('vi-VN', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
})

/** `24/08/2026` (plan's mandated date shape, no i18next in this bundle). */
export function DateText({ value, withTime = false }: { value: string | Date; withTime?: boolean }) {
  const date = typeof value === 'string' ? new Date(value) : value
  if (Number.isNaN(date.getTime())) return <span>—</span>
  return <span className="tabular-nums">{(withTime ? FORMATTER_WITH_TIME : FORMATTER).format(date)}</span>
}
