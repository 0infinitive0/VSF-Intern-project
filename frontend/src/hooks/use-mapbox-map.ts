/**
 * use-mapbox-map.ts — Mapbox GL JS map lifecycle: creation, theme-driven
 * style swap, cleanup, and resize handling around the focus-mode
 * collapse-to-width-0 transition. Named deliberately unlike the
 * `use-leaflet-map` hook the (now-superseded) Leaflet plan called for.
 *
 * No VITE_MAPBOX_TOKEN configured -> `tokenMissing` is true and this hook
 * never constructs a mapboxgl.Map at all. There is no free-tile equivalent
 * to Leaflet+OSM for official Mapbox styles, so MapView renders an honest
 * "map unavailable" state in that case instead of silently falling back to
 * a different, unrequested map provider (see the phase-10 plan's §"Missing
 * VITE_MAPBOX_TOKEN" decision).
 *
 * Two gotchas this hook exists to hide from callers:
 *
 *  - `map.setStyle()` (fired on every theme change) wipes all custom
 *    GeoJSON sources/layers previously added — but NOT `mapboxgl.Marker`s,
 *    which are plain DOM elements. `styleVersion` increments on every
 *    'load'/'style.load' (including the very first one), so a route-drawing
 *    effect keyed on `[styleVersion, ...data]` correctly re-adds its
 *    source/layers after every style (re)load, including theme swaps.
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
 */
import { useEffect, useRef, useState } from 'react'
import type { RefObject } from 'react'
import mapboxgl from 'mapbox-gl'
import 'mapbox-gl/dist/mapbox-gl.css'
import type { Theme } from './use-theme'

// Center of Đà Nẵng — an initial camera position only, never used to place
// a marker for unparseable data (parseCoordinates/geo.ts drops those instead).
const DEFAULT_CENTER: [number, number] = [108.2208, 16.0544]
const DEFAULT_ZOOM = 11

const STYLE_URL: Record<Theme, string> = {
  light: 'mapbox://styles/mapbox/light-v11',
  dark: 'mapbox://styles/mapbox/dark-v11',
}

export interface UseMapboxMapResult {
  containerRef: RefObject<HTMLDivElement | null>
  mapRef: RefObject<mapboxgl.Map | null>
  /** True once the style has fired 'load' at least once — safe to add markers/sources. */
  ready: boolean
  /** Bumped on every successful (re)load, including theme-driven setStyle() reloads. */
  styleVersion: number
  /** VITE_MAPBOX_TOKEN absent/empty — caller must render the honest unavailable state. */
  tokenMissing: boolean
}

export function useMapboxMap(theme: Theme): UseMapboxMapResult {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const mapRef = useRef<mapboxgl.Map | null>(null)
  const [ready, setReady] = useState(false)
  const [styleVersion, setStyleVersion] = useState(0)

  const token = (import.meta.env.VITE_MAPBOX_TOKEN as string | undefined) || ''
  const tokenMissing = !token

  // Create the map once per mount. Intentionally NOT keyed on `theme` —
  // the initial style uses whichever theme is current at creation time, and
  // every later theme change is applied via setStyle() in the effect below
  // rather than tearing the map down and recreating it.
  useEffect(() => {
    if (tokenMissing || !containerRef.current) return

    mapboxgl.accessToken = token
    const map = new mapboxgl.Map({
      container: containerRef.current,
      style: STYLE_URL[theme],
      center: DEFAULT_CENTER,
      zoom: DEFAULT_ZOOM,
    })
    mapRef.current = map

    const onLoad = () => {
      setReady(true)
      setStyleVersion((v) => v + 1)
    }
    map.on('load', onLoad)
    map.on('style.load', onLoad)

    return () => {
      map.off('load', onLoad)
      map.off('style.load', onLoad)
      map.remove()
      mapRef.current = null
      setReady(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- see comment above: theme handled below
  }, [tokenMissing, token])

  // Theme change -> setStyle() on the existing map instead of recreating it.
  // Also re-applies once `ready` first flips true, in case the theme changed
  // during the brief window before the initial 'load' fired.
  useEffect(() => {
    const map = mapRef.current
    if (!map || !ready) return
    map.setStyle(STYLE_URL[theme])
  }, [theme, ready])

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

  return { containerRef, mapRef, ready, styleVersion, tokenMissing }
}
