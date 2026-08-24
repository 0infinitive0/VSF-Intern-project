import type { ReactNode } from 'react'
import { Sidebar } from './sidebar'

interface AdminShellProps {
  path: string
  navigate: (to: string) => void
  children: ReactNode
}

/** A2 — sidebar (240px) + content column. Route dispatch lives in
 * admin-app.tsx; this component only owns the fixed layout frame. `path`/
 * `navigate` come from admin-app.tsx's single useAdminRoute() call, not a
 * second instance here, so the two never have a chance to disagree. */
export function AdminShell({ path, navigate, children }: AdminShellProps) {
  return (
    <div style={{ display: 'flex', height: '100vh', width: '100%' }}>
      <Sidebar path={path} navigate={navigate} />
      <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>{children}</div>
    </div>
  )
}
