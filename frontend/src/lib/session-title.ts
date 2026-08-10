/**
 * session-title.ts — composes the history-rail row title from a SessionSummary.
 * Pure: no React, no i18next instance. Labels come in as parameters so VI/EN
 * switch without a reload (App owns the t() call).
 */
import type { SessionSummary } from '../types'

export interface SessionTitleLabels {
  nightsSuffix: string
  daysSuffix: string
}

export function composeSessionTitle(
  summary: Pick<SessionSummary, 'title' | 'destination' | 'duration_days'>,
  labels: SessionTitleLabels,
): string | null {
  const { destination, duration_days, title } = summary

  if (destination && duration_days != null && duration_days >= 1) {
    const nights = Math.max(duration_days - 1, 1)
    return `${destination} ${duration_days}${labels.daysSuffix}${nights}${labels.nightsSuffix}`
  }
  if (destination) return destination
  if (title) return title
  return null
}
