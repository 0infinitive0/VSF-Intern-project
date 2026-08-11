import { useEffect, useMemo, useRef, useState } from 'react'
import mapboxgl from 'mapbox-gl'
import { useTranslation } from 'react-i18next'
import { useMapboxMap } from '../hooks/use-mapbox-map'
import { boundsOf, parseCoordinates, toLngLat } from '../lib/geo'
import { dayColor, legColor } from '../lib/map-colors'
import type { HotelMapRay } from '../lib/map-presentation'
import { highlightedRouteKeys } from '../lib/map-presentation'
import type { RouteSegment } from '../lib/route-segments'
import type { Theme } from '../hooks/use-theme'
import type { MapStyleKind } from '../hooks/use-mapbox-map'
import MapControls from './map-controls'
import MapStateOverlay from './map-state-overlay'

const ROUTE_SOURCE = 'trip-routes'
const RAY_SOURCE = 'hotel-distance-rays'
const HALO_SOURCE = 'hotel-selection-halo'
const DRIVE_LAYER = 'route-drive'
const WALK_LAYER = 'route-walk'
const FALLBACK_LAYER = 'route-fallback'
// Only drive/walk animate (see addRouteLayers) — fallback is an honest
// straight-line estimate, not a real route, and never gets the "flowing"
// treatment that would make it look like real navigated data.
const ANIMATED_LAYERS = [DRIVE_LAYER, WALK_LAYER] as const
const ROUTE_LAYER_IDS = [DRIVE_LAYER, WALK_LAYER, FALLBACK_LAYER] as const
const RAY_LAYER = 'hotel-distance-rays-line'
const HALO_LAYER = 'hotel-selection-halo-circle'

// Fade-in duration when a leg first appears (tab/day change or initial load).
const ROUTE_FADE_MS = 400

// Per-layer rest width/opacity — the ONE place these live, read by
// addRouteLayers (paint) and by the fade-in effect (restoring after the
// zero-opacity flash). Keeping this a plain table instead of scattering
// magic numbers is what makes the fade-in/hover logic below able to stay
// generic across all 3 layers instead of one bespoke branch per layer.
// Mapbox GL requires every line-dasharray entry to be positive — a literal
// 0 (rather than a very small gap) makes the WHOLE layer disappear in some
// renderers, not just render as solid. Every dasharray below, static or
// animated, must go through this instead of a bare 0.
const DASH_EPSILON = 0.01

// route-drive's "0" gap is what makes it read as one continuous solid line
// while idle (before the flow animation below takes over, or permanently
// when `prefers-reduced-motion` skips that effect entirely) — hence
// DASH_EPSILON instead of a literal 0.
const LAYER_STYLE: Record<string, { width: number; opacity: number; dash: [number, number] }> = {
  [DRIVE_LAYER]: { width: 5, opacity: 0.9, dash: [1, DASH_EPSILON] },
  [WALK_LAYER]: { width: 4, opacity: 0.9, dash: [0.6, 2] },
  [FALLBACK_LAYER]: { width: 3, opacity: 0.45, dash: [0.6, 1.8] },
}

// Direction-of-travel dash animation — one shared mechanism for both
// animated layers (§9 of the earlier animation spec: never one animation
// loop per segment/leg, one mechanism for the whole route regardless of how
// many legs/days are in it). Cycle length controls how long a full pattern
// period takes to drift past; shorter = livelier (walking), longer = calmer
// (driving) — tuned to feel like motion, not a loading spinner.
const FLOW: Record<string, { dash: number; gap: number; cycleMs: number }> = {
  [DRIVE_LAYER]: { dash: 3, gap: 2, cycleMs: 2200 },
  [WALK_LAYER]: { dash: 0.6, gap: 2, cycleMs: 1400 },
}

// Mapbox GL caches every distinct `line-dasharray` it's ever been asked to
// draw in ONE shared, fixed-size texture (LineAtlas) — each new pattern
// claims space permanently and is never evicted
// (line_atlas.js: `if (this.nextRow + rowHeight > this.height) return
// warnOnce("LineAtlas out of space"), null`). Feeding it a raw elapsed-time
// float every single animation frame mints a virtually unique pattern on
// EVERY frame (two layers × ~60fps), which silently exhausts that atlas
// within minutes — after which the layer needing a new pattern just stops
// drawing, no error, no crash, the line vanishes. This is exactly what made
// the walking route disappear (drive happened to still have room). Mapbox's
// own "animate a line" example avoids this by cycling a small, FIXED set of
// precomputed dasharrays instead of an unbounded continuous ramp — FLOW_STEPS
// quantizes to the same fix: only this many distinct patterns per layer ever
// exist, so they're reused/cache-hit from the atlas forever after warm-up.
const FLOW_STEPS = 24

/**
 * Phase-shifts a fixed [dash, gap] pattern by elapsed time, quantized to
 * FLOW_STEPS discrete positions per cycle (see FLOW_STEPS doc above) — for
 * pattern [D, G] with period P = D+G, at offset o ∈ [0, P): while o is still
 * inside the dash (o < D) the visible remainder is (D - o) then a full
 * [G, D, G]; once o has moved into the gap (o >= D) nothing is visible yet,
 * then the remaining gap then a full [D, G]. GL tiles whatever 4-tuple is
 * given, so this alone represents the shifted infinite pattern — no
 * per-frame DOM work, no React state, just one setPaintProperty call per
 * animated layer.
 */
function animatedDash(dash: number, gap: number, cycleMs: number, elapsedMs: number): [number, number, number, number] {
  const period = dash + gap
  const step = Math.floor(((elapsedMs % cycleMs) / cycleMs) * FLOW_STEPS)
  const offset = (step / FLOW_STEPS) * period
  return offset < dash
    ? [Math.max(DASH_EPSILON, dash - offset), gap, dash, gap]
    : [DASH_EPSILON, Math.max(DASH_EPSILON, period - offset), dash, gap]
}

export interface MapMarkerSpec {
  syncId: string
  coordinates?: string | null
  kind: 'hotel' | 'item'
  label?: number
  dayNumber?: number
  openId?: string
  endpoint?: 'start' | 'end'
  priceLabel?: string
  matchLabel?: string
}

export interface MapViewProps {
  variant: 'workspace' | 'hotels'
  theme: Theme
  markers: MapMarkerSpec[]
  segments: RouteSegment[]
  hoveredId: string | null
  onHoverChange: (id: string | null) => void
  onMarkerClick: (marker: MapMarkerSpec) => void
  selectedId?: string | null
  hotelRays?: HotelMapRay[]
}

type FeatureCollection = { type: 'FeatureCollection'; features: Array<Record<string, unknown>> }

function routeData(segments: RouteSegment[]): FeatureCollection {
  return {
    type: 'FeatureCollection',
    features: segments.map((segment) => ({
      type: 'Feature',
      id: segment.segKey,
      properties: { segKey: segment.segKey, isFallback: segment.isFallback, profile: segment.profile, color: legColor(segment.legIndex) },
      geometry: { type: 'LineString', coordinates: segment.points.map(toLngLat) },
    })),
  }
}

// Hover highlight (§1/§3 of the earlier UI-fix spec): the related leg
// brightens to full opacity + a bit wider; every OTHER leg dims (never to
// 0) whenever anything is hovered; a leg's own color never changes. One
// shape shared by all 3 layers — there is no longer a separate "casing"/
// "flow" role with different rules, which is exactly the kind of extra
// moving part this rebuild is cutting.
function opacityExpr(rest: number): mapboxgl.DataDrivenPropertyValueSpecification<number> {
  return ['case', ['boolean', ['feature-state', 'hovered'], false], 1, ['boolean', ['feature-state', 'dimmed'], false], 0.2, rest]
}
function widthExpr(rest: number): mapboxgl.DataDrivenPropertyValueSpecification<number> {
  return ['case', ['boolean', ['feature-state', 'hovered'], false], rest + 2, rest]
}

function addRouteLayers(map: mapboxgl.Map) {
  map.addSource(ROUTE_SOURCE, { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
  const layout: mapboxgl.LineLayerSpecification['layout'] = { 'line-cap': 'round', 'line-join': 'round' }
  const realRouteFilter = ['==', ['get', 'isFallback'], false]
  const walkFilter = ['all', realRouteFilter, ['==', ['get', 'profile'], 'walking']]
  const driveFilter = ['all', realRouteFilter, ['!=', ['get', 'profile'], 'walking']]
  const fadeIn = { 'line-opacity-transition': { duration: ROUTE_FADE_MS, delay: 0 } }

  for (const [id, filter] of [
    [DRIVE_LAYER, driveFilter],
    [WALK_LAYER, walkFilter],
    [FALLBACK_LAYER, ['==', ['get', 'isFallback'], true]],
  ] as const) {
    const style = LAYER_STYLE[id]
    map.addLayer({
      id,
      type: 'line',
      source: ROUTE_SOURCE,
      filter,
      layout,
      paint: {
        ...fadeIn,
        'line-color': ['get', 'color'],
        'line-dasharray': style.dash,
        'line-opacity': opacityExpr(style.opacity),
        'line-width': widthExpr(style.width),
      },
    } as mapboxgl.LineLayerSpecification)
  }
}

/** Zeroes then restores each route layer's opacity — the fade-in cue when a leg first appears (tab/day change, initial load). */
function flashRouteIn(map: mapboxgl.Map) {
  for (const id of ROUTE_LAYER_IDS) {
    if (map.getLayer(id)) map.setPaintProperty(id, 'line-opacity', 0)
  }
  requestAnimationFrame(() => {
    for (const id of ROUTE_LAYER_IDS) {
      if (map.getLayer(id)) map.setPaintProperty(id, 'line-opacity', opacityExpr(LAYER_STYLE[id].opacity))
    }
  })
}

function createMarkerElement(marker: MapMarkerSpec): { root: HTMLDivElement; content: HTMLDivElement } {
  const root = document.createElement('div')
  const content = document.createElement('div')
  root.appendChild(content)
  content.style.cursor = 'pointer'
  content.style.transition = 'transform .25s cubic-bezier(.34,1.5,.64,1), box-shadow .25s ease, opacity .2s ease'
  content.style.transformOrigin = 'center'
  content.style.color = '#FCFDFE'
  content.style.border = '2px solid #fff'
  content.style.boxShadow = '0 4px 12px -3px rgba(0,0,0,.45)'
  if (marker.kind === 'hotel') {
    content.style.display = 'flex'
    content.style.alignItems = 'center'
    content.style.gap = '6px'
    content.style.whiteSpace = 'nowrap'
    content.style.padding = '5px 10px'
    content.style.borderRadius = '999px'
    content.style.background = '#3A73DE'
    content.style.font = "500 11.5px/1.2 'Be Vietnam Pro', sans-serif"
    content.style.setProperty('--base-marker', '#3A73DE')
    if (marker.priceLabel) { const price = document.createElement('b'); price.textContent = marker.priceLabel; price.style.fontWeight = '590'; content.appendChild(price) }
    if (marker.matchLabel) { const match = document.createElement('span'); match.textContent = marker.matchLabel; match.style.opacity = '.75'; content.appendChild(match) }
  } else {
    content.style.width = '26px'
    content.style.height = '26px'
    content.style.borderRadius = '50%'
    content.style.background = dayColor(marker.dayNumber ?? 1)
    content.style.font = "600 12px/26px 'Be Vietnam Pro', sans-serif"
    content.style.textAlign = 'center'
    content.style.animation = `vPinIn .6s ${(marker.label ?? 1) * 65}ms cubic-bezier(.34,1.4,.64,1) backwards`
    content.textContent = marker.label != null ? String(marker.label) : ''
    if (marker.endpoint) {
      const badge = document.createElement('div')
      badge.textContent = marker.endpoint === 'start' ? 'XUẤT PHÁT' : 'KẾT THÚC'
      badge.style.cssText = "position:absolute;left:50%;bottom:30px;transform:translateX(-50%);white-space:nowrap;padding:2px 8px;border-radius:99px;background:var(--btn);color:var(--btn-fg);font:600 9.5px/1.4 'Be Vietnam Pro',sans-serif;letter-spacing:.04em;box-shadow:0 6px 14px -6px rgba(0,0,0,.6)"
      content.appendChild(badge)
    }
  }
  return { root, content }
}

function applyMarkerState(content: HTMLElement, marker: MapMarkerSpec, hovered: boolean, selected: boolean, dimmed: boolean) {
  const scale = marker.kind === 'hotel' ? (hovered ? 1.18 : 1) : (hovered || selected ? 1.45 : 1)
  content.style.transform = `scale(${scale})`
  const root = content.parentElement as HTMLElement | null
  if (root) root.style.zIndex = hovered ? '1000' : selected ? '900' : '0'
  content.style.opacity = dimmed ? '.55' : '1'
  content.style.boxShadow = hovered || selected ? '0 8px 20px -4px rgba(0,0,0,.5), 0 0 0 6px rgba(255,255,255,.55)' : '0 4px 12px -3px rgba(0,0,0,.45)'
  if (marker.kind === 'hotel') content.style.background = selected ? '#0e1319' : 'var(--base-marker)'
}

function fitWorkspace(map: mapboxgl.Map, points: { lat: number; lng: number }[]) {
  if (points.length === 1) map.flyTo({ center: toLngLat(points[0]), zoom: 15, duration: 900 })
  else if (points.length > 1) { const bounds = boundsOf(points)!; map.fitBounds([[bounds.sw.lng, bounds.sw.lat], [bounds.ne.lng, bounds.ne.lat]], { padding: 56, maxZoom: 15, duration: 900 }) }
}

export default function MapView({ variant, theme, markers, segments, hoveredId, onHoverChange, onMarkerClick, selectedId = null, hotelRays = [] }: MapViewProps) {
  const { t } = useTranslation()
  const [styleKind, setStyleKind] = useState<MapStyleKind>('map')
  const { containerRef, mapRef, status, styleVersion, tokenMissing, retry } = useMapboxMap(theme, styleKind)
  const markerRegistry = useRef(new Map<string, { marker: mapboxgl.Marker; spec: MapMarkerSpec }>())
  const badgeRegistry = useRef<mapboxgl.Marker[]>([])
  const hotelCameraSet = useRef(false)
  const onHoverRef = useRef(onHoverChange); onHoverRef.current = onHoverChange
  const onClickRef = useRef(onMarkerClick); onClickRef.current = onMarkerClick
  const markerKey = useMemo(() => markers.map((marker) => JSON.stringify(marker)).join('|'), [markers])

  useEffect(() => {
    const map = mapRef.current
    if (!map || status !== 'ready') return
    markerRegistry.current.forEach(({ marker }) => marker.remove()); markerRegistry.current.clear()
    const points: { lat: number; lng: number }[] = []
    const duplicateCount = new Map<string, number>()
    for (const spec of markers) {
      const point = spec.kind === 'hotel' ? parseCoordinates(spec.coordinates) : null
      if (!point) continue
      const key = `${point.lat.toFixed(4)},${point.lng.toFixed(4)}`
      duplicateCount.set(key, (duplicateCount.get(key) ?? 0) + 1)
    }
    const duplicateIndex = new Map<string, number>()
    for (const spec of markers) {
      const point = parseCoordinates(spec.coordinates); if (!point) continue
      points.push(point)
      const { root, content } = createMarkerElement(spec)
      content.addEventListener('mouseenter', () => { root.style.zIndex = '1000'; onHoverRef.current(spec.syncId) })
      content.addEventListener('mouseleave', () => { root.style.zIndex = '0'; onHoverRef.current(null) })
      content.addEventListener('click', (event) => { event.stopPropagation(); onClickRef.current(spec) })
      const key = `${point.lat.toFixed(4)},${point.lng.toFixed(4)}`
      const count = spec.kind === 'hotel' ? duplicateCount.get(key) ?? 1 : 1
      const index = duplicateIndex.get(key) ?? 0
      if (spec.kind === 'hotel') duplicateIndex.set(key, index + 1)
      const angle = count > 1 ? (Math.PI * 2 * index) / count - Math.PI / 2 : 0
      const offset: [number, number] = count > 1 ? [Math.cos(angle) * 18, Math.sin(angle) * 18] : [0, 0]
      const marker = new mapboxgl.Marker({ element: root, anchor: spec.kind === 'hotel' ? 'bottom' : 'center', offset }).setLngLat(toLngLat(point)).addTo(map)
      markerRegistry.current.set(spec.syncId, { marker, spec })
    }
    if (variant === 'hotels' && !hotelCameraSet.current) { map.jumpTo({ center: [108.24, 16.045], zoom: 12 }); hotelCameraSet.current = true }
    if (variant === 'workspace') fitWorkspace(map, points)
  }, [markerKey, markers, status, variant, mapRef])

  useEffect(() => {
    const anyActive = hoveredId != null || selectedId != null
    markerRegistry.current.forEach(({ marker, spec }, id) => {
      const content = marker.getElement().firstElementChild as HTMLElement | null
      if (content) applyMarkerState(content, spec, id === hoveredId, id === selectedId, anyActive && id !== hoveredId && id !== selectedId)
    })
  }, [hoveredId, selectedId, markerKey])

  // Route source/layers: created once, then just setData() on every
  // segments change (tab/day switch, hotel rotation) — no geometry-reveal
  // animation, just a plain opacity flash so the swap doesn't feel like an
  // abrupt cut. Simpler and far easier to reason about than a trim-offset
  // draw-in: one visual property (opacity), one transition, no dependency
  // on line-metrics.
  useEffect(() => {
    const map = mapRef.current
    if (!map || status !== 'ready' || variant !== 'workspace') return
    if (!map.getSource(ROUTE_SOURCE)) addRouteLayers(map)
    const source = map.getSource(ROUTE_SOURCE) as mapboxgl.GeoJSONSource
    source.setData(routeData(segments) as never)
    flashRouteIn(map)
  }, [segments, status, styleVersion, variant, mapRef])

  useEffect(() => {
    const map = mapRef.current
    if (!map || status !== 'ready' || variant !== 'workspace' || !map.getSource(ROUTE_SOURCE)) return
    const activeSegmentKeys = highlightedRouteKeys(segments, hoveredId, null)
    const active = hoveredId != null
    for (const segment of segments) map.setFeatureState({ source: ROUTE_SOURCE, id: segment.segKey }, { hovered: activeSegmentKeys.has(segment.segKey), dimmed: active && !activeSegmentKeys.has(segment.segKey) })
  }, [hoveredId, segments, status, styleVersion, variant, mapRef])

  // Direction-of-travel flow: one requestAnimationFrame loop, two
  // setPaintProperty calls per frame (drive + walk), regardless of how many
  // legs/days are on screen — never one loop per segment.
  useEffect(() => {
    const map = mapRef.current
    if (!map || status !== 'ready' || variant !== 'workspace' || window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return
    let frame = 0
    let start = 0
    const tick = (time: number) => {
      if (!start) start = time
      const elapsed = time - start
      for (const id of ANIMATED_LAYERS) {
        if (map.getLayer(id)) {
          const { dash, gap, cycleMs } = FLOW[id]
          map.setPaintProperty(id, 'line-dasharray', animatedDash(dash, gap, cycleMs, elapsed))
        }
      }
      frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [status, styleVersion, variant, mapRef])

  useEffect(() => {
    const map = mapRef.current
    badgeRegistry.current.forEach((marker) => marker.remove()); badgeRegistry.current = []
    if (!map || status !== 'ready' || variant !== 'hotels') return
    if (!map.getSource(RAY_SOURCE)) map.addSource(RAY_SOURCE, { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
    if (!map.getLayer(RAY_LAYER)) map.addLayer({ id: RAY_LAYER, type: 'line', source: RAY_SOURCE, paint: { 'line-color': '#0e1319', 'line-width': 1.6, 'line-opacity': .45, 'line-dasharray': [3, 7] } })
    if (!map.getSource(HALO_SOURCE)) map.addSource(HALO_SOURCE, { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
    if (!map.getLayer(HALO_LAYER)) map.addLayer({ id: HALO_LAYER, type: 'circle', source: HALO_SOURCE, paint: { 'circle-radius': 26, 'circle-color': '#0e1319', 'circle-opacity': .07, 'circle-stroke-color': '#0e1319', 'circle-stroke-width': 1.4, 'circle-stroke-opacity': .5 } })
    const selected = selectedId ? markers.find((marker) => marker.syncId === selectedId) : undefined
    const origin = selected ? parseCoordinates(selected.coordinates) : null
    const raySource = map.getSource(RAY_SOURCE) as mapboxgl.GeoJSONSource
    const haloSource = map.getSource(HALO_SOURCE) as mapboxgl.GeoJSONSource
    if (!origin) { raySource.setData({ type: 'FeatureCollection', features: [] }); haloSource.setData({ type: 'FeatureCollection', features: [] }); return }
    raySource.setData({ type: 'FeatureCollection', features: hotelRays.map((ray) => ({ type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: [toLngLat(origin), toLngLat(ray.coordinates)] } })) })
    haloSource.setData({ type: 'FeatureCollection', features: [{ type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: toLngLat(origin) } }] })
    badgeRegistry.current = hotelRays.map((ray) => {
      const el = document.createElement('div')
      el.textContent = `${ray.name} · ${new Intl.NumberFormat('vi-VN', { maximumFractionDigits: 1 }).format(ray.distanceKm)} km`
      el.style.cssText = "white-space:nowrap;padding:2px 8px;border-radius:99px;background:rgba(255,255,255,.85);border:1px solid var(--edge);box-shadow:0 4px 10px -6px rgb(var(--shadow-rgb) / .6);font:400 10px/1.3 'Be Vietnam Pro',sans-serif;color:var(--t1)"
      return new mapboxgl.Marker({ element: el, anchor: 'center' }).setLngLat([(origin.lng + ray.coordinates.lng) / 2, (origin.lat + ray.coordinates.lat) / 2]).addTo(map)
    })
  }, [hotelRays, markerKey, markers, selectedId, status, styleVersion, variant, mapRef])

  const validMarker = markers.some((marker) => parseCoordinates(marker.coordinates) != null)
  const hasGeolocation = typeof navigator !== 'undefined' && 'geolocation' in navigator
  return <div className="relative h-full w-full overflow-hidden rounded-[26px] border border-edge" style={{ boxShadow: '0 20px 50px -26px rgb(var(--shadow-rgb) / .3)' }}>
    {tokenMissing ? <MapStateOverlay icon="map" title={t('mapUnavailableTitle')} body={t('mapUnavailableBody')} /> : <>
      <div ref={containerRef} className="h-full w-full" />
      {status === 'error' && <MapStateOverlay icon="error" title={t('mapErrorTitle')} body={t('mapErrorBody')} action={{ label: t('mapRetryLabel'), onClick: retry }} />}
      {status === 'loading' && <div className="absolute inset-0 shimmer-block" aria-hidden="true" />}
      {status === 'ready' && !validMarker && <MapStateOverlay icon="location_off" title={t('mapEmptyTitle')} body={t('mapEmptyBody')} />}
      {status === 'ready' && validMarker && <>
        <MapControls styleKind={styleKind} onZoomIn={() => mapRef.current?.zoomIn()} onZoomOut={() => mapRef.current?.zoomOut()} onFitRoute={() => { const points = markers.map((marker) => parseCoordinates(marker.coordinates)).filter((point): point is NonNullable<typeof point> => point != null); fitWorkspace(mapRef.current!, points) }} onLocate={hasGeolocation ? () => navigator.geolocation.getCurrentPosition((position) => mapRef.current?.flyTo({ center: [position.coords.longitude, position.coords.latitude], zoom: 14, duration: 600 })) : undefined} onToggleStyle={() => setStyleKind((kind) => kind === 'satellite' ? 'map' : 'satellite')} className="absolute right-4 top-4 z-10" />
      </>}
    </>}
  </div>
}
