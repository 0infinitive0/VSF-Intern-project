/**
 * session-status-badge.ts — maps a session's status to the sidebar pill's
 * label key + color classes. Pure: no React, no i18next instance (mirrors
 * session-title.ts's pattern) — the caller does its own `t(labelKey)`.
 *
 * "holding"/"paid" are derived server-side, fresh per list request, from
 * real bookings tied to this session_id (backend/src/services/
 * session_store.py's booking_states_for_sessions) — not client-side guesses
 * (plan 260818-vnpay-payment-and-email-confirmation's addendum 2).
 */
import type { SessionSummary } from '../types'

export interface SessionStatusBadge {
  labelKey: string
  bgClass: string
  inkClass: string
}

const BADGE_BY_STATUS: Record<SessionSummary['status'], SessionStatusBadge> = {
  paid: { labelKey: 'sidebarStatusPaid', bgClass: 'bg-paid-soft', inkClass: 'text-paid-ink' },
  holding: { labelKey: 'sidebarStatusHolding', bgClass: 'bg-holding-soft', inkClass: 'text-holding-ink' },
  completed: { labelKey: 'sidebarStatusCompleted', bgClass: 'bg-success-soft', inkClass: 'text-success-ink' },
  draft: { labelKey: 'sidebarStatusDraft', bgClass: 'bg-warning-soft', inkClass: 'text-warning-ink' },
}

export function sessionStatusBadge(status: SessionSummary['status']): SessionStatusBadge {
  return BADGE_BY_STATUS[status]
}
