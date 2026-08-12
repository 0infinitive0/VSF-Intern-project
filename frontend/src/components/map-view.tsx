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
// white moving bar on top. Walk has no casing (spec §2.2) — a colored line
// with white dots marching along it. Both moving overlays are gradient
// layers, see travelGradient below. Add order == z-order (casing at the
// bottom, the two moving overlays on top so nothing paints over them).
const DRIVE_CASING_LAYER = 'route-drive-casing'
const DRIVE_LAYER = 'route-drive'
const WALK_LAYER = 'route-walk'
const FALLBACK_LAYER = 'route-fallback'
const DRIVE_FLOW_LAYER = 'route-drive-flow'
const WALK_FLOW_LAYER = 'route-walk-flow'
const ROUTE_LAYER_IDS = [DRIVE_CASING_LAYER, DRIVE_LAYER, WALK_LAYER, FALLBACK_LAYER, DRIVE_FLOW_LAYER, WALK_FLOW_LAYER] as const
const RAY_LAYER = 'hotel-distance-rays-line'
const HALO_LAYER = 'hotel-selection-halo-circle'

// Fade-in duration for opacity changes (hover/dim) — NOT the entrance cue
// anymore, see startDrawIn() below for that.
const ROUTE_FADE_MS = 400

// Fallback's static dash, in Mapbox's dasharray unit (multiples of the
// layer's own line-width): sparse and faint so an estimated straight line
// never passes for navigated data. It's the only dashed layer left — the
// walking "dots" are now drawn by a gradient instead (see travelGradient),
// because a dasharray fundamentally cannot animate smoothly.
const FALLBACK_DASH: [number, number] = [0.6, 1.8]

// Per-layer rest width/opacity/color, one row per role in
// map_line_animation_effects.md §2: casing (white glow beneath drive),
// main (drive/walk/fallback's own colored line), flow (white pulse on top
// of drive only). opacityFn/widthFn wire each layer to the right hover/dim
// behavior (see mainOpacity/mainWidth/accentOpacity below) — casing/flow
// never brighten on hover per the spec's dimming snippet, only main lines do.
type PaintExpr = mapboxgl.DataDrivenPropertyValueSpecification<number>
const LAYER_STYLE: Record<
  string,
  {
    width: number
    opacity: number
    color: mapboxgl.DataDrivenPropertyValueSpecification<string>
    opacityFn: (rest: number) => PaintExpr
    widthFn?: (rest: number) => PaintExpr
    dash?: [number, number]
    /** Colored by an animated line-gradient instead of a flat line-color (see travelGradient). */
    pulse?: PulseKind
  }
> = {
  [DRIVE_CASING_LAYER]: { width: 7, opacity: 0.75, color: '#fff', opacityFn: accentOpacityExpr, widthFn: mainWidthExpr },
  [DRIVE_LAYER]: { width: 4, opacity: 0.92, color: ['get', 'color'], opacityFn: mainOpacityExpr, widthFn: mainWidthExpr },
  [WALK_LAYER]: { width: 4.5, opacity: 0.92, color: ['get', 'color'], opacityFn: mainOpacityExpr, widthFn: mainWidthExpr },
  [FALLBACK_LAYER]: { width: 3, opacity: 0.45, color: ['get', 'color'], opacityFn: mainOpacityExpr, widthFn: mainWidthExpr, dash: FALLBACK_DASH },
  // The two moving overlays, both at the spec's full 0.95 — they're meant to
  // read as a bright white highlight travelling along the leg, so anything
  // dimmer just disappears against the colored line underneath.
  [DRIVE_FLOW_LAYER]: { width: 3, opacity: 0.95, color: '#fff', opacityFn: accentOpacityExpr, pulse: 'bar' },
  [WALK_FLOW_LAYER]: { width: 2.6, opacity: 0.95, color: '#fff', opacityFn: accentOpacityExpr, pulse: 'dots' },
}

/**
 * Direction-of-travel motion (map_line_animation_effects.md §2): a bright
 * white bar sweeping each drive leg, and white dots marching along each walk
 * leg.
 *
 * Both are animated `line-gradient`s, NOT scrolling `line-dasharray`s, and
 * that choice is the whole reason they can run at display rate. A dasharray
 * pattern is baked into a texture atlas by the WORKER during tile parse
 * (LineBucket.populate -> addConstantDashes); the draw call only ever looks
 * the baked pattern up (LineAtlas.getDash returns this.positions[key], it
 * never adds one). So every new dasharray value has to wait on a tile
 * re-parse round-trip before it can show — which caps the effective frame
 * rate no matter how often setPaintProperty is called, and is exactly why
 * the earlier scrolling-dash version looked like ~30fps. A line-gradient is
 * instead rasterized into a small ramp texture on the MAIN thread inside the
 * render pass (keyed by gradientVersion), so rewriting it every frame is
 * cheap and lands in that same frame.
 *
 * That's also why walking lost its dashed line-dasharray: the dots ARE the
 * gradient now, which is the only way they can move smoothly.
 *
 * Trade-off worth knowing: `line-progress` is normalized per FEATURE, so a
 * leg's motion is timed and sized relative to that leg, not in absolute
 * pixels — every leg completes a cycle together regardless of length. It
 * reads as "this is the direction you travel" rather than as one continuous
 * stream flowing down the whole route like the Leaflet original.
 */
type PulseKind = 'bar' | 'dots'

/** One sweep of the drive bar from before a leg's start to past its end. */
const BAR_CYCLE_MS = 3_400
/** Half-extent of the bar's soft edge, and of its solid core, as a fraction of leg length. */
const BAR_HALF_WIDTH = 0.075
const BAR_CORE_HALF_WIDTH = 0.028

/** Time for the walking dots to advance by exactly one dot spacing (so the loop is seamless). */
const DOTS_CYCLE_MS = 1_600
const DOTS_PER_LEG = 13
const DOT_HALF_WIDTH = 0.013

const PULSE_CLEAR = 'rgba(255,255,255,0)'
const PULSE_CORE = 'rgba(255,255,255,1)'

/**
 * Builds a line-progress gradient from a caller-supplied set of stops.
 *
 * `interpolate` demands strictly increasing stops, but stops get clamped
 * into [0,1] as a shape slides off either end of the leg and would then
 * collide with their predecessor. Each stop is therefore nudged just past
 * the previous one rather than dropped, which keeps the expression valid at
 * every phase without special-casing the ends.
 */
function buildGradient(addStops: (push: (at: number, color: string) => void) => void): mapboxgl.ExpressionSpecification {
  const stops: Array<number | string> = []
  let last = -1
  const push = (at: number, color: string) => {
    let value = Math.min(1, Math.max(0, at))
    if (value <= last) value = last + 1e-4
    if (value > 1) return
    last = value
    stops.push(value, color)
  }
  addStops(push)
  return ['interpolate', ['linear'], ['line-progress'], ...stops] as mapboxgl.ExpressionSpecification
}

/**
 * `phase` runs 0->1 over one cycle for both kinds.
 *
 * bar:  one solid-cored bar travelling the leg, entering and leaving past
 *       the ends so it never pops into existence mid-line.
 * dots: an evenly spaced train of dots shifted by one whole spacing per
 *       cycle — at phase 1 each dot has taken its neighbour's place, so the
 *       loop is seamless. The -1/+1 iterations are the dots half in and half
 *       out at the two ends.
 */
function travelGradient(kind: PulseKind, phase: number): mapboxgl.ExpressionSpecification {
  if (kind === 'bar') {
    const center = phase * (1 + 2 * BAR_HALF_WIDTH) - BAR_HALF_WIDTH
    return buildGradient((push) => {
      push(0, PULSE_CLEAR)
      push(center - BAR_HALF_WIDTH, PULSE_CLEAR)
      push(center - BAR_CORE_HALF_WIDTH, PULSE_CORE)
      push(center + BAR_CORE_HALF_WIDTH, PULSE_CORE)
      push(center + BAR_HALF_WIDTH, PULSE_CLEAR)
      push(1, PULSE_CLEAR)
    })
  }
  return buildGradient((push) => {
    push(0, PULSE_CLEAR)
    for (let index = -1; index <= DOTS_PER_LEG; index++) {
      const center = (index + phase) / DOTS_PER_LEG
      if (center + DOT_HALF_WIDTH < 0 || center - DOT_HALF_WIDTH > 1) continue
      push(center - DOT_HALF_WIDTH, PULSE_CLEAR)
      push(center, PULSE_CORE)
      push(center + DOT_HALF_WIDTH, PULSE_CLEAR)
    }
    push(1, PULSE_CLEAR)
  })
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
    [WALK_FLOW_LAYER, walkFilter],
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
        'line-opacity': style.opacityFn(style.opacity),
        'line-width': style.widthFn ? style.widthFn(style.width) : style.width,
        // Fully hidden ([trim_start, trim_end] = [0,1] covers the whole
        // line — see startDrawIn's doc comment) until startDrawIn reveals it.
        'line-trim-offset': [0, 1],
        // line-gradient replaces line-color outright, so a moving overlay
        // sets one or the other, never both.
        ...(style.pulse ? { 'line-gradient': travelGradient(style.pulse, 0) } : { 'line-color': style.color }),
        ...(style.dash ? { 'line-dasharray': style.dash } : {}),
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
// Cost-wise it behaves like line-gradient rather than line-dasharray (see
// travelGradient above): it's two plain uniforms fed to the shader per draw
// call, with no worker round-trip, so tweening it every frame is cheap.
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

  // Double-leg highlight (map_implementation_spec.md §2/§3): picking ONE
  // place lights up BOTH legs touching it — the one arriving at it and the
  // one leaving it — because highlightedRouteKeys matches a segment when
  // the active id is at EITHER endpoint (its fromKey/toKey pair is the
  // spec's `ids: [id_start, id_end]`), never just the arriving one.
  //
  // `hoveredId ?? selectedId` is the spec's `hovered || selected`: a live
  // hover wins, but a click-through selection keeps its two legs lit after
  // the pointer leaves. This mirrors what the marker effect above already
  // does with the same two ids — routes and pins now agree on what "active"
  // means instead of routes tracking hover alone.
  useEffect(() => {
    const map = mapRef.current
    if (!map || status !== 'ready' || variant !== 'workspace' || !map.getSource(ROUTE_SOURCE)) return
    const activeId = hoveredId ?? selectedId
    const activeSegmentKeys = highlightedRouteKeys(segments, activeId, null)
    const active = activeId != null
    for (const segment of segments) map.setFeatureState({ source: ROUTE_SOURCE, id: segment.segKey }, { hovered: activeSegmentKeys.has(segment.segKey), dimmed: active && !activeSegmentKeys.has(segment.segKey) })
  }, [hoveredId, selectedId, segments, status, styleVersion, variant, mapRef])

  // Direction-of-travel motion: ONE requestAnimationFrame loop writing one
  // paint property per moving overlay, regardless of how many legs/days are
  // on screen — never one loop per segment. Runs at display rate with no
  // quantization at all, because line-gradient updates on the main thread
  // (see travelGradient's doc comment for why the earlier
  // scrolling-dasharray version could not).
  useEffect(() => {
    const map = mapRef.current
    if (!map || status !== 'ready' || variant !== 'workspace' || window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return
    let frame = 0
    let start = 0
    const tick = (time: number) => {
      if (!start) start = time
      const elapsed = time - start
      for (const [id, kind, cycleMs] of [
        [DRIVE_FLOW_LAYER, 'bar', BAR_CYCLE_MS],
        [WALK_FLOW_LAYER, 'dots', DOTS_CYCLE_MS],
      ] as const) {
        if (!map.getLayer(id)) continue
        map.setPaintProperty(id, 'line-gradient', travelGradient(kind, (elapsed % cycleMs) / cycleMs))
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
