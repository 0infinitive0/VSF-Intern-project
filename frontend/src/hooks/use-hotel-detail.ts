import { useEffect, useState } from 'react'
import { getHotelDetail } from '../api/place-client'
import type { HotelDetail } from '../types'

/**
 * use-hotel-detail — fetch + per-session cache for GET /hotels/{id}.
 *
 * The plan is explicit: one fetch per hotel id per session (phase-08
 * §non-functional). The cache is module-level — it survives focus
 * open/close/switch (those are layout transforms, not unmounts) and even a
 * remount of the panel, but is dropped with the page (session-scoped). Both
 * successes and misses (404/network) are cached so a broken id doesn't
 * re-request on every open; a miss renders the panel's "no details" state.
 */
type Status = 'idle' | 'loading' | 'ready' | 'error'

const cache = new Map<string, HotelDetail | null>()

export function useHotelDetail(hotelId: string | null): {
  detail: HotelDetail | null
  status: Status
} {
  const [detail, setDetail] = useState<HotelDetail | null>(hotelId ? (cache.get(hotelId) ?? null) : null)
  const [status, setStatus] = useState<Status>(() =>
    hotelId == null ? 'idle' : cache.has(hotelId) ? (cache.get(hotelId) ? 'ready' : 'error') : 'loading',
  )

  useEffect(() => {
    if (hotelId == null) {
      setDetail(null)
      setStatus('idle')
      return
    }
    if (cache.has(hotelId)) {
      const hit = cache.get(hotelId) ?? null
      setDetail(hit)
      setStatus(hit ? 'ready' : 'error')
      return
    }
    let cancelled = false
    setDetail(null)
    setStatus('loading')
    getHotelDetail(hotelId).then((result) => {
      cache.set(hotelId, result)
      if (cancelled) return
      setDetail(result)
      setStatus(result ? 'ready' : 'error')
    })
    return () => {
      cancelled = true
    }
  }, [hotelId])

  return { detail, status }
}
