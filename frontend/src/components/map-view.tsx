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
const CASING_LAYER = 'route-casing'
const DRIVE_LAYER = 'route-drive'
const WALK_LAYER = 'route-walk'
const FALLBACK_LAYER = 'route-fallback'
const FLOW_LAYER = 'route-flow'
const RAY_LAYER = 'hotel-distance-rays-line'
const HALO_LAYER = 'hotel-selection-halo-circle'
// Entrance draw-in duration (map_line_animation_effects.md §1: "0.9 giây").
const ROUTE_FADE_MS = 900
// Dash/gap below are line-width MULTIPLES (mapbox-gl's own dasharray unit,
// same semantics as an SVG stroke-dasharray relative to stroke-width) — so
// each pair is the doc's raw px spec divided by that layer's own
// line-width, reproducing the same on-screen dash/gap length in pixels:
// drive flow (weight 2.4): 14px/2.4=5.83, 120px/2.4=50, 3.4s cycle.
const FLOW_DASH = 5.83
const FLOW_GAP = 50
const FLOW_CYCLE_MS = 3_400
// Walk mode has no casing layer under it (unlike drive), so its dots are
// the ONLY thing carrying the whole leg against a busy street basemap — the
// doc's literal 2px/9px (at width 4) rendered essentially invisibly in
// testing. Sized up while keeping the same "small dot, wide gap" character
// clearly distinct from drive's bold flowing dash, not the doc's raw ratio.
const WALK_DASH = 0.9
const WALK_GAP = 3.2
const WALK_CYCLE_MS = 1_600
const WALK_WIDTH = 5
const DASH_EPSILON = 0.01

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

// map_line_animation_effects.md §3: the "main" colored line for a leg (drive/
// walk/fallback) brightens to full opacity on hover; a "casing"/"flow"
// overlay never brightens on hover (only its width does, for casing) — it
// only reacts to `dimmed`. Two expression shapes instead of one shared
// 3-tier case, matching that split exactly.
function mainOpacity(rest: number, dimmed: number): mapboxgl.DataDrivenPropertyValueSpecification<number> {
  return ['case', ['boolean', ['feature-state', 'hovered'], false], 1, ['boolean', ['feature-state', 'dimmed'], false], dimmed, rest]
}
function accentOpacity(rest: number, dimmed: number): mapboxgl.DataDrivenPropertyValueSpecification<number> {
  return ['case', ['boolean', ['feature-state', 'dimmed'], false], dimmed, rest]
}
// "weight + 2" on the active leg (§3) — casing and the main-color line both
// get this; the flow overlay's width stays constant (doc never widens it).
function hoverWidth(rest: number): mapboxgl.DataDrivenPropertyValueSpecification<number> {
  return ['case', ['boolean', ['feature-state', 'hovered'], false], rest + 2, rest]
}

function addRouteLayers(map: mapboxgl.Map) {
  map.addSource(ROUTE_SOURCE, { type: 'geojson', lineMetrics: true, data: { type: 'FeatureCollection', features: [] } })
  const layout: mapboxgl.LineLayerSpecification['layout'] = { 'line-cap': 'round', 'line-join': 'round' }
  const realRouteFilter = ['==', ['get', 'isFallback'], false]
  const walkFilter = ['all', realRouteFilter, ['==', ['get', 'profile'], 'walking']]
  const driveFilter = ['all', realRouteFilter, ['!=', ['get', 'profile'], 'walking']]
  // The trim interval is rendered transparent. Start at [0, 1] (fully
  // hidden) and animate to [0, 0] (fully visible), matching SVG draw-in —
  // applied to every semantic line layer (casing/drive/walk/fallback) so a
  // tab/day change always "draws" the whole route, not just driving legs.
  // The flow overlay is deliberately excluded: it's already animating its
  // own dash, trimming it too would read as two motions fighting each other.
  const opacityTransition = { 'line-opacity-transition': { duration: ROUTE_FADE_MS, delay: 0 } }
  const trimProps = { ...opacityTransition, 'line-trim-offset-transition': { duration: ROUTE_FADE_MS, delay: 0 }, 'line-trim-color': 'rgba(0,0,0,0)' as const, 'line-trim-offset': [0, 1] as [number, number] }
  map.addLayer({ id: CASING_LAYER, type: 'line', source: ROUTE_SOURCE, filter: driveFilter, layout, paint: { ...trimProps, 'line-color': '#fff', 'line-opacity': accentOpacity(.75, .1), 'line-width': hoverWidth(7) } } as mapboxgl.LineLayerSpecification)
  map.addLayer({ id: DRIVE_LAYER, type: 'line', source: ROUTE_SOURCE, filter: driveFilter, layout, paint: { ...trimProps, 'line-color': ['get', 'color'], 'line-opacity': mainOpacity(.92, .18), 'line-width': hoverWidth(4) } } as mapboxgl.LineLayerSpecification)
  map.addLayer({ id: WALK_LAYER, type: 'line', source: ROUTE_SOURCE, filter: walkFilter, layout, paint: { ...trimProps, 'line-color': ['get', 'color'], 'line-dasharray': [WALK_DASH, WALK_GAP], 'line-opacity': mainOpacity(.95, .18), 'line-width': hoverWidth(WALK_WIDTH) } } as mapboxgl.LineLayerSpecification)
  map.addLayer({ id: FALLBACK_LAYER, type: 'line', source: ROUTE_SOURCE, filter: ['==', ['get', 'isFallback'], true], layout, paint: { ...trimProps, 'line-color': ['get', 'color'], 'line-dasharray': [.6, 1.8], 'line-opacity': mainOpacity(.5, .18), 'line-width': hoverWidth(3) } } as mapboxgl.LineLayerSpecification)
  map.addLayer({ id: FLOW_LAYER, type: 'line', source: ROUTE_SOURCE, filter: driveFilter, layout, paint: { ...opacityTransition, 'line-color': '#fff', 'line-dasharray': [FLOW_DASH, FLOW_GAP], 'line-opacity': accentOpacity(.95, .1), 'line-width': 2.4 } } as mapboxgl.LineLayerSpecification)
}

function setRouteTrimEnd(map: mapboxgl.Map, trimEnd: number) {
  const trimLayers = [CASING_LAYER, DRIVE_LAYER, WALK_LAYER, FALLBACK_LAYER] as const
  for (const id of trimLayers) if (map.getLayer(id)) map.setPaintProperty(id, 'line-trim-offset', [0, trimEnd])
}

function animatedDash(dash: number, gap: number, cycleMs: number, elapsedMs: number): [number, number, number, number] {
  const offset = ((elapsedMs % cycleMs) / cycleMs) * (dash + gap)
  // Mapbox GL requires every dash-array entry to be positive. A literal zero
  // makes the whole layer disappear in some renderers, so an imperceptible
  // leading dash preserves the phase shift without ever invalidating the line.
  return offset < dash
    ? [Math.max(DASH_EPSILON, dash - offset), gap, dash, gap]
    : [DASH_EPSILON, Math.max(DASH_EPSILON, dash + gap - offset), dash, gap]
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

  useEffect(() => {
    const map = mapRef.current
    if (!map || status !== 'ready' || variant !== 'workspace') return
    if (!map.getSource(ROUTE_SOURCE)) addRouteLayers(map)
    const source = map.getSource(ROUTE_SOURCE) as mapboxgl.GeoJSONSource
    source.setData(routeData(segments) as never)
    setRouteTrimEnd(map, 1)
    const frame = requestAnimationFrame(() => setRouteTrimEnd(map, 0))
    return () => cancelAnimationFrame(frame)
  }, [segments, status, styleVersion, variant, mapRef])

  useEffect(() => {
    const map = mapRef.current
    if (!map || status !== 'ready' || variant !== 'workspace' || !map.getSource(ROUTE_SOURCE)) return
    const activeSegmentKeys = highlightedRouteKeys(segments, hoveredId, null)
    const active = hoveredId != null
    for (const segment of segments) map.setFeatureState({ source: ROUTE_SOURCE, id: segment.segKey }, { hovered: activeSegmentKeys.has(segment.segKey), dimmed: active && !activeSegmentKeys.has(segment.segKey) })
  }, [hoveredId, segments, status, styleVersion, variant, mapRef])

  useEffect(() => {
    const map = mapRef.current
    if (!map || status !== 'ready' || variant !== 'workspace' || window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return
    let frame = 0; let start = 0
    const tick = (time: number) => {
      if (!start) start = time
      const elapsed = time - start
      if (map.getLayer(FLOW_LAYER)) map.setPaintProperty(FLOW_LAYER, 'line-dasharray', animatedDash(FLOW_DASH, FLOW_GAP, FLOW_CYCLE_MS, elapsed))
      if (map.getLayer(WALK_LAYER)) map.setPaintProperty(WALK_LAYER, 'line-dasharray', animatedDash(WALK_DASH, WALK_GAP, WALK_CYCLE_MS, elapsed))
      frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick); return () => cancelAnimationFrame(frame)
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
