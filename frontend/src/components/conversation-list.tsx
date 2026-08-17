import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import ConfirmDialog from './confirm-dialog'
import { formatSessionDate } from '../lib/session-date'
import { composeSessionTitle } from '../lib/session-title'
import type { SessionSummary } from '../types'

// 115° diagonal stripe, matching convoRows' thumb token exactly
// (V-OTA Planner.dc.html:1523). Real thumbnail_url always wins over this.
function thumbGradient(active: boolean): string {
  const stripe = active ? 'rgba(58,115,222,.28)' : 'var(--t4)'
  return `repeating-linear-gradient(115deg,${stripe} 0 7px,transparent 7px 14px)`
}

/**
 * ConversationList — history rail. Pure/controlled: App.tsx owns fetching
 * (useSessionHistory) and which session is active (ChatState.sessionId);
 * this component only renders and forwards clicks. Renders three states:
 *   - loading (`sessions === null`): skeleton rows
 *   - empty or 404 (endpoint not shipped yet): renders nothing, no header,
 *     no error — treated identically per the Phase 4 contract
 *   - data: real rows with title/date/status pill/thumbnail, clickable to
 *     restore, delete on hover/focus.
 */
export default function ConversationList({
  collapsed,
  sessions,
  activeSessionId,
  onPickSession,
  onDeleteSession,
  turnPending,
}: {
  collapsed: boolean
  sessions: SessionSummary[] | null
  activeSessionId: string | null
  onPickSession: (sessionId: string) => void
  onDeleteSession: (sessionId: string) => void
  turnPending: boolean
}) {
  const { t, i18n } = useTranslation()
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null)

  if (sessions === null) {
    return (
      <div className="flex flex-col gap-1.5" aria-hidden="true">
        {[0, 1, 2].map((i) => (
          <div
            key={i}
            className="h-11 rounded-2xl bg-surface-container animate-pulse"
            style={{ animationDelay: `${i * 120}ms` }}
          />
        ))}
      </div>
    )
  }

  if (sessions.length === 0) return null

  const pendingDeleteSession = sessions.find((s) => s.session_id === pendingDeleteId) ?? null
  const pendingDeleteTitle = pendingDeleteSession
    ? (composeSessionTitle(pendingDeleteSession, {
        daysSuffix: t('sidebarDaysShort'),
        nightsSuffix: t('sidebarNightsShort'),
      }) ?? t('newChatBtn'))
    : ''

  return (
    <>
      <div
        className="flex flex-col gap-1 overflow-y-auto overflow-x-hidden overscroll-contain custom-scrollbar min-h-0"
        style={{
          marginRight: collapsed ? '-13px' : '-12px',
          paddingRight: collapsed ? '13px' : '12px',
        }}
        role="list"
        aria-label={t('sidebarHistoryLabel')}
      >
      {sessions.map((session, i) => {
        const active = session.session_id === activeSessionId
        const title =
          composeSessionTitle(session, { daysSuffix: t('sidebarDaysShort'), nightsSuffix: t('sidebarNightsShort') }) ??
          t('newChatBtn')
        return (
          <div
            key={session.session_id}
            role="listitem"
            className="relative group animate-[vFade_0.5s_ease_both]"
            style={{ animationDelay: `${Math.min(i, 8) * 55}ms` }}
          >
            <button
              type="button"
              title={title}
              onClick={() => onPickSession(session.session_id)}
              aria-current={active ? 'true' : undefined}
              aria-disabled={turnPending || undefined}
              className={`w-full flex items-center gap-2.5 rounded-[14px] hover:bg-glass-2 transition-colors text-left ${
                turnPending ? 'opacity-60 cursor-not-allowed' : 'cursor-pointer'
              }`}
              style={{
                padding: collapsed ? '4px' : '9px',
                border: `1px solid ${active ? 'var(--edge)' : 'transparent'}`,
                // `undefined` omits the inline declaration for an inactive row —
                // an explicit 'transparent' here would out-rank `hover:bg-glass-2`
                // (inline style always beats a class at equal specificity, same
                // trap sidebar-rail.tsx's borderRight comment documents), killing
                // the hover background on every row, active or not.
                background: active ? 'var(--g3)' : undefined,
                boxShadow: active ? '0 10px 24px -18px rgba(var(--sh),.7)' : 'none',
              }}
            >
              {session.thumbnail_url ? (
                <img src={session.thumbnail_url} alt="" className="w-8 h-8 rounded-[11px] object-cover shrink-0" />
              ) : (
                <div
                  className="w-8 h-8 rounded-[11px] shrink-0"
                  style={{ background: thumbGradient(active) }}
                  aria-hidden="true"
                />
              )}
              {!collapsed && (
                <div className="flex-1 min-w-0">
                  <div className="text-[12.5px] font-[590] tracking-[-.1px] text-on-surface truncate pr-4">
                    {title}
                  </div>
                  <div className="flex items-center gap-1.5 mt-0.5">
                    <span className="text-[10px] text-on-surface-muted whitespace-nowrap">
                      {session.updated_at
                        ? formatSessionDate(session.updated_at, i18n.language, t('sidebarToday'))
                        : ''}
                    </span>
                    <span
                      className={`text-[9px] px-1.5 py-px rounded-full font-medium whitespace-nowrap ${
                        session.status === 'completed'
                          ? 'bg-success-soft text-success-ink'
                          : 'bg-warning-soft text-warning-ink'
                      }`}
                    >
                      {t(session.status === 'completed' ? 'sidebarStatusCompleted' : 'sidebarStatusDraft')}
                    </span>
                  </div>
                </div>
              )}
            </button>
            {/* Sibling of the button above, not nested in it — HTML forbids a
                button inside a button (HistoryRow.dc.html keeps them as
                siblings for the same reason). stopPropagation is a no-op with
                this DOM structure but matches the design's own onDelete. */}
            {!collapsed && (
              <button
                type="button"
                title={t('sidebarDeleteSessionHint')}
                aria-label={t('sidebarDeleteSessionHint')}
                onClick={(e) => {
                  e.stopPropagation()
                  setPendingDeleteId(session.session_id)
                }}
                className="absolute top-1/2 -translate-y-1/2 right-2 w-6 h-6 rounded-lg border border-border-subtle bg-surface-background text-on-surface-variant items-center justify-center opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 focus:opacity-100 hover:bg-error hover:text-on-error hover:border-error transition-colors flex"
              >
                <span className="material-symbols-outlined text-[14px] cursor-pointer" aria-hidden="true">
                  close
                </span>
              </button>
            )}
          </div>
        )
      })}
      </div>
      <ConfirmDialog
        open={pendingDeleteId !== null}
        title={t('sidebarDeleteSessionConfirmTitle')}
        message={t('sidebarDeleteSessionConfirmMessage', { title: pendingDeleteTitle })}
        confirmLabel={t('sidebarDeleteSessionConfirmAction')}
        cancelLabel={t('sidebarDeleteSessionCancel')}
        destructive
        onConfirm={() => {
          if (pendingDeleteId) onDeleteSession(pendingDeleteId)
          setPendingDeleteId(null)
        }}
        onCancel={() => setPendingDeleteId(null)}
      />
    </>
  )
}
