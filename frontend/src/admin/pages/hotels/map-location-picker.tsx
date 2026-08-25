import { useEffect, useRef, useState } from 'react'
import type { Map as MapboxMap, Marker as MapboxMarker } from 'mapbox-gl'

/**
 * map-location-picker.tsx -- interactive replacement for the old
 * map-static-preview.tsx: click the map or drag the pin to set Vĩ độ/Kinh
 * độ instead of typing only. `mapbox-gl` is loaded via dynamic import()
 * rather than a static one -- admin-app.tsx imports every route eagerly
 * (no route-level code splitting, see router.tsx), so a static import here
 * would add mapbox-gl's weight to every admin page, not just the hotel
 * form. That's exactly the cost map-static-preview.tsx's docstring chose
 * to avoid; the dynamic import keeps it scoped to Vite's own chunk that
 * only loads once this component mounts.
 */
interface MapLocationPickerProps {
  latitude: number | null
  longitude: number | null
  onPick: (lat: number, lng: number) => void
}

const TOKEN = (import.meta.env.VITE_MAPBOX_TOKEN as string | undefined) || ''
// Same default center as use-mapbox-map.ts (Đà Nẵng) -- only a starting
// camera position, never a marker placement for missing coordinates.
const DEFAULT_CENTER: [number, number] = [108.2208, 16.0544]
const DEFAULT_ZOOM = 11
const PIN_ZOOM = 13
const MARKER_COLOR = '#3A73DE'
// Camera recentering (not the marker itself) is debounced so typing
// digit-by-digit into Vĩ độ/Kinh độ doesn't fight the map with an animated
// flyTo on every keystroke -- same rationale map-static-preview.tsx used
// for its Static Images API debounce.
const RECENTER_DEBOUNCE_MS = 400

type Status = 'loading' | 'ready' | 'error'

export function MapLocationPicker({ latitude, longitude, onPick }: MapLocationPickerProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const mapRef = useRef<MapboxMap | null>(null)
  const markerRef = useRef<MapboxMarker | null>(null)
  // Click/drag handlers close over this instead of `onPick` directly so the
  // map-creation effect below never needs onPick in its deps.
  const onPickRef = useRef(onPick)
  onPickRef.current = onPick
  const [status, setStatus] = useState<Status>('loading')

  const hasCoords = latitude !== null && longitude !== null && Number.isFinite(latitude) && Number.isFinite(longitude)

  // Create the map once per mount.
  useEffect(() => {
    if (!TOKEN || !containerRef.current) return
    let cancelled = false

    Promise.all([import('mapbox-gl'), import('mapbox-gl/dist/mapbox-gl.css')])
      .then(([mod]) => {
        if (cancelled || !containerRef.current) return
        const mapboxgl = mod.default
        mapboxgl.accessToken = TOKEN
        const map = new mapboxgl.Map({
          container: containerRef.current,
          style: 'mapbox://styles/mapbox/streets-v12',
          center: hasCoords ? [longitude as number, latitude as number] : DEFAULT_CENTER,
          zoom: hasCoords ? PIN_ZOOM : DEFAULT_ZOOM,
        })
        const marker = new mapboxgl.Marker({ color: MARKER_COLOR, draggable: true })
        if (hasCoords) marker.setLngLat([longitude as number, latitude as number]).addTo(map)

        marker.on('dragend', () => {
          const pos = marker.getLngLat()
          onPickRef.current(pos.lat, pos.lng)
        })
        map.on('click', (e) => {
          marker.setLngLat(e.lngLat).addTo(map)
          onPickRef.current(e.lngLat.lat, e.lngLat.lng)
        })
        map.on('load', () => !cancelled && setStatus('ready'))
        map.on('error', (e) => {
          console.error('[map-location-picker] mapbox-gl error:', e.error)
          if (!cancelled) setStatus('error')
        })

        mapRef.current = map
        markerRef.current = marker
      })
      .catch((err: unknown) => {
        console.error('[map-location-picker] failed to load mapbox-gl:', err)
        if (!cancelled) setStatus('error')
      })

    return () => {
      cancelled = true
      mapRef.current?.remove()
      mapRef.current = null
      markerRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- created once; initial lat/lng/hasCoords only seed the starting camera/marker position
  }, [])

  // Marker follows lat/lng typed into the number inputs too, not just pin
  // drags -- applied immediately (cheap, no animation, no debounce needed).
  useEffect(() => {
    const map = mapRef.current
    const marker = markerRef.current
    if (!map || !marker) return
    if (!hasCoords) {
      marker.remove()
      return
    }
    marker.setLngLat([longitude as number, latitude as number]).addTo(map)
  }, [hasCoords, latitude, longitude])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !hasCoords) return
    const timer = setTimeout(() => {
      map.easeTo({ center: [longitude as number, latitude as number], duration: 300 })
    }, RECENTER_DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [hasCoords, latitude, longitude])

  return (
    <div
      style={{
        height: 260,
        borderRadius: 12,
        border: '1px solid var(--stroke)',
        background: 'var(--fill)',
        overflow: 'hidden',
        position: 'relative',
      }}
    >
      {!TOKEN ? (
        <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <span style={{ fontSize: 12.5, color: 'var(--t4)' }}>Bản đồ không khả dụng</span>
        </div>
      ) : (
        <>
          <div ref={containerRef} style={{ width: '100%', height: '100%' }} />
          {status === 'error' && (
            <div
              style={{
                position: 'absolute',
                inset: 0,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                background: 'var(--fill)',
              }}
            >
              <span style={{ fontSize: 12.5, color: 'var(--t4)' }}>Bản đồ không khả dụng</span>
            </div>
          )}
        </>
      )}
    </div>
  )
}
