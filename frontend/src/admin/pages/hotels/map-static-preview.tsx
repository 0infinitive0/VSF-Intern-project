import { useEffect, useState } from 'react'

/**
 * map-static-preview.tsx -- B2's "Xem trước vị trí trên bản đồ" (L30).
 * Renders one `<img>` against Mapbox's Static Images API instead of
 * embedding `mapbox-gl`: the admin bundle has no other reason to carry that
 * library's weight, and this preview needs one flat image, not an
 * interactive map (see Phase 3's decision against pulling the chat app's map
 * stack into admin). Reuses VITE_MAPBOX_TOKEN (public pk.*, see
 * frontend/.env.example) -- same token the chat app's MapView renders with,
 * same "leave the token blank -> honest unavailable state" rule from
 * use-mapbox-map.ts.
 */
interface MapStaticPreviewProps {
  latitude: number | null
  longitude: number | null
}

const TOKEN = (import.meta.env.VITE_MAPBOX_TOKEN as string | undefined) || ''
const DEBOUNCE_MS = 500

function previewUrl(lat: number, lng: number): string {
  const marker = `pin-s+3A73DE(${lng},${lat})`
  return `https://api.mapbox.com/styles/v1/mapbox/streets-v12/static/${marker}/${lng},${lat},13,0/640x280@2x?access_token=${TOKEN}`
}

export function MapStaticPreview({ latitude, longitude }: MapStaticPreviewProps) {
  const hasCoords = latitude !== null && longitude !== null && Number.isFinite(latitude) && Number.isFinite(longitude)

  // Vĩ độ/Kinh độ are plain number inputs typed digit-by-digit -- without
  // debouncing, every keystroke would fire a billable Mapbox Static Images
  // API request.
  const [debounced, setDebounced] = useState<{ lat: number; lng: number } | null>(
    hasCoords ? { lat: latitude, lng: longitude } : null,
  )
  useEffect(() => {
    if (!hasCoords) {
      setDebounced(null)
      return
    }
    const timer = setTimeout(() => setDebounced({ lat: latitude, lng: longitude }), DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [hasCoords, latitude, longitude])

  const unavailable = !TOKEN || !debounced

  return (
    <div
      style={{
        height: 200,
        borderRadius: 12,
        border: '1px solid var(--stroke)',
        background: 'var(--fill)',
        overflow: 'hidden',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      {unavailable ? (
        <span style={{ fontSize: 12.5, color: 'var(--t4)' }}>
          {hasCoords ? 'Bản đồ không khả dụng' : 'Nhập vĩ độ/kinh độ để xem trước vị trí'}
        </span>
      ) : (
        <img
          src={previewUrl(debounced.lat, debounced.lng)}
          alt="Xem trước vị trí trên bản đồ"
          style={{ width: '100%', height: '100%', objectFit: 'cover' }}
        />
      )}
    </div>
  )
}
