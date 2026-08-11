/**
 * use-mapbox-map.ts — Mapbox GL JS map lifecycle: creation, theme-driven
 * style swap, cleanup, resize handling around the focus-mode collapse-to-
 * width-0 transition, and (Phase 10.5) load status / error+retry / a
 * map-vs-satellite style axis independent of theme. Named deliberately
 * unlike the `use-leaflet-map` hook the (now-superseded) Leaflet plan called
 * for.
 *
 * No VITE_MAPBOX_TOKEN configured -> `tokenMissing` is true and this hook
 * never constructs a mapboxgl.Map at all. There is no free-tile equivalent
 * to Leaflet+OSM for official Mapbox styles, so MapView renders an honest
 * "map unavailable" state in that case instead of silently falling back to
 * a different, unrequested map provider (see the phase-10 plan's §"Missing
 * VITE_MAPBOX_TOKEN" decision).
 *
 * Gotchas this hook exists to hide from callers:
 *
 *  - `map.setStyle()` (fired on every theme/styleKind change) wipes all
 *    custom GeoJSON sources/layers previously added — but NOT
 *    `mapboxgl.Marker`s, which are plain DOM elements. `styleVersion`
 *    increments on every 'load'/'style.load' (including the very first
 *    one), so a route-drawing effect keyed on `[styleVersion, ...data]`
 *    correctly re-adds its source/layers after every style (re)load,
 *    including theme/style-kind swaps.
 *
 *  - Resize on the focus-mode collapse-to-0 transition uses a
 *    ResizeObserver on the map's own container, NOT `transitionend` on an
 *    ancestor wrapper. Both stage-hotels.tsx and stage-workspace.tsx
 *    transition multiple CSS properties at different durations on that
 *    wrapper (flex/opacity/transform/filter) — listening for one
 *    `transitionend` risks matching the wrong property, or breaking
 *    silently if that inline transition string is edited later.
 *    ResizeObserver reacts to the actual rendered box size regardless of
 *    cause, and is coalesced through requestAnimationFrame so a ~600ms
 *    transition doesn't trigger dozens of `map.resize()` calls.
 *
 *  - `status: 'error'` is only ever reached from `'loading'` — a
 *    `map.on('error', ...)` firing AFTER the map has successfully reached
 *    `'ready'` once (a single bad tile fetch, a missing sprite glyph, a
 *    transient network hiccup) is logged as a warning and otherwise
 *    ignored, never demoted back to `'error'`. Mapbox GL fires `'error'`
 *    for plenty of non-fatal conditions; only a failure to ever load in the
 *    first place should show the user a broken map (Phase 10.5 spec §16 —
 *    an error must not crash a map that's already working).
 *
 *  - `retry()` only makes sense pre-`ready` (see above), so it's a full
 *    teardown + recreate of the map instance via a `retryKey` dependency —
 *    there is deliberately no attempt to preserve markers/sources across a
 *    retry, because a map that's never been `ready` never had any.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import type { RefObject } from 'react'
import mapboxgl from 'mapbox-gl'
import 'mapbox-gl/dist/mapbox-gl.css'
import type { Theme } from './use-theme'

// Center of Đà Nẵng — an initial camera position only, never used to place
// a marker for unparseable data (parseCoordinates/geo.ts drops those instead).
const DEFAULT_CENTER: [number, number] = [108.2208, 16.0544]
const DEFAULT_ZOOM = 11

const STYLE_URL: Record<Theme, string> = {
  light: 'mapbox://styles/mapbox/streets-v12',
  dark: 'mapbox://styles/mapbox/dark-v11',
}
// No dark variant — satellite imagery doesn't have a meaningful "dark mode",
// so satellite mode always uses this one style regardless of `theme`.
const SATELLITE_STYLE_URL = 'mapbox://styles/mapbox/satellite-streets-v12'

export type MapStatus = 'loading' | 'ready' | 'error'
export type MapStyleKind = 'map' | 'satellite'

function styleUrlFor(theme: Theme, styleKind: MapStyleKind): string {
  return styleKind === 'satellite' ? SATELLITE_STYLE_URL : STYLE_URL[theme]
}

export interface UseMapboxMapResult {
  containerRef: RefObject<HTMLDivElement | null>
  mapRef: RefObject<mapboxgl.Map | null>
  /** 'loading' until the style first fires 'load'; 'error' only if that never happens. */
  status: MapStatus
  /** Bumped on every successful (re)load, including theme/style-kind-driven setStyle() reloads. */
  styleVersion: number
  /** VITE_MAPBOX_TOKEN absent/empty — caller must render the honest unavailable state. */
  tokenMissing: boolean
  /** Tears down and recreates the map instance. Only meaningful while status === 'error'. */
  retry: () => void
}

export function useMapboxMap(theme: Theme, styleKind: MapStyleKind = 'map'): UseMapboxMapResult {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const mapRef = useRef<mapboxgl.Map | null>(null)
  const [status, setStatus] = useState<MapStatus>('loading')
  const [styleVersion, setStyleVersion] = useState(0)
  const [retryKey, setRetryKey] = useState(0)
  // Tracks "has this map instance ever reached ready" — the gate that keeps
  // a post-ready 'error' event from demoting a working map back to the
  // error screen (see file doc comment).
  const everReadyRef = useRef(false)

  const token = (import.meta.env.VITE_MAPBOX_TOKEN as string | undefined) || ''
  const tokenMissing = !token

  const retry = useCallback(() => {
    setStatus('loading')
    setRetryKey((k) => k + 1)
  }, [])

  // Create the map once per mount (or per retry()). Intentionally NOT keyed
  // on `theme`/`styleKind` — the initial style uses whichever is current at
  // creation time, and every later change is applied via setStyle() in the
  // effect below rather than tearing the map down and recreating it.
  useEffect(() => {
    if (tokenMissing || !containerRef.current) return

    mapboxgl.accessToken = token
    const map = new mapboxgl.Map({
      container: containerRef.current,
      style: styleUrlFor(theme, styleKind),
      center: DEFAULT_CENTER,
      zoom: DEFAULT_ZOOM,
    })
    mapRef.current = map
    everReadyRef.current = false

    const onLoad = () => {
      everReadyRef.current = true
      setStatus('ready')
      setStyleVersion((v) => v + 1)
    }
    const onError = (e: mapboxgl.ErrorEvent) => {
      if (everReadyRef.current) {
        // Non-fatal once the map has proven it can load — a bad tile fetch
        // or a missing glyph shouldn't blank out a map that's already usable.
        console.warn('[map] mapbox-gl error after ready (ignored):', e.error)
        return
      }
      console.error('[map] mapbox-gl failed to load:', e.error)
      setStatus('error')
    }
    map.on('load', onLoad)
    map.on('style.load', onLoad)
    map.on('error', onError)

    return () => {
      map.off('load', onLoad)
      map.off('style.load', onLoad)
      map.off('error', onError)
      map.remove()
      mapRef.current = null
      setStatus('loading')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- theme/styleKind handled by the setStyle effect below; retryKey intentionally forces a full recreate
  }, [tokenMissing, token, retryKey])

  // Theme/style-kind change -> setStyle() on the existing map instead of
  // recreating it. Also re-applies once `status` first flips to 'ready', in
  // case theme or style changed during the brief window before the initial
  // 'load' fired.
  useEffect(() => {
    const map = mapRef.current
    if (!map || status !== 'ready') return
    map.setStyle(styleUrlFor(theme, styleKind))
  }, [theme, styleKind, status])

  // Resize around the focus-mode collapse transition (see file doc comment).
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    let raf = 0
    const observer = new ResizeObserver(() => {
      if (raf) cancelAnimationFrame(raf)
      raf = requestAnimationFrame(() => {
        mapRef.current?.resize()
      })
    })
    observer.observe(el)
    return () => {
      if (raf) cancelAnimationFrame(raf)
      observer.disconnect()
    }
  }, [])

  return { containerRef, mapRef, status, styleVersion, tokenMissing, retry }
}
