import { useTranslation } from 'react-i18next'
import ConversationList from './conversation-list'
import LanguageToggle from './language-toggle'
import ThemeToggle from './theme-toggle'
import UserMenu from './user-menu'
import type { Theme } from '../hooks/use-theme'
import type { SessionSummary } from '../types'

/**
 * SidebarRail — logo, new-trip, conversation history, language + theme
 * toggles, collapse/expand. Width animates 76<->248px (--ease-glide, .42s)
 * — a plain width transition is fine here; the risky one to avoid is the
 * focus-mode chat/stage transition in app-shell.tsx, which is transform-only.
 *
 * Below `lg` the rail becomes a fixed overlay (see app-shell.tsx's wrapper)
 * instead of pushing content. `collapsed` is controlled by app-shell.tsx
 * (defaulting to collapsed below `lg`) since the content area needs to know
 * this state too, to reserve a gutter for the persistent collapsed strip.
 */
export default function SidebarRail({
  theme,
  onToggleTheme,
  onNewTrip,
  collapsed,
  onToggleCollapsed,
  sessions,
  activeSessionId,
  onPickSession,
  onDeleteSession,
  turnPending,
  restoringSessionId,
  onOpenAuthPanel,
}: {
  theme: Theme
  onToggleTheme: () => void
  onNewTrip: () => void
  collapsed: boolean
  onToggleCollapsed: () => void
  sessions: SessionSummary[] | null
  activeSessionId: string | null
  onPickSession: (sessionId: string) => void
  onDeleteSession: (sessionId: string) => void
  turnPending: boolean
  restoringSessionId: string | null
  onOpenAuthPanel: () => void
}) {
  const { t } = useTranslation()

  return (
    <>
      {!collapsed && (
        <div
          className="fixed inset-0 z-30 bg-black/30 lg:hidden"
          onClick={onToggleCollapsed}
          aria-hidden="true"
        />
      )}
      <aside
        className="fixed lg:relative inset-y-0 left-0 z-40 lg:z-30 shrink-0 flex flex-col gap-2.5 glass-panel overflow-hidden"
        style={{
          width: collapsed ? '68px' : '252px',
          padding: collapsed ? '14px 13px' : '14px 12px',
          borderRadius: 0,
          // glass-panel's own `border` shorthand (--color-edge, all sides) sorts after
          // plain utilities in the generated stylesheet and wins on equal specificity,
          // silently overriding a `border-r border-line2` className. Inline style always
          // outranks any class, so the design's border-right token is set here instead.
          borderRight: '1px solid var(--line2)',
          transition: 'width .42s var(--ease-glide), padding .42s ease',
        }}
        aria-label={t('sidebarLabel')}
      >
        <div className={`flex items-center gap-2 shrink-0 ${collapsed ? 'flex-col' : 'flex-row'}`}>
          <div
            className="w-[34px] h-[34px] shrink-0 rounded-xl flex items-center justify-center text-on-primary font-bold text-base"
            style={{
              background: 'linear-gradient(145deg,#5C93EE,#2C5FC9)',
              boxShadow: '0 8px 20px -7px rgba(44,95,201,.65)',
            }}
            aria-hidden="true"
          >
            V
          </div>
          {!collapsed && (
            <div className="flex-1 min-w-0 text-[15px] font-semibold tracking-tight truncate">
              {t('navBrand')}
            </div>
          )}
          <button
            type="button"
            onClick={onToggleCollapsed}
            title={t(collapsed ? 'sidebarExpandHint' : 'sidebarCollapseHint')}
            aria-label={t(collapsed ? 'sidebarExpandHint' : 'sidebarCollapseHint')}
            className="w-[30px] h-[30px] shrink-0 rounded-[10px] border border-outline-variant glass-chip text-on-surface-variant flex items-center justify-center hover:text-on-surface transition-colors"
          >
            <span className="material-symbols-outlined text-[16px]" aria-hidden="true">
              {collapsed ? 'keyboard_double_arrow_right' : 'keyboard_double_arrow_left'}
            </span>
          </button>
        </div>

        <button
          type="button"
          onClick={onNewTrip}
          title={t('resetTitle')}
          className="shrink-0 h-10 rounded-[14px] border border-dashed border-outline-variant bg-glass-1 flex items-center justify-center gap-2 text-sm font-medium text-on-surface hover:border-primary hover:text-primary transition-colors"
        >
          <span className="material-symbols-outlined text-[18px]" aria-hidden="true">
            add
          </span>
          {!collapsed && t('newChatBtn')}
        </button>

        {!collapsed && (
          <div className="text-[10px] font-semibold tracking-widest uppercase text-on-surface-faint px-1 shrink-0">
            {t('sidebarHistoryLabel')}
          </div>
        )}

        {/* Must itself be a flex container: a plain block div here would size
            correctly as an aside flex-item but wouldn't propagate that bound
            down to ConversationList's scrollable child, which would then
            render at full content height and spill over the footer below. */}
        <div className="flex-1 min-h-0 flex flex-col">
          <ConversationList
            collapsed={collapsed}
            sessions={sessions}
            activeSessionId={activeSessionId}
            onPickSession={onPickSession}
            onDeleteSession={onDeleteSession}
            turnPending={turnPending}
            restoringSessionId={restoringSessionId}
          />
        </div>

        <LanguageToggle />
        <ThemeToggle theme={theme} onToggle={onToggleTheme} collapsed={collapsed} />

        {/* Account sits below its own hairline, separate from the
            language/theme controls above (design: dc.html:48, the profile
            block is its own bordered-off footer group — same aside-level
            gap above the divider, then this element's own inset below it). */}
        <div className="shrink-0 border-t border-line2">
          <UserMenu collapsed={collapsed} onOpenAuthPanel={onOpenAuthPanel} />
        </div>
      </aside>
    </>
  )
}
