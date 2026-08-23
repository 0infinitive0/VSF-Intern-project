import { useEffect, useMemo, useRef, useState } from 'react'
import mapboxgl from 'mapbox-gl'
import { useTranslation } from 'react-i18next'
import { useMapboxMap } from '../hooks/use-mapbox-map'
import { boundsOf, parseCoordinates, toLngLat } from '../lib/geo'
import { LEG_COLORS, dayColor, legColor } from '../lib/map-colors'
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
// Drive is 2 stacked layers at the same coordinates: a white casing
// underneath, and the per-leg-colored main line with a small train of white
// bars travelling on top of it (both the casing and the bars are part of
// DRIVE_CASING_LAYER/DRIVE_LAYER's own paint — see travelGradient). Walk has
// no casing and no separate colored base line either — the marching dots
// ARE the whole visual for a walking leg, not an overlay on top of a solid
// line underneath. Add order == z-order (casing at the bottom, drive's
// moving bars painted via its own line-gradient on top of that).
const DRIVE_CASING_LAYER = 'route-drive-casing'
const DRIVE_LAYER = 'route-drive'
const FALLBACK_LAYER = 'route-fallback'
const DRIVE_FLOW_LAYER = 'route-drive-flow'
// One walk layer PER color in the shared route palette (LEG_COLORS is the
// superset — DAY_COLORS is its first 4 entries verbatim, see map-colors.ts),
// each filtered to just the segments carrying that color — see LAYER_STYLE
// and addRouteLayers below for why: line-gradient (what draws the walking
// dots) is a per-LAYER Mapbox paint property, not data-driven per-feature
// like line-color, so one shared layer can't paint each leg's dots in that
// leg's own day/leg color. Splitting into one small (6, bounded, fixed)
// layer per possible color is the workaround.
const WALK_LAYER_IDS = LEG_COLORS.map((_, i) => `route-walk-${i}`)
const ROUTE_LAYER_IDS = [DRIVE_CASING_LAYER, DRIVE_LAYER, ...WALK_LAYER_IDS, FALLBACK_LAYER, DRIVE_FLOW_LAYER] as const
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

// Per-layer rest width/opacity/color, one row per role: casing (white glow
// beneath drive), main (drive/walk/fallback's own colored line), flow
// (white marching-dash overlay on top of drive/walk). opacityFn/widthFn wire
// each layer to the right hover/dim behavior (see mainOpacity/mainWidth/
// accentOpacity below) — casing/flow never brighten on hover, only main
// lines do (matches the design's dimming formula, see the hover/dim effect
// below for the exact numbers).
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
    /** Colored by an animated line-gradient instead of a flat line-color (see travelGradient) — `color` here is the mark color, NOT the same as the row's own `color` field, which line-gradient replaces outright and so goes unused. */
    pulse?: { count: number; halfWidth: number; color: string; capFraction?: number }
  }
> = {
  [DRIVE_CASING_LAYER]: { width: 7, opacity: 0.75, color: '#fff', opacityFn: accentOpacityExpr, widthFn: mainWidthExpr },
  [DRIVE_LAYER]: { width: 4, opacity: 0.92, color: ['get', 'color'], opacityFn: mainOpacityExpr, widthFn: mainWidthExpr },
  [FALLBACK_LAYER]: { width: 3, opacity: 0.45, color: ['get', 'color'], opacityFn: mainOpacityExpr, widthFn: mainWidthExpr, dash: FALLBACK_DASH },
  // Drive's moving overlay, at the spec's full 0.95 opacity: just a couple
  // of long white BARS travelling the leg ("thanh ngang trắng di chuyển
  // trên đường line" — a small, clearly countable number of separate
  // rectangular bars, not a dense pattern). Real gaps between bars, so the
  // colored line underneath — and its hover brighten/widen — stays visible
  // in between.
  [DRIVE_FLOW_LAYER]: { width: 3, opacity: 0.95, color: '#fff', opacityFn: accentOpacityExpr, pulse: { count: 2, halfWidth: 0.028, color: '#ffffff' } },
}

// Walk: the marching-dot gradient itself IS the whole visual — no solid/
// colored base line underneath it, no separate "flow" layer on top of one.
// mainOpacityExpr/mainWidthExpr still apply on top of the gradient
// (line-opacity/line-width aren't replaced by line-gradient, only
// line-color is), so hover still brightens+widens the dots and dimming
// still fades them, exactly like a normal main line would. One entry per
// WALK_LAYER_IDS color (see its own comment above) — each identical except
// for which color its dots render in.
for (const [i, id] of WALK_LAYER_IDS.entries()) {
  LAYER_STYLE[id] = {
    width: 4,
    opacity: 0.85,
    color: '#fff', // inert — line-gradient (pulse, below) replaces line-color
    opacityFn: mainOpacityExpr,
    widthFn: mainWidthExpr,
    // Longer than the first pass (halfWidth 0.009 -> 0.016 -> 0.04) with a
    // large capFraction (0.6, vs drive's crisp 0.18 default — "bo tròn các
    // góc") so each mark is mostly rounded cap with just a short flat
    // shaft — a pill, not a rectangle. Fewer of them each time (14 -> 9 ->
    // 6) so the longer marks don't run into each other.
    //
    // Second pass (0.016/9) still read as round DOTS rather than elongated
    // pills on an actual walking leg: halfWidth is a fraction of THAT LEG's
    // own length (line-progress is normalized per feature, not per screen
    // pixel — see the module doc comment above on travelGradient's
    // trade-offs), and walking legs are short by construction (routing.py's
    // WALKING_THRESHOLD_KM only picks the "walking" profile under 1.2km) —
    // so a mark's on-screen length ended up close to or shorter than
    // line-width (4), reading as a circle instead of a capsule. This pass
    // (0.04, ~2.5x longer) targets a mark clearly longer than it is wide
    // (e.g. ~8px long x 4px wide on a ~100px-long leg on screen) regardless
    // of the exact leg length — capFraction stays 0.6 (same rounded/flat
    // proportions, just scaled up); count drops 9 -> 6 to keep a clear gap
    // between the now-longer marks (ink/gap goes from ~29/71 to ~48/52,
    // still visibly dashed, not a solid line). Engine limitation still
    // applies: an unusually short or long leg can still under/overshoot
    // this — there's no per-screen-pixel dash sizing available here.
    pulse: { count: 6, halfWidth: 0.04, color: LEG_COLORS[i], capFraction: 0.6 },
  }
}

/**
 * Direction-of-travel motion: a train of bright white dashes marching along
 * each drive/walk leg — matches the original design's CSS
 * `stroke-dasharray` + `stroke-dashoffset` marching-ants effect (many short
 * segments visible along the WHOLE leg at once, continuously scrolling),
 * not a single sweeping highlight.
 *
 * This is an animated `line-gradient`, NOT a scrolling `line-dasharray`, and
 * that choice is the whole reason it can run at display rate. A dasharray
 * pattern is baked into a texture atlas by the WORKER during tile parse
 * (LineBucket.populate -> addConstantDashes); the draw call only ever looks
 * the baked pattern up (LineAtlas.getDash returns this.positions[key], it
 * never adds one). So every new dasharray value has to wait on a tile
 * re-parse round-trip before it can show — which caps the effective frame
 * rate no matter how often setPaintProperty is called, and is exactly why
 * an earlier scrolling-dash version looked like ~30fps. A line-gradient is
 * instead rasterized into a small ramp texture on the MAIN thread inside the
 * render pass (keyed by gradientVersion), so rewriting it every frame is
 * cheap and lands in that same frame.
 *
 * Trade-off worth knowing: `line-progress` is normalized per FEATURE, so a
 * leg's dash count is fixed (not scaled to the leg's real-world length) —
 * `line-gradient` is a per-LAYER paint property in Mapbox GL, not
 * data-driven per feature like `line-color`/`line-width`, so every leg
 * sharing a layer necessarily shares one gradient shape. This is an engine
 * constraint, not a stylistic choice.
 */
/** Time for the drive dash train to advance by exactly one dash spacing (so the loop is seamless). */
const DRIVE_FLOW_CYCLE_MS = 4_800
/** Time for the walk dash train to advance by exactly one dash spacing. */
const WALK_FLOW_CYCLE_MS = 1_600

/** Hex `#rrggbb` -> a function giving that color at any alpha, for a pure-alpha gradient fade (see travelGradient). */
function alphaColorOf(hex: string): (alpha: number) => string {
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  return (alpha: number) => `rgba(${r},${g},${b},${alpha})`
}

/** Classic 3t²-2t³ ease: 0 at t=0, 1 at t=1, S-curved (slow-fast-slow) in between — not a straight ramp. */
function smoothstep(t: number): number {
  const x = Math.min(1, Math.max(0, t))
  return x * x * (3 - 2 * x)
}

/** Fractions sampled across one rounded cap, fed through smoothstep — a handful of points on the S-curve approximate a round end with mapbox's piecewise-LINEAR interpolate, the same way a many-sided polygon approximates a circle. */
const CAP_STEPS = [0, 0.25, 0.5, 0.75, 1]

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
 * `phase` runs 0->1 over one cycle: an evenly spaced train of `count` marks
 * shifted by one whole spacing per cycle — at phase 1 each mark has taken
 * its neighbour's place, so the loop is seamless. The -1/+1 iterations are
 * the marks half in and half out at the two ends.
 *
 * Each mark is a rounded PILL: a flat full-opacity "shaft" in the middle
 * (when `capFraction` leaves room for one) flanked by two curved caps. A
 * first attempt fully skipped the flat middle and ramped clear->core->clear
 * in one straight LINE per side — a straight ramp is a taper, not a curve,
 * so it read as a pointed lens/diamond, not a rounded pill end. This samples
 * each cap at CAP_STEPS through `smoothstep` instead of one straight line —
 * several points on an S-curve, piecewise-linear-interpolated by mapbox
 * between them, approximate an actual round end the way a many-sided
 * polygon approximates a circle. `capFraction` is how much of `halfWidth`
 * each cap eats into: small (drive's default) leaves a long flat shaft with
 * just a light rounding at the very ends — a crisp BAR; larger (walk) eats
 * more of the mark, leaving a short shaft between two clearly round ends —
 * a pill/capsule. Gradient stops still can't draw a true geometric round
 * line-cap on an internal color transition (only `line-cap` at a whole
 * feature's start/end does that), but a curved alpha taper reads as
 * "rounded" the same way a blurred/antialiased dot does.
 */
function travelGradient(count: number, halfWidth: number, phase: number, hexColor: string, capFraction = 0.18): mapboxgl.ExpressionSpecification {
  const colorAt = alphaColorOf(hexColor)
  const capWidth = halfWidth * capFraction
  const coreHalf = halfWidth - capWidth
  return buildGradient((push) => {
    push(0, colorAt(0))
    for (let index = -1; index <= count; index++) {
      const center = (index + phase) / count
      if (center + halfWidth < 0 || center - halfWidth > 1) continue
      const leftCapStart = center - halfWidth
      for (const t of CAP_STEPS) push(leftCapStart + t * capWidth, colorAt(smoothstep(t)))
      if (coreHalf > 0) push(center + coreHalf, colorAt(1)) // flat shaft: hold full opacity across the middle
      const rightCapStart = center + coreHalf
      for (const t of CAP_STEPS) push(rightCapStart + t * capWidth, colorAt(smoothstep(1 - t)))
    }
    push(1, colorAt(0))
  })
}

export interface MapMarkerSpec {
  syncId: string
  coordinates?: string | null
  kind: 'hotel' | 'item' | 'suggested'
  /** Number drawn inside the pin: an 'item' pin's stop order within its day,
   * a 'suggested' pin's position in the chat reply's numbered list. */
  label?: number
  dayNumber?: number
  openId?: string
  /** 'both' marks the hotel as the day's single start/end point (every day
   * starts and ends there) — 'start'/'end' remain for a non-hotel endpoint,
   * though the itinerary day view no longer produces those (see
   * stage-workspace.tsx's markers useMemo). */
  endpoint?: 'start' | 'end' | 'both'
  /** Hotel itinerary position number(s), revealed only while hovering the pin. */
  hoverLabel?: string
  priceLabel?: string
  matchLabel?: string
  /** 'suggested' only — revealed as a hover label on the pin; these pins have
   * no itinerary row to display the name next to. */
  name?: string
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
  /** True on the Overview tab (matches the design's `perDay = tab !== 'overview'`
   * split): color each segment by its DAY (dayColor) so a whole day reads as
   * one consistent color across the trip, instead of by LEG (legColor) —
   * which is what a single day's own tab uses, to tell that day's individual
   * legs apart. Defaults to false (leg-colored) for callers that don't pass it. */
  colorByDay?: boolean
  /** Show/hide toggle for 'suggested' marker pins — state lives in the
   * caller (transient, per-component), MapView only renders the control and
   * forwards clicks. Both absent (not just no-ops) when the caller has
   * nothing to toggle this turn — same convention as `onLocate`. */
  showSuggested?: boolean
  onToggleSuggested?: () => void
}

type FeatureCollection = { type: 'FeatureCollection'; features: Array<Record<string, unknown>> }

function routeData(segments: RouteSegment[], colorByDay: boolean): FeatureCollection {
  return {
    type: 'FeatureCollection',
    features: segments.map((segment) => ({
      type: 'Feature',
      id: segment.segKey,
      properties: {
        segKey: segment.segKey,
        isFallback: segment.isFallback,
        profile: segment.profile,
        color: colorByDay ? dayColor(segment.dayNumber) : legColor(segment.legIndex),
      },
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
  // promoteId (rather than relying on each Feature's top-level `id`) is
  // Mapbox's own documented pattern for feature-state on a GeoJSON source —
  // reads the id from the `segKey` property (already set on every feature,
  // see routeData) instead. Same effective ids either way; switched to this
  // after top-level `id` alone did not visibly light up hover/dim (still
  // unconfirmed which mechanism was at fault without a live browser check).
  map.addSource(ROUTE_SOURCE, { type: 'geojson', lineMetrics: true, promoteId: 'segKey', data: { type: 'FeatureCollection', features: [] } })
  const layout: mapboxgl.LineLayerSpecification['layout'] = { 'line-cap': 'round', 'line-join': 'round' }
  const realRouteFilter = ['==', ['get', 'isFallback'], false]
  const walkFilter = ['all', realRouteFilter, ['==', ['get', 'profile'], 'walking']]
  const driveFilter = ['all', realRouteFilter, ['!=', ['get', 'profile'], 'walking']]
  const fadeIn = { 'line-opacity-transition': { duration: ROUTE_FADE_MS, delay: 0 } }

  const layerEntries: Array<[string, unknown]> = [
    [DRIVE_CASING_LAYER, driveFilter],
    [DRIVE_LAYER, driveFilter],
    [FALLBACK_LAYER, ['==', ['get', 'isFallback'], true]],
    [DRIVE_FLOW_LAYER, driveFilter],
    // One walk layer per color, each only drawing the segments carrying
    // that exact color (see WALK_LAYER_IDS's own comment for why).
    ...WALK_LAYER_IDS.map((id, i): [string, unknown] => [id, ['all', walkFilter, ['==', ['get', 'color'], LEG_COLORS[i]]]]),
  ]
  for (const [id, filter] of layerEntries) {
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
        ...(style.pulse ? { 'line-gradient': travelGradient(style.pulse.count, style.pulse.halfWidth, 0, style.pulse.color, style.pulse.capFraction) } : { 'line-color': style.color }),
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

const ENDPOINT_BADGE_TEXT: Record<NonNullable<MapMarkerSpec['endpoint']>, string> = {
  start: 'XUẤT PHÁT',
  end: 'KẾT THÚC',
  both: 'XUẤT PHÁT & KẾT THÚC',
}

function appendEndpointBadge(content: HTMLElement, endpoint: MapMarkerSpec['endpoint']) {
  if (!endpoint) return
  const badge = document.createElement('div')
  badge.textContent = ENDPOINT_BADGE_TEXT[endpoint]
  badge.style.cssText = "position:absolute;left:50%;bottom:30px;transform:translateX(-50%);white-space:nowrap;padding:2px 8px;border-radius:99px;background:var(--btn);color:var(--btn-fg);font:600 9.5px/1.4 'Be Vietnam Pro',sans-serif;letter-spacing:.04em;box-shadow:0 6px 14px -6px rgba(0,0,0,.6)"
  content.appendChild(badge)
}

function createMarkerElement(marker: MapMarkerSpec): { root: HTMLDivElement; content: HTMLDivElement } {
  const root = document.createElement('div')
  const content = document.createElement('div')
  root.appendChild(content)
  content.style.cursor = 'pointer'
  content.style.transition = 'transform .25s cubic-bezier(.34,1.5,.64,1), box-shadow .25s ease, opacity .2s ease'
  content.style.transformOrigin = 'center'
  content.style.color = 'var(--on-acc)'
  content.style.border = '2px solid var(--surface-background)'
  content.style.boxShadow = '0 4px 12px -3px rgba(0,0,0,.45)'
  if (marker.kind === 'hotel') {
    content.style.display = 'flex'
    content.style.alignItems = 'center'
    content.style.gap = '6px'
    content.style.whiteSpace = 'nowrap'
    content.style.padding = '5px 10px'
    content.style.borderRadius = '999px'
    content.style.background = 'var(--acc)'
    content.style.font = "500 11.5px/1.2 'Be Vietnam Pro', sans-serif"
    content.style.setProperty('--base-marker', 'var(--acc)')
    content.style.position = 'relative'
    if (!marker.priceLabel && !marker.matchLabel) {
      const icon = document.createElement('span')
      icon.className = 'material-symbols-outlined'
      icon.style.fontSize = '15px'
      icon.textContent = 'hotel'
      content.appendChild(icon)
    }
    if (marker.priceLabel) { const price = document.createElement('b'); price.textContent = marker.priceLabel; price.style.fontWeight = '590'; content.appendChild(price) }
    if (marker.matchLabel) { const match = document.createElement('span'); match.textContent = marker.matchLabel; match.style.opacity = '.75'; content.appendChild(match) }
    // A day view's hotel never carries a hoverLabel (hotelItemNumbers is
    // empty whenever the hotel isn't literally embedded as a day item — see
    // stage-workspace.tsx), so this static badge and the hover-only number
    // label below never actually compete for the same spot in practice.
    if (marker.endpoint) appendEndpointBadge(content, marker.endpoint)
    else if (marker.hoverLabel) {
      const label = document.createElement('div')
      label.dataset.hotelMarkerNumber = 'true'
      label.textContent = marker.hoverLabel
      label.style.cssText = "position:absolute;left:50%;bottom:30px;transform:translate(-50%,4px);white-space:nowrap;padding:2px 8px;border-radius:99px;background:var(--btn);color:var(--btn-fg);font:600 9.5px/1.4 'Be Vietnam Pro',sans-serif;letter-spacing:.04em;box-shadow:0 6px 14px -6px rgba(0,0,0,.6);opacity:0;pointer-events:none;transition:opacity .16s ease,transform .16s ease"
      content.appendChild(label)
    }
  } else if (marker.kind === 'suggested') {
    // Carries the chat reply's own list number so "5. Xe 2 tầng Hà Nội" in
    // the message can be found on the map at a glance. Still never
    // day-colored: a neutral glass surface with --t1 ink is what separates a
    // suggestion from the saturated, white-on-color numbered day pins below,
    // so the number alone can't make the two read alike. Falls back to the
    // place icon when a caller has no number to give.
    content.style.width = '24px'
    content.style.height = '24px'
    content.style.borderRadius = '50%'
    content.style.display = 'flex'
    content.style.alignItems = 'center'
    content.style.justifyContent = 'center'
    content.style.background = 'var(--g3)'
    content.style.color = 'var(--t1)'
    content.style.animation = 'vPinIn .6s cubic-bezier(.34,1.4,.64,1) backwards'
    if (marker.label != null) {
      content.style.font = "600 11px/1 'Be Vietnam Pro', sans-serif"
      content.textContent = String(marker.label)
    } else {
      const icon = document.createElement('span')
      icon.className = 'material-symbols-outlined'
      icon.style.fontSize = '14px'
      icon.textContent = 'place'
      content.appendChild(icon)
    }
    // Name label lives on `root`, not `content`: content is what
    // applyMarkerState scales to 1.45 on hover, and a scaled label would
    // render its text blurry-large instead of at its own size.
    if (marker.name) {
      const label = document.createElement('div')
      label.dataset.markerName = 'true'
      // Number repeated here, not just on the pin: the pin's own digit is
      // hidden under the cursor at the moment the label opens.
      label.textContent = marker.label != null ? `${marker.label}. ${marker.name}` : marker.name
      label.style.cssText = "position:absolute;left:50%;bottom:32px;transform:translate(-50%,4px);max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;padding:3px 9px;border-radius:99px;background:var(--g3);border:1px solid var(--edge);color:var(--t1);font:500 10.5px/1.4 'Be Vietnam Pro',sans-serif;box-shadow:0 6px 14px -6px rgb(var(--shadow-rgb) / .6);opacity:0;pointer-events:none;transition:opacity .16s ease,transform .16s ease"
      root.appendChild(label)
    }
  } else {
    content.style.width = '26px'
    content.style.height = '26px'
    content.style.borderRadius = '50%'
    content.style.background = dayColor(marker.dayNumber ?? 1)
    content.style.font = "600 12px/26px 'Be Vietnam Pro', sans-serif"
    content.style.textAlign = 'center'
    content.style.animation = `vPinIn .6s ${(marker.label ?? 1) * 65}ms cubic-bezier(.34,1.4,.64,1) backwards`
    content.textContent = marker.label != null ? String(marker.label) : ''
    appendEndpointBadge(content, marker.endpoint)
  }
  return { root, content }
}

function applyMarkerState(content: HTMLElement, marker: MapMarkerSpec, hovered: boolean, selected: boolean, dimmed: boolean) {
  const scale = marker.kind === 'hotel' ? (hovered ? 1.18 : 1) : (hovered || selected ? 1.45 : 1)
  content.style.transform = `scale(${scale})`
  const root = content.parentElement as HTMLElement | null
  if (root) root.style.zIndex = hovered ? '1000' : selected ? '900' : '0'
  content.style.opacity = dimmed ? '.55' : '1'
  content.style.boxShadow = hovered || selected ? '0 8px 20px -4px rgb(var(--shadow-rgb) / .6), 0 0 0 6px var(--g2)' : '0 4px 12px -3px rgb(var(--shadow-rgb) / .45)'
  if (marker.kind === 'suggested') {
    // Suggested pins carry no itinerary row, so the name only ever appears
    // here — revealed by hover or an active selection, same rule as the
    // hotel pin's number label below.
    const name = root?.querySelector<HTMLElement>('[data-marker-name]')
    if (name) {
      const shown = hovered || selected
      name.style.opacity = shown ? '1' : '0'
      name.style.transform = shown ? 'translate(-50%,0)' : 'translate(-50%,4px)'
    }
  }
  if (marker.kind === 'hotel') {
    content.style.background = selected ? 'var(--btn)' : 'var(--base-marker)'
    content.style.color = selected ? 'var(--btn-fg)' : 'var(--on-acc)'
    const number = content.querySelector<HTMLElement>('[data-hotel-marker-number]')
    if (number) {
      number.style.opacity = hovered ? '1' : '0'
      number.style.transform = hovered ? 'translate(-50%,0)' : 'translate(-50%,4px)'
    }
  }
}

function fitWorkspace(map: mapboxgl.Map, points: { lat: number; lng: number }[]) {
  if (points.length === 1) map.flyTo({ center: toLngLat(points[0]), zoom: 15, duration: 900 })
  else if (points.length > 1) { const bounds = boundsOf(points)!; map.fitBounds([[bounds.sw.lng, bounds.sw.lat], [bounds.ne.lng, bounds.ne.lat]], { padding: 56, maxZoom: 15, duration: 900 }) }
}

export default function MapView({ variant, theme, markers, segments, hoveredId, onHoverChange, onMarkerClick, selectedId = null, hotelRays = [], colorByDay = false, showSuggested, onToggleSuggested }: MapViewProps) {
  const { t } = useTranslation()
  const [styleKind, setStyleKind] = useState<MapStyleKind>('map')
  const { containerRef, mapRef, status, styleVersion, tokenMissing, retry } = useMapboxMap(theme, styleKind)
  const markerRegistry = useRef(new Map<string, { marker: mapboxgl.Marker; spec: MapMarkerSpec }>())
  const badgeRegistry = useRef<mapboxgl.Marker[]>([])
  const prevPointsKey = useRef<string>('')
  const onHoverRef = useRef(onHoverChange); onHoverRef.current = onHoverChange
  const onClickRef = useRef(onMarkerClick); onClickRef.current = onMarkerClick
  const markerKey = useMemo(() => markers.map((marker) => JSON.stringify(marker)).join('|'), [markers])

  // Route line animation rebuilds a line-gradient every frame per flow layer
  // (see travelGradient's doc comment for why that's not cheap) — the loop
  // below used to do that for all 7 flow layers (drive + all 6 walk colors)
  // regardless of whether a given day actually used a color, which on a
  // typical 1-2-color day meant 4-5 layers being recomputed and pushed to
  // Mapbox 60x/second for nothing visible on screen. This narrows it to only
  // the layers a real segment in the CURRENT `segments` will actually paint.
  const activeFlowLayers = useMemo(() => {
    const active = new Set<string>()
    for (const segment of segments) {
      if (segment.isFallback) continue
      if (segment.profile === 'walking') {
        const color = colorByDay ? dayColor(segment.dayNumber) : legColor(segment.legIndex)
        const index = (LEG_COLORS as readonly string[]).indexOf(color)
        if (index >= 0) active.add(WALK_LAYER_IDS[index])
      } else {
        active.add(DRIVE_FLOW_LAYER)
      }
    }
    return active
  }, [segments, colorByDay])

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
    // Frame the hotel coordinates whenever points change (e.g. switching chat
    // sessions or arriving on stage 2 for a different destination).
    const currentPointsKey = points.map((p) => `${p.lat.toFixed(4)},${p.lng.toFixed(4)}`).join('|')
    if (variant === 'hotels' && points.length > 0 && currentPointsKey !== prevPointsKey.current) {
      prevPointsKey.current = currentPointsKey
      fitWorkspace(map, points)
    }
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
    source.setData(routeData(segments, colorByDay) as never)
    return startDrawIn(map)
  }, [segments, status, styleVersion, variant, colorByDay, mapRef])

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
  // paint property per moving overlay — filtered to activeFlowLayers (see
  // its own comment above) so an idle color's layer is never touched, never
  // one loop per segment either way. Runs at display rate with no
  // quantization at all, because line-gradient updates on the main thread
  // (see travelGradient's doc comment for why the earlier
  // scrolling-dasharray version could not).
  useEffect(() => {
    const map = mapRef.current
    if (!map || status !== 'ready' || variant !== 'workspace' || window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return
    // Built once per effect run (segments/style change), not per frame.
    const allFlowLayers: Array<[string, number]> = [
      [DRIVE_FLOW_LAYER, DRIVE_FLOW_CYCLE_MS],
      ...WALK_LAYER_IDS.map((id): [string, number] => [id, WALK_FLOW_CYCLE_MS]),
    ]
    const flowLayers = allFlowLayers.filter(([id]) => activeFlowLayers.has(id))
    if (flowLayers.length === 0) return
    let frame = 0
    let start = 0
    const tick = (time: number) => {
      if (!start) start = time
      const elapsed = time - start
      for (const [id, cycleMs] of flowLayers) {
        const style = LAYER_STYLE[id]
        if (!map.getLayer(id) || !style.pulse) continue
        map.setPaintProperty(id, 'line-gradient', travelGradient(style.pulse.count, style.pulse.halfWidth, (elapsed % cycleMs) / cycleMs, style.pulse.color, style.pulse.capFraction))
      }
      frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [status, styleVersion, variant, mapRef, activeFlowLayers])

  useEffect(() => {
    const map = mapRef.current
    badgeRegistry.current.forEach((marker) => marker.remove()); badgeRegistry.current = []
    if (!map || status !== 'ready' || variant !== 'hotels') return
    const lineColor = theme === 'dark' ? '#EDF0F4' : '#0e1319'
    if (!map.getSource(RAY_SOURCE)) map.addSource(RAY_SOURCE, { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
    if (!map.getLayer(RAY_LAYER)) map.addLayer({ id: RAY_LAYER, type: 'line', source: RAY_SOURCE, paint: { 'line-color': lineColor, 'line-width': 1.6, 'line-opacity': .45, 'line-dasharray': [3, 7] } })
    else map.setPaintProperty(RAY_LAYER, 'line-color', lineColor)
    if (!map.getSource(HALO_SOURCE)) map.addSource(HALO_SOURCE, { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
    if (!map.getLayer(HALO_LAYER)) map.addLayer({ id: HALO_LAYER, type: 'circle', source: HALO_SOURCE, paint: { 'circle-radius': 26, 'circle-color': lineColor, 'circle-opacity': .07, 'circle-stroke-color': lineColor, 'circle-stroke-width': 1.4, 'circle-stroke-opacity': .5 } })
    else {
      map.setPaintProperty(HALO_LAYER, 'circle-color', lineColor)
      map.setPaintProperty(HALO_LAYER, 'circle-stroke-color', lineColor)
    }
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
      // background used to be a literal rgba(255,255,255,.85) — in dark
      // theme --t1 (the text color right after it) flips to a near-white
      // ink, so light text landed on a still-near-white background: barely
      // legible. --g3 is the same "elevated glass" surface every other
      // badge/chip in the app uses, and actually inverts with the theme.
      el.style.cssText = "white-space:nowrap;padding:2px 8px;border-radius:99px;background:var(--g3);border:1px solid var(--edge);box-shadow:0 4px 10px -6px rgb(var(--shadow-rgb) / .6);font:400 10px/1.3 'Be Vietnam Pro',sans-serif;color:var(--t1)"
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
        <MapControls styleKind={styleKind} onZoomIn={() => mapRef.current?.zoomIn()} onZoomOut={() => mapRef.current?.zoomOut()} onFitRoute={() => { const points = markers.map((marker) => parseCoordinates(marker.coordinates)).filter((point): point is NonNullable<typeof point> => point != null); fitWorkspace(mapRef.current!, points) }} onLocate={hasGeolocation ? () => navigator.geolocation.getCurrentPosition((position) => mapRef.current?.flyTo({ center: [position.coords.longitude, position.coords.latitude], zoom: 14, duration: 600 })) : undefined} onToggleStyle={() => setStyleKind((kind) => kind === 'satellite' ? 'map' : 'satellite')} showSuggested={showSuggested} onToggleSuggested={onToggleSuggested} className="absolute right-4 top-4 z-10" />
      </>}
    </>}
  </div>
}
