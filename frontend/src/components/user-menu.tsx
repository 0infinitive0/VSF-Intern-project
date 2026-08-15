import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../auth/auth-context'
import { getDisplayName } from '../auth/profile-display'
import ProfilePasswordModal from '../auth/profile-password-modal'
import UserAvatar from '../auth/user-avatar'

/**
 * UserMenu — SidebarRail's footer account slot (design: "User Account UI" /
 * "User Menu", Design Update - Authentication Ex.md §9-10). This app has no
 * separate page header — the sidebar rail is where every other global
 * control (theme, language) already lives, so the account slot joins them
 * there instead of a header this shell doesn't have.
 *
 * Self-contained: reads auth state via useAuth() directly rather than
 * threading user/isAnonymous down from App.tsx, since SidebarRail's prop
 * list is already long. Only `onOpenAuthPanel` (owned by App.tsx's
 * authPanelOpen state) and `collapsed` (owned by AppShell's layout state)
 * are still passed in — both are state this component doesn't own. The
 * profile modal's own open/close state stays local here for the same
 * reason, rendered through a portal to document.body (see
 * profile-password-modal.tsx's doc comment for why: this rail is a
 * `glass-panel`, and `backdrop-filter` makes it a containing block for
 * `position: fixed` descendants, which would clip a non-portaled dialog to
 * the rail's own width instead of the viewport).
 */
export default function UserMenu({
  collapsed,
  onOpenAuthPanel,
}: {
  collapsed: boolean
  onOpenAuthPanel: () => void
}) {
  const { t } = useTranslation()
  const { user, isAnonymous, signOut } = useAuth()
  const [open, setOpen] = useState(false)
  const [profileModalOpen, setProfileModalOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    function onPointerDown(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false)
    }
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false)
    }
    window.addEventListener('mousedown', onPointerDown)
    window.addEventListener('keydown', onKeyDown)
    return () => {
      window.removeEventListener('mousedown', onPointerDown)
      window.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  if (isAnonymous || !user) {
    return (
      <button
        type="button"
        onClick={onOpenAuthPanel}
        title={t('authSignIn')}
        className="shrink-0 w-full h-9 rounded-xl border border-outline-variant bg-glass-1 flex items-center justify-center gap-2 text-[11.5px] font-medium text-on-surface-variant hover:text-on-surface transition-colors animate-[vFade_0.28s_ease_both]"
      >
        <span className="material-symbols-outlined text-[16px]" aria-hidden="true">
          login
        </span>
        {!collapsed && t('authSignIn')}
      </button>
    )
  }

  const displayName = getDisplayName(user, t)

  return (
    <div ref={rootRef} className="shrink-0 flex flex-col gap-1.5 animate-[vFade_0.28s_ease_both]">
      {open && (
        // In-flow, not `position: absolute` (design: V-OTA Planner.dc.html:127-138)
        // — SidebarRail's <aside> is `overflow-hidden`, so an absolutely
        // positioned popup wide enough for label text gets clipped once the
        // rail is collapsed to 68px. Stacking this as a normal sibling above
        // the toggle button instead just grows the footer's height (the
        // scrollable conversation list above it absorbs the difference), the
        // same way the design handles it. `var(--g3)` (not the `glass-panel`
        // utility's blurred `--g1`) matches the design's own background for
        // this exact block — opaque enough to stay readable over any page
        // content behind the rail.
        <div
          role="menu"
          className="flex flex-col gap-0.5 p-1.5 rounded-[14px] border border-edge"
          style={{
            background: 'var(--g3)',
            boxShadow: '0 18px 40px -26px rgb(var(--shadow-rgb) / 0.7)',
            animation: 'vFade .22s ease both',
          }}
        >
          <button
            type="button"
            role="menuitem"
            title={t('authProfilePassword')}
            onClick={() => {
              setOpen(false)
              setProfileModalOpen(true)
            }}
            className={`h-9 rounded-[10px] flex items-center gap-2 text-[12px] font-medium text-on-surface text-left transition-colors hover:bg-fill ${
              collapsed ? 'justify-center px-0' : 'px-2.5'
            }`}
          >
            <span className="material-symbols-outlined text-[16px] opacity-75 shrink-0" aria-hidden="true">
              account_circle
            </span>
            {!collapsed && t('authProfilePassword')}
          </button>
          <button
            type="button"
            role="menuitem"
            title={t('authSignOut')}
            onClick={() => {
              setOpen(false)
              signOut()
            }}
            className={`h-9 rounded-[10px] flex items-center gap-2 text-[12px] font-medium text-left transition-colors hover:bg-fill ${
              collapsed ? 'justify-center px-0' : 'px-2.5'
            }`}
            style={{ color: 'var(--color-error)' }}
          >
            <span className="material-symbols-outlined text-[16px] opacity-75 shrink-0" aria-hidden="true">
              logout
            </span>
            {!collapsed && t('authSignOut')}
          </button>
        </div>
      )}
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-haspopup="menu"
        title={displayName}
        className={`h-9 w-full rounded-xl border border-outline-variant bg-glass-1 flex items-center gap-2 hover:bg-glass-2 transition-colors ${
          collapsed ? 'justify-center px-0' : 'px-0'
        }`}
      >
        <UserAvatar user={user} displayName={displayName} className="w-6 h-6 shrink-0 rounded-full text-[11px]" />
        {!collapsed && (
          <>
            <span className="flex-1 min-w-0 text-[12px] font-medium text-on-surface truncate text-left">
              {displayName}
            </span>
            <span className="material-symbols-outlined text-[16px] text-on-surface-faint" aria-hidden="true">
              expand_more
            </span>
          </>
        )}
      </button>
      {profileModalOpen &&
        createPortal(<ProfilePasswordModal onClose={() => setProfileModalOpen(false)} />, document.body)}
    </div>
  )
}
