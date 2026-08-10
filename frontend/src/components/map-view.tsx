import { useEffect, useMemo, useRef } from 'react'
import type { ReactNode } from 'react'
import mapboxgl from 'mapbox-gl'
import { useTranslation } from 'react-i18next'
import { useMapboxMap } from '../hooks/use-mapbox-map'
import { boundsOf, parseCoordinates, toLngLat } from '../lib/geo'
import { dayColor, kindAccent } from '../lib/map-colors'
import MapLegend from './map-legend'
import type { RouteSegment } from '../lib/route-segments'
import type { Theme } from '../hooks/use-theme'

const SOURCE_ID = 'trip-routes'
const DRIVING_LAYER = 'route-line-driving'
const WALKING_LAYER = 'route-line-walking'
const FALLBACK_LAYER = 'route-line-fallback'
const ROUTE_LAYER_IDS = [DRIVING_LAYER, WALKING_LAYER, FALLBACK_LAYER] as const

export interface MapMarkerSpec {
  syncId: string
  coordinates?: string | null
  kind: 'hotel' | 'item'
  /** 1-based position label shown inside an 'item' pin; ignored for 'hotel'. */
  label?: number
  /** Day-color source for an 'item' pin. */
  dayNumber?: number
  /** Present when clicking this marker should also open a detail focus mode, in addition to scrolling its card into view. */
  openId?: string
}

export interface MapViewProps {
  theme: Theme
  markers: MapMarkerSpec[]
  segments: RouteSegment[]
  hoveredId: string | null
  onHoverChange: (id: string | null) => void
  onMarkerClick: (marker: MapMarkerSpec) => void
  /** Stage-specific overlay (e.g. the hotels-stage top-left hotel-count/status card) — not legend content. */
  statusOverlay?: ReactNode
  showLegend?: boolean
}

// Local shape instead of the ambient `GeoJSON.*` namespace (from @types/geojson,
// which mapbox-gl pulls in transitively) — avoids depending on whether that
// package's ambient globals are visible in this file's compilation, while
// staying structurally compatible with what mapboxgl.GeoJSONSourceSpecification expects.
interface RouteFeature {
  type: 'Feature'
  id: string
  properties: { segKey: string; isFallback: boolean; profile: string | null; color: string }
  geometry: { type: 'LineString'; coordinates: [number, number][] }
}
interface RouteFeatureCollection {
  type: 'FeatureCollection'
  features: RouteFeature[]
}

function segmentsToFeatureCollection(segments: RouteSegment[]): RouteFeatureCollection {
  return {
    type: 'FeatureCollection',
    features: segments.map((seg) => ({
      type: 'Feature',
      id: seg.segKey,
      properties: {
        segKey: seg.segKey,
        isFallback: seg.isFallback,
        profile: seg.profile ?? null,
        color: dayColor(seg.dayNumber),
      },
      geometry: {
        type: 'LineString',
        coordinates: seg.points.map((p) => toLngLat(p)),
      },
    })),
  }
}

/**
 * Adds the shared source + 3 filtered line-layers (driving/walking/fallback —
 * line-dasharray isn't data-driven in the GL style spec, only zoom
 * expressions, so a single layer can't vary dash pattern per feature).
 *
 * Hover highlight is declared ONCE here via feature-state expressions —
 * `map.setFeatureState()` alone (no further setPaintProperty calls) is
 * enough to re-evaluate line-opacity/line-width per feature, exactly like
 * Mapbox's own "create a hover effect" pattern. This is simpler than (and
 * functionally equivalent to) toggling the expression itself on every
 * hover change.
 */
function addRouteLayers(map: mapboxgl.Map) {
  map.addSource(SOURCE_ID, { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })

  const commonLayout: mapboxgl.LineLayerSpecification['layout'] = {
    'line-cap': 'round',
    'line-join': 'round',
  }

  map.addLayer({
    id: DRIVING_LAYER,
    type: 'line',
    source: SOURCE_ID,
    filter: ['all', ['==', ['get', 'isFallback'], false], ['!=', ['get', 'profile'], 'walking']],
    layout: commonLayout,
    paint: {
      'line-color': ['get', 'color'],
      'line-dasharray': [1, 0],
      'line-opacity': ['case', ['boolean', ['feature-state', 'hovered'], false], 1.0, 0.85],
      'line-width': ['case', ['boolean', ['feature-state', 'hovered'], false], 6, 4],
      'line-opacity-transition': { duration: 500, delay: 0 },
      'line-width-transition': { duration: 300, delay: 0 },
    },
  } as mapboxgl.LineLayerSpecification)

  map.addLayer({
    id: WALKING_LAYER,
    type: 'line',
    source: SOURCE_ID,
    filter: ['all', ['==', ['get', 'isFallback'], false], ['==', ['get', 'profile'], 'walking']],
    layout: commonLayout,
    paint: {
      'line-color': ['get', 'color'],
      'line-dasharray': [2, 1.6],
      'line-opacity': ['case', ['boolean', ['feature-state', 'hovered'], false], 1.0, 0.85],
      'line-width': ['case', ['boolean', ['feature-state', 'hovered'], false], 6, 4],
      'line-opacity-transition': { duration: 500, delay: 0 },
      'line-width-transition': { duration: 300, delay: 0 },
    },
  } as mapboxgl.LineLayerSpecification)

  // Fallback legs: same day color, distinguished by sparser dash + lower
  // opacity + thinner width — never a second color, never curved (see
  // route-segments.ts doc comment on why this stays a straight line).
  map.addLayer({
    id: FALLBACK_LAYER,
    type: 'line',
    source: SOURCE_ID,
    filter: ['==', ['get', 'isFallback'], true],
    layout: commonLayout,
    paint: {
      'line-color': ['get', 'color'],
      'line-dasharray': [0.6, 1.8],
      'line-opacity': ['case', ['boolean', ['feature-state', 'hovered'], false], 0.9, 0.5],
      'line-width': ['case', ['boolean', ['feature-state', 'hovered'], false], 5, 3],
      'line-opacity-transition': { duration: 500, delay: 0 },
      'line-width-transition': { duration: 300, delay: 0 },
    },
  } as mapboxgl.LineLayerSpecification)
}

/** One-time fade-in right after the layers are (re)created — see map-view.tsx's route effect. */
function fadeInRouteLayers(map: mapboxgl.Map) {
  for (const id of ROUTE_LAYER_IDS) {
    if (!map.getLayer(id)) continue
    map.setPaintProperty(id, 'line-opacity', 0)
  }
  requestAnimationFrame(() => {
    for (const id of ROUTE_LAYER_IDS) {
      if (!map.getLayer(id)) continue
      map.setPaintProperty(id, 'line-opacity', [
        'case',
        ['boolean', ['feature-state', 'hovered'], false],
        id === FALLBACK_LAYER ? 0.9 : 1.0,
        id === FALLBACK_LAYER ? 0.5 : 0.85,
      ])
    }
  })
}

function createMarkerElement(marker: MapMarkerSpec): HTMLDivElement {
  const el = document.createElement('div')
  el.style.cursor = 'pointer'
  el.style.display = 'flex'
  el.style.alignItems = 'center'
  el.style.justifyContent = 'center'
  el.style.transition = 'transform .18s cubic-bezier(.34,1.4,.64,1)'
  el.style.transformOrigin = 'center'
  el.style.color = '#fff'
  el.style.border = '2px solid #fff'
  el.style.borderRadius = '50%'
  el.style.boxShadow = '0 3px 10px -3px rgba(0,0,0,.55)'

  if (marker.kind === 'hotel') {
    el.style.width = '34px'
    el.style.height = '34px'
    el.style.background = kindAccent('hotel')
    const icon = document.createElement('span')
    icon.className = 'material-symbols-outlined'
    icon.textContent = 'hotel'
    icon.style.fontSize = '17px'
    icon.setAttribute('aria-hidden', 'true')
    el.appendChild(icon)
  } else {
    el.style.width = '24px'
    el.style.height = '24px'
    el.style.background = dayColor(marker.dayNumber ?? 1)
    el.style.fontSize = '11px'
    el.style.fontWeight = '590'
    el.textContent = marker.label != null ? String(marker.label) : ''
  }

  return el
}

function applyHoverStyle(el: HTMLElement, hovered: boolean) {
  el.style.transform = hovered ? 'scale(1.22)' : 'scale(1)'
  el.style.zIndex = hovered ? '10' : '0'
}

export default function MapView({
  theme,
  markers,
  segments,
  hoveredId,
  onHoverChange,
  onMarkerClick,
  statusOverlay,
  showLegend,
}: MapViewProps) {
  const { t } = useTranslation()
  const { containerRef, mapRef, ready, styleVersion, tokenMissing } = useMapboxMap(theme)
  const markerRegistry = useRef<Map<string, mapboxgl.Marker>>(new Map())

  // Latest-callback refs so the imperative marker effect doesn't need to
  // recreate markers every time a parent re-render hands it a fresh inline
  // callback — only real data changes (markersKey below) do that.
  const onHoverChangeRef = useRef(onHoverChange)
  onHoverChangeRef.current = onHoverChange
  const onMarkerClickRef = useRef(onMarkerClick)
  onMarkerClickRef.current = onMarkerClick

  const markersKey = useMemo(
    () => markers.map((m) => `${m.syncId}:${m.coordinates ?? ''}:${m.kind}:${m.label ?? ''}:${m.dayNumber ?? ''}:${m.openId ?? ''}`).join('|'),
    [markers],
  )

  // Marker reconciliation: add/remove/move by syncId, plus an initial
  // camera fit over whatever's currently plottable. Coordinates that fail
  // to parse are dropped here — never plotted at (0,0).
  useEffect(() => {
    const map = mapRef.current
    if (!map || !ready) return

    const registry = markerRegistry.current
    const seen = new Set<string>()
    const points: { lat: number; lng: number }[] = []

    for (const marker of markers) {
      const point = parseCoordinates(marker.coordinates)
      if (!point) continue
      seen.add(marker.syncId)
      points.push(point)

      const existing = registry.get(marker.syncId)
      if (existing) {
        existing.setLngLat(toLngLat(point))
        continue
      }

      const el = createMarkerElement(marker)
      el.addEventListener('mouseenter', () => onHoverChangeRef.current(marker.syncId))
      el.addEventListener('mouseleave', () => onHoverChangeRef.current(null))
      el.addEventListener('click', () => onMarkerClickRef.current(marker))

      const mbMarker = new mapboxgl.Marker({ element: el }).setLngLat(toLngLat(point)).addTo(map)
      registry.set(marker.syncId, mbMarker)
    }

    for (const [syncId, mbMarker] of registry) {
      if (!seen.has(syncId)) {
        mbMarker.remove()
        registry.delete(syncId)
      }
    }

    if (points.length === 1) {
      map.flyTo({ center: toLngLat(points[0]), zoom: 14, duration: 600 })
    } else if (points.length >= 2) {
      const bounds = boundsOf(points)!
      map.fitBounds(
        [
          [bounds.sw.lng, bounds.sw.lat],
          [bounds.ne.lng, bounds.ne.lat],
        ],
        { padding: 56, maxZoom: 15, duration: 600 },
      )
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- markersKey is the real dependency; markers/onHoverChange/onMarkerClick read via refs/key above
  }, [ready, markersKey])

  // Reverse hover direction (timeline/card hover -> marker highlight).
  useEffect(() => {
    for (const [syncId, mbMarker] of markerRegistry.current) {
      applyHoverStyle(mbMarker.getElement(), syncId === hoveredId)
    }
  }, [hoveredId])

  // Route source/layers: re-added after every style (re)load (setStyle wipes
  // them, see use-mapbox-map.ts), then setData on every segment change.
  useEffect(() => {
    const map = mapRef.current
    if (!map || !ready) return

    let justCreated = false
    if (!map.getSource(SOURCE_ID)) {
      addRouteLayers(map)
      justCreated = true
    }

    const source = map.getSource(SOURCE_ID) as mapboxgl.GeoJSONSource
    source.setData(segmentsToFeatureCollection(segments))
    if (justCreated) fadeInRouteLayers(map)
  }, [styleVersion, segments, ready, mapRef])

  // Route hover highlight: setFeatureState only — the paint expressions
  // declared in addRouteLayers already react to it (no setPaintProperty
  // needed per hover change).
  useEffect(() => {
    const map = mapRef.current
    if (!map || !ready || !map.getSource(SOURCE_ID)) return

    const hoveredSegKeys = new Set(
      segments.filter((s) => s.fromKey === hoveredId || s.toKey === hoveredId).map((s) => s.segKey),
    )
    for (const seg of segments) {
      map.setFeatureState({ source: SOURCE_ID, id: seg.segKey }, { hovered: hoveredSegKeys.has(seg.segKey) })
    }
  }, [hoveredId, segments, ready, styleVersion, mapRef])

  return (
    <div
      className="relative w-full h-full rounded-[26px] overflow-hidden border border-edge"
      style={{ boxShadow: '0 20px 50px -26px rgb(var(--shadow-rgb) / 0.3)' }}
    >
      {tokenMissing ? (
        <div className="absolute inset-0 flex items-center justify-center bg-surface-muted px-6">
          <div className="text-center text-on-surface-variant">
            <span className="material-symbols-outlined text-4xl" aria-hidden="true">
              map
            </span>
            <div className="font-medium text-on-surface mt-2">{t('mapUnavailableTitle')}</div>
            <div className="text-sm mt-1">{t('mapUnavailableBody')}</div>
          </div>
        </div>
      ) : (
        <>
          {/* w-full h-full, NOT absolute+inset-0: mapbox-gl.css ships a
              `.mapboxgl-map { position: relative }` rule, and Mapbox GL JS
              appends that exact class to whatever element we hand it as
              `container` — it silently wins over our own `absolute` utility
              (same specificity, later in the cascade), which drops `inset-0`
              positioning and collapses this div to its normal-flow height
              (0, since its only child content is absolutely-positioned).
              Plain block sizing sidesteps the fight entirely; the overlay
              siblings below stay `absolute` against the very same
              `position: relative` parent (this component's own root), so
              stacking is unaffected. */}
          <div ref={containerRef} className="w-full h-full" />
          {statusOverlay && <div className="absolute top-4 left-4 right-4 z-10">{statusOverlay}</div>}
          {showLegend && <MapLegend segments={segments} className="absolute bottom-4 left-4 z-10" />}
        </>
      )}
    </div>
  )
}
