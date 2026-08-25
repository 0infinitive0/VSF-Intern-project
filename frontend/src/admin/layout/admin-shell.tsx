import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { listAmenityCatalog } from '../api/amenity-catalog-client'
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
  const [pendingAmenityCount, setPendingAmenityCount] = useState<number | undefined>(undefined)

  // Fetched here (not inside amenity-catalog-page.tsx) so the sidebar badge
  // is visible from every admin screen, not only while the page itself is
  // mounted -- page_size=1 since only `pending_count` is read.
  useEffect(() => {
    let cancelled = false
    listAmenityCatalog({ scope: 'all', status: 'pending', category: 'all', page: 1, pageSize: 1 }).then((result) => {
      if (!cancelled && result.ok) setPendingAmenityCount(result.data.pending_count)
    })
    return () => {
      cancelled = true
    }
  }, [path])

  return (
    <div style={{ display: 'flex', height: '100vh', width: '100%' }}>
      <Sidebar path={path} navigate={navigate} pendingAmenityCount={pendingAmenityCount} />
      <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>{children}</div>
    </div>
  )
}
