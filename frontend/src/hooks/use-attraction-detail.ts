import { useEffect, useState } from 'react'
import { getAttractionDetail } from '../api/place-client'
import type { AttractionDetail } from '../types'

/**
 * use-attraction-detail — fetch + per-session cache for GET /attractions/{id}.
 *
 * Mirror of use-hotel-detail.ts (phase-08): the plan wants one fetch per place
 * id per session (phase-09 §phi-chuc-nang). The cache is module-level so it
 * survives focus open/close/switch (layout transforms, not unmounts) and even
 * a panel remount, but is dropped with the page. Both successes and misses
 * (404/network) are cached so a broken id doesn't re-request on every open; a
 * miss renders the panel's "no details" state — never an error screen.
 */
type Status = 'idle' | 'loading' | 'ready' | 'error'

const cache = new Map<string, AttractionDetail | null>()

export function useAttractionDetail(attractionId: string | null): {
  detail: AttractionDetail | null
  status: Status
} {
  const [detail, setDetail] = useState<AttractionDetail | null>(attractionId ? (cache.get(attractionId) ?? null) : null)
  const [status, setStatus] = useState<Status>(() =>
    attractionId == null ? 'idle' : cache.has(attractionId) ? (cache.get(attractionId) ? 'ready' : 'error') : 'loading',
  )

  useEffect(() => {
    if (attractionId == null) {
      setDetail(null)
      setStatus('idle')
      return
    }
    if (cache.has(attractionId)) {
      const hit = cache.get(attractionId) ?? null
      setDetail(hit)
      setStatus(hit ? 'ready' : 'error')
      return
    }
    let cancelled = false
    setDetail(null)
    setStatus('loading')
    getAttractionDetail(attractionId).then((result) => {
      cache.set(attractionId, result)
      if (cancelled) return
      setDetail(result)
      setStatus(result ? 'ready' : 'error')
    })
    return () => {
      cancelled = true
    }
  }, [attractionId])

  return { detail, status }
}
