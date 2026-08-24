/**
 * router.tsx — the admin portal's own router. No react-router-dom: ~10 flat
 * routes, no nested routes, no loaders/actions -- a history.pushState +
 * popstate hook is enough (see phase-03-admin-shell-frontend.md's
 * Architecture section for why). If a future phase needs nested routes or
 * loaders, replace this file; it's the only place route state lives.
 */
import { useCallback, useEffect, useState } from 'react'

export interface AdminRoute {
  path: string
  navigate: (to: string) => void
}

function currentPath(): string {
  return window.location.pathname
}

export function useAdminRoute(): AdminRoute {
  const [path, setPath] = useState(currentPath)

  useEffect(() => {
    const onPopState = () => setPath(currentPath())
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [])

  const navigate = useCallback((to: string) => {
    if (to === currentPath()) return
    window.history.pushState(null, '', to)
    setPath(to)
  }, [])

  return { path, navigate }
}

/** True when `path` is `base` itself or nested under `base/`. Used for both
 * route matching and sidebar active-state (a hotel edit page still counts
 * as "under /admin/hotels" for nav highlighting). */
export function matchesBase(path: string, base: string): boolean {
  return path === base || path.startsWith(`${base}/`)
}
