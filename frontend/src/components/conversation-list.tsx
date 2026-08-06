import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { deleteSession, listSessions } from '../api/session-client'
import type { SessionSummary } from '../types'

function formatSessionDate(iso: string, locale: string): string {
  try {
    return new Date(iso).toLocaleDateString(locale, { day: '2-digit', month: '2-digit', year: 'numeric' })
  } catch {
    return iso
  }
}

/**
 * ConversationList — history rail. Renders three states:
 *   - loading: skeleton rows
 *   - empty or 404 (endpoint not shipped yet): renders nothing, no header,
 *     no error — treated identically per the Phase 4 contract
 *   - data: real rows with title/date/status pill/thumbnail, delete on
 *     hover/focus. Rows aren't clickable yet: opening a past session means
 *     hydrating use-chat-session.ts's state, which is explicitly out of
 *     scope for this phase (that hook is reused as-is) — a future phase
 *     wires session-client.ts's restoreSession() to a click handler here.
 *     Until then the row is a plain non-interactive display, not a button
 *     that does nothing.
 */
export default function ConversationList({ collapsed }: { collapsed: boolean }) {
  const { t, i18n } = useTranslation()
  const [sessions, setSessions] = useState<SessionSummary[] | null>(null)

  useEffect(() => {
    let cancelled = false
    listSessions().then((list) => {
      if (!cancelled) setSessions(list)
    })
    return () => {
      cancelled = true
    }
  }, [])

  async function handleDelete(sessionId: string) {
    setSessions((prev) => (prev ? prev.filter((s) => s.session_id !== sessionId) : prev))
    await deleteSession(sessionId)
  }

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

  return (
    <div
      className="flex flex-col gap-1 overflow-y-auto overflow-x-hidden custom-scrollbar min-h-0"
      role="list"
      aria-label={t('sidebarHistoryLabel')}
    >
      {sessions.map((session, i) => {
        const title = session.title || session.destination || t('sidebarUntitledSession')
        return (
          <div
            key={session.session_id}
            role="listitem"
            className="relative group animate-[vFade_0.5s_ease_both]"
            style={{ animationDelay: `${Math.min(i, 8) * 60}ms` }}
            title={title}
          >
            <div className="w-full flex items-center gap-2.5 rounded-[14px] p-2 hover:bg-glass-2 transition-colors">
              {session.thumbnail_url ? (
                <img src={session.thumbnail_url} alt="" className="w-8 h-8 rounded-[11px] object-cover shrink-0" />
              ) : (
                <div className="w-8 h-8 rounded-[11px] bg-surface-container shrink-0" aria-hidden="true" />
              )}
              {!collapsed && (
                <div className="flex-1 min-w-0">
                  <div className="text-[12.5px] font-[590] text-on-surface truncate pr-4">{title}</div>
                  <div className="flex items-center gap-1.5 mt-0.5">
                    <span className="text-[10px] text-on-surface-muted whitespace-nowrap">
                      {formatSessionDate(session.updated_at, i18n.language)}
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
            </div>
            {!collapsed && (
              <button
                type="button"
                title={t('sidebarDeleteSessionHint')}
                aria-label={t('sidebarDeleteSessionHint')}
                onClick={() => handleDelete(session.session_id)}
                className="absolute top-2 right-2 w-6 h-6 rounded-lg border border-border-subtle bg-surface-background text-on-surface-variant items-center justify-center opacity-0 group-hover:opacity-100 focus:opacity-100 hover:bg-error hover:text-on-error hover:border-error transition-colors flex"
              >
                <span className="material-symbols-outlined text-[14px]" aria-hidden="true">
                  close
                </span>
              </button>
            )}
          </div>
        )
      })}
    </div>
  )
}
