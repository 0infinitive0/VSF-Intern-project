/**
 * session-date.ts — history-rail row date label. Ported from
 * VP-OTA Planner.dc.html's convoDate() but inverted: the design mock stores a
 * pre-formatted 'Hôm nay' string and translates it to 'Today'; here the
 * source is a real ISO `updated_at`, so the local calendar date is compared
 * first and only then mapped to a label.
 */

function isSameLocalDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate()
}

export function formatSessionDate(iso: string, locale: string, todayLabel: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso

  if (isSameLocalDay(date, new Date())) return todayLabel

  if (locale.startsWith('vi')) {
    return date.toLocaleDateString(locale, { day: '2-digit', month: '2-digit', year: 'numeric' })
  }
  return date.toLocaleDateString(locale, { month: 'short', day: 'numeric', year: 'numeric' })
}
