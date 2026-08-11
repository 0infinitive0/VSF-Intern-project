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
// Drive is 3 stacked layers at the same coordinates (map_line_animation_effects.md
// §2.1): a white casing underneath, the per-leg-colored main line, and a
// white "flow" pulse on top. Walk is a single dotted line (no casing). Both
// z-order (add order, casing first = bottom) and filter come from this list.
const DRIVE_CASING_LAYER = 'route-drive-casing'
const DRIVE_LAYER = 'route-drive'
const WALK_LAYER = 'route-walk'
const FALLBACK_LAYER = 'route-fallback'
const DRIVE_FLOW_LAYER = 'route-drive-flow'
const ROUTE_LAYER_IDS = [DRIVE_CASING_LAYER, DRIVE_LAYER, WALK_LAYER, FALLBACK_LAYER, DRIVE_FLOW_LAYER] as const
// Only the flow overlay and the walk line carry motion — fallback is an
// honest straight-line estimate, not a real route, and never gets the
// "flowing" treatment that would make it look like real navigated data;
// the casing/main drive lines are solid (the flow layer on top is what
// reads as "moving"), so they don't need a dasharray at all.
const ANIMATED_LAYERS = [DRIVE_FLOW_LAYER, WALK_LAYER] as const
const RAY_LAYER = 'hotel-distance-rays-line'
const HALO_LAYER = 'hotel-selection-halo-circle'

// Fade-in duration for opacity changes (hover/dim) — NOT the entrance cue
// anymore, see startDrawIn() below for that.
const ROUTE_FADE_MS = 400

// Mapbox GL requires every line-dasharray entry to be positive — a literal
// 0 (rather than a very small gap) makes the WHOLE layer disappear in some
// renderers. Only used inside animatedDash() below; the solid layers
// (casing/drive/fallback) don't set line-dasharray at all anymore, so they
// can't hit this.
const DASH_EPSILON = 0.01

// Per-layer rest width/opacity/color, one row per role in
// map_line_animation_effects.md §2: casing (white glow beneath drive),
// main (drive/walk/fallback's own colored line), flow (white pulse on top
// of drive only). opacityFn/widthFn wire each layer to the right hover/dim
// behavior (see mainOpacity/mainWidth/accentOpacity below) — casing/flow
// never brighten on hover per the spec's dimming snippet, only main lines do.
type PaintExpr = mapboxgl.DataDrivenPropertyValueSpecification<number>
const LAYER_STYLE: Record<
  string,
  { width: number; opacity: number; color: mapboxgl.DataDrivenPropertyValueSpecification<string>; opacityFn: (rest: number) => PaintExpr; widthFn?: (rest: number) => PaintExpr }
> = {
  [DRIVE_CASING_LAYER]: { width: 7, opacity: 0.75, color: '#fff', opacityFn: accentOpacityExpr, widthFn: mainWidthExpr },
  [DRIVE_LAYER]: { width: 4, opacity: 0.92, color: ['get', 'color'], opacityFn: mainOpacityExpr, widthFn: mainWidthExpr },
  [WALK_LAYER]: { width: 5, opacity: 0.9, color: ['get', 'color'], opacityFn: mainOpacityExpr, widthFn: mainWidthExpr },
  [FALLBACK_LAYER]: { width: 3, opacity: 0.45, color: ['get', 'color'], opacityFn: mainOpacityExpr, widthFn: mainWidthExpr },
  [DRIVE_FLOW_LAYER]: { width: 2.4, opacity: 0.95, color: '#fff', opacityFn: accentOpacityExpr },
}

// Direction-of-travel dash animation — one shared mechanism for both
// animated layers (§9 of the earlier animation spec: never one animation
// loop per segment/leg, one mechanism for the whole route regardless of how
// many legs/days are in it). Values are map_line_animation_effects.md §2's
// raw px/timing converted to Mapbox's dasharray unit (multiples of the
// layer's own line-width): drive flow is 14px dash / 120px gap at weight
// 2.4px -> 14/2.4=5.83, 120/2.4=50, 3.4s cycle, matching the spec exactly.
// Walk's raw spec value (2px/9px at width 4) rendered essentially
// invisibly in testing, so it's sized up here (width 5, 0.9/3.2) while
// keeping the same "small dot, wide gap" character and the spec's 1.6s cycle.
const FLOW: Record<string, { dash: number; gap: number; cycleMs: number }> = {
  [DRIVE_FLOW_LAYER]: { dash: 14 / 2.4, gap: 120 / 2.4, cycleMs: 3400 },
  [WALK_LAYER]: { dash: 0.9, gap: 3.2, cycleMs: 1600 },
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

// Hover/dim highlight (map_line_animation_effects.md §3): the leg related
// to whatever's hovered brightens to full opacity + a bit wider; every
// OTHER leg dims — but not uniformly. Only "main" lines (drive/walk/
// fallback's own colored line) ever brighten to 1 on hover; "accent" roles
// (casing, flow) never brighten, they only ever dim — exactly the split in
// the spec's dimming snippet:
//   r.line.setStyle({opacity: dim?.18:(rel?1:r.o), weight: rel?r.w+2:r.w})
//   r.casing.setStyle({opacity: dim?.1:.75, weight: rel?9:7})
//   r.flow.setStyle({opacity: dim?.1:.95})
const HOVERED = ['boolean', ['feature-state', 'hovered'], false]
const DIMMED = ['boolean', ['feature-state', 'dimmed'], false]

function mainOpacityExpr(rest: number): PaintExpr {
  return ['case', HOVERED, 1, DIMMED, 0.18, rest]
}
function mainWidthExpr(rest: number): PaintExpr {
  return ['case', HOVERED, rest + 2, rest]
}
/** Casing/flow: dims like a main line, but never brightens past `rest` on hover — a leg's own glow/pulse doesn't change, only its neighbors dim. */
function accentOpacityExpr(rest: number): PaintExpr {
  return ['case', DIMMED, 0.1, rest]
}

function addRouteLayers(map: mapboxgl.Map) {
  // lineMetrics precomputes normalized distance-along-line per vertex,
  // required for line-trim-offset — the entrance draw-in, see startDrawIn.
  map.addSource(ROUTE_SOURCE, { type: 'geojson', lineMetrics: true, data: { type: 'FeatureCollection', features: [] } })
  const layout: mapboxgl.LineLayerSpecification['layout'] = { 'line-cap': 'round', 'line-join': 'round' }
  const realRouteFilter = ['==', ['get', 'isFallback'], false]
  const walkFilter = ['all', realRouteFilter, ['==', ['get', 'profile'], 'walking']]
  const driveFilter = ['all', realRouteFilter, ['!=', ['get', 'profile'], 'walking']]
  const fadeIn = { 'line-opacity-transition': { duration: ROUTE_FADE_MS, delay: 0 } }

  for (const [id, filter] of [
    [DRIVE_CASING_LAYER, driveFilter],
    [DRIVE_LAYER, driveFilter],
    [WALK_LAYER, walkFilter],
    [FALLBACK_LAYER, ['==', ['get', 'isFallback'], true]],
    [DRIVE_FLOW_LAYER, driveFilter],
  ] as const) {
    const style = LAYER_STYLE[id]
    const flow = FLOW[id]
    // Only the 2 animated layers get a dasharray from animatedDash (frame 0
    // — a safe, already-quantized pattern, see FLOW_STEPS above); fallback
    // keeps its own static dashed look; casing/drive stay solid (no key).
    const dash: [number, number, number, number] | [number, number] | undefined = flow
      ? animatedDash(flow.dash, flow.gap, flow.cycleMs, 0)
      : id === FALLBACK_LAYER
        ? [0.6, 1.8]
        : undefined
    map.addLayer({
      id,
      type: 'line',
      source: ROUTE_SOURCE,
      filter,
      layout,
      paint: {
        ...fadeIn,
        'line-color': style.color,
        'line-opacity': style.opacityFn(style.opacity),
        'line-width': style.widthFn ? style.widthFn(style.width) : style.width,
        // Fully hidden ([trim_start, trim_end] = [0,1] covers the whole
        // line — see startDrawIn's doc comment) until startDrawIn reveals it.
        'line-trim-offset': [0, 1],
        ...(dash ? { 'line-dasharray': dash } : {}),
      },
    } as mapboxgl.LineLayerSpecification)
  }
}

// Entrance draw-in (map_line_animation_effects.md §1: "kéo rút dây" — the
// route draws from start to end like a pen, 0.9s, cubic-bezier(.22,1,.36,1)).
// Mapbox's equivalent of SVG stroke-dashoffset is `line-trim-offset`: the
// [trim_start, trim_end] interval is the HIDDEN portion of the line
// (confirmed by reading mapbox-gl's own shader source: `trim_alpha = 1 -
// transition_factor`, and transition_factor peaks INSIDE that interval) —
// so with trim_end pinned at 1 and trim_start animating 0 -> 1, the hidden
// region shrinks from the whole line down to nothing, revealing
// start-to-end. Animating the other way (trim_end 1 -> 0, trim_start fixed
// at 0) reveals end-to-start instead — easy to get backwards, hence this
// comment.
//
// `line-trim-offset` does NOT support the automatic `-transition` paint
// property (mapbox-gl 3.28.1's style-spec has no
// "line-trim-offset-transition" entry — setting one is silently ignored),
// so unlike line-opacity above this needs a manual requestAnimationFrame
// tween instead of a paint transition.
//
// Also, unlike line-dasharray (see the LineAtlas doc on FLOW_STEPS above),
// line-trim-offset is NOT texture/atlas-backed — it's two floats fed
// straight into the shader per draw call via line-progress, no shared
// cache to exhaust. Animating it continuously every frame is safe.
const DRAW_IN_MS = 900

/** Numeric solver for a CSS-style cubic-bezier(x1,y1,x2,y2) easing curve — Newton-Raphson on the bezier's own parametric t, the same evaluation browsers use for `cubic-bezier()`. */
function makeCubicBezierEase(x1: number, y1: number, x2: number, y2: number): (x: number) => number {
  const sampleX = (t: number) => 3 * (1 - t) ** 2 * t * x1 + 3 * (1 - t) * t * t * x2 + t ** 3
  const sampleY = (t: number) => 3 * (1 - t) ** 2 * t * y1 + 3 * (1 - t) * t * t * y2 + t ** 3
  const sampleDX = (t: number) => 3 * (1 - t) ** 2 * x1 + 6 * (1 - t) * t * (x2 - x1) + 3 * t * t * (1 - x2)
  return (x: number) => {
    let t = x
    for (let i = 0; i < 8; i++) {
      const err = sampleX(t) - x
      if (Math.abs(err) < 1e-6) break
      const d = sampleDX(t)
      if (Math.abs(d) < 1e-6) break
      t -= err / d
    }
    return sampleY(t)
  }
}
const drawInEase = makeCubicBezierEase(0.22, 1, 0.36, 1)

/**
 * Reveals every route layer start-to-end over DRAW_IN_MS — the "just
 * appeared" cue for a tab/day change or initial load. Returns a cleanup
 * that cancels the in-flight tween; the caller (the segments effect below)
 * returns it directly so React cancels a stale tween itself whenever
 * segments change again mid-animation or the component unmounts, instead
 * of a hand-rolled ref.
 */
function startDrawIn(map: mapboxgl.Map): () => void {
  if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) {
    for (const id of ROUTE_LAYER_IDS) if (map.getLayer(id)) map.setPaintProperty(id, 'line-trim-offset', [0, 0])
    return () => {}
  }
  for (const id of ROUTE_LAYER_IDS) if (map.getLayer(id)) map.setPaintProperty(id, 'line-trim-offset', [0, 1])
  let frame = 0
  let start = 0
  const tick = (time: number) => {
    if (!start) start = time
    const t = Math.min(1, (time - start) / DRAW_IN_MS)
    const trimStart = drawInEase(t)
    for (const id of ROUTE_LAYER_IDS) if (map.getLayer(id)) map.setPaintProperty(id, 'line-trim-offset', t < 1 ? [trimStart, 1] : [0, 0])
    if (t < 1) frame = requestAnimationFrame(tick)
  }
  frame = requestAnimationFrame(tick)
  return () => cancelAnimationFrame(frame)
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
  // segments change (tab/day switch, hotel rotation), followed by the
  // start-to-end draw-in (see startDrawIn's doc comment) so a route swap
  // always reads as "just drawn" rather than an abrupt cut. Returning
  // startDrawIn's cancel fn lets React's own effect-cleanup cancel a
  // still-running tween if segments change again mid-animation (fast
  // tab/day switching) or the component unmounts.
  useEffect(() => {
    const map = mapRef.current
    if (!map || status !== 'ready' || variant !== 'workspace') return
    if (!map.getSource(ROUTE_SOURCE)) addRouteLayers(map)
    const source = map.getSource(ROUTE_SOURCE) as mapboxgl.GeoJSONSource
    source.setData(routeData(segments) as never)
    return startDrawIn(map)
  }, [segments, status, styleVersion, variant, mapRef])

  useEffect(() => {
    const map = mapRef.current
    if (!map || status !== 'ready' || variant !== 'workspace' || !map.getSource(ROUTE_SOURCE)) return
    const activeSegmentKeys = highlightedRouteKeys(segments, hoveredId, null)
    const active = hoveredId != null
    for (const segment of segments) map.setFeatureState({ source: ROUTE_SOURCE, id: segment.segKey }, { hovered: activeSegmentKeys.has(segment.segKey), dimmed: active && !activeSegmentKeys.has(segment.segKey) })
  }, [hoveredId, segments, status, styleVersion, variant, mapRef])

  // Direction-of-travel flow: one requestAnimationFrame loop, two
  // setPaintProperty calls per frame (drive's flow overlay + walk's own
  // line — ANIMATED_LAYERS), regardless of how many legs/days are on
  // screen — never one loop per segment. Quantized via FLOW_STEPS (see its
  // doc comment above addRouteLayers) so this never floods LineAtlas.
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
