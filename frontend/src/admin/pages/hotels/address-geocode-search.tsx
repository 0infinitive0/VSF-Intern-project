import { useEffect, useRef, useState } from 'react'
import { Input } from '../../ui/input'

export interface GeocodeResult {
  address: string
  city: string
  latitude: number
  longitude: number
}

interface AddressGeocodeSearchProps {
  id: string
  value: string
  onChange: (address: string) => void
  onSelect: (result: GeocodeResult) => void
  placeholder?: string
}

interface Suggestion {
  mapbox_id: string
  name: string
  full_address?: string
  place_formatted?: string
  feature_type: string
}

interface RetrieveFeature {
  properties: {
    name: string
    full_address?: string
    place_formatted?: string
    coordinates: { latitude: number; longitude: number }
    context?: {
      place?: { name: string }
      region?: { name: string }
    }
  }
}

const TOKEN = (import.meta.env.VITE_MAPBOX_TOKEN as string | undefined) || ''
const SEARCH_DEBOUNCE_MS = 350
const RESULT_LIMIT = 6
const MIN_QUERY_LENGTH = 3
// Every hotel this admin manages is domestic (B2/B3 scope) -- biasing to VN/vi
// keeps e.g. "Hội An" from resolving to a same-named place outside Vietnam.
const COUNTRY = 'vn'
const LANGUAGE = 'vi'

function toGeocodeResult(feature: RetrieveFeature): GeocodeResult {
  const { properties } = feature
  const city = properties.context?.place?.name ?? properties.context?.region?.name ?? ''
  return {
    address: properties.full_address ?? properties.place_formatted ?? properties.name,
    city,
    latitude: properties.coordinates.latitude,
    longitude: properties.coordinates.longitude,
  }
}

/** address-geocode-search.tsx -- "Địa chỉ" input, upgraded from plain text
 * to a live search like Google Maps' place box: typing debounces into the
 * Mapbox Search Box API's /suggest (addresses AND named places/POIs --
 * unlike the plain Geocoding API's /forward, which dropped POI results in
 * v6), picking a suggestion calls /retrieve for its coordinates and fills
 * address/city/lat/lng in one shot via `onSelect` so MapLocationPicker's
 * marker moves too. Typing without picking a suggestion still just edits
 * free text (`onChange`) -- this never forces a selection, matching how the
 * field behaved before.
 *
 * Search Box billing is per session (a suggest→retrieve round trip), not
 * per keystroke, so `sessionTokenRef` holds one UUID across a burst of
 * suggest calls and is reset once a retrieve completes -- reusing it past
 * that point would just keep billing keystrokes into an already-closed
 * session. REST fetch instead of the @mapbox/search-js-core SDK so it
 * doesn't add a dependency beyond the mapbox-gl already used for the map. */
export function AddressGeocodeSearch({ id, value, onChange, onSelect, placeholder }: AddressGeocodeSearchProps) {
  const [open, setOpen] = useState(false)
  const [results, setResults] = useState<Suggestion[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(false)
  const sessionTokenRef = useRef<string | null>(null)
  // Selecting a suggestion writes the picked address straight into `value`
  // via onSelect -> parent onChange; without this guard that value change
  // would immediately re-trigger a search for the text we just picked.
  const skipNextSearchRef = useRef(false)

  useEffect(() => {
    if (!TOKEN || !open) return
    if (skipNextSearchRef.current) {
      skipNextSearchRef.current = false
      return
    }
    const q = value.trim()
    if (q.length < MIN_QUERY_LENGTH) {
      setResults([])
      setLoading(false)
      setError(false)
      return
    }
    if (!sessionTokenRef.current) sessionTokenRef.current = crypto.randomUUID()
    let cancelled = false
    setLoading(true)
    setError(false)
    const timer = setTimeout(() => {
      const url =
        `https://api.mapbox.com/search/searchbox/v1/suggest?q=${encodeURIComponent(q)}` +
        `&session_token=${sessionTokenRef.current}&access_token=${TOKEN}&limit=${RESULT_LIMIT}&country=${COUNTRY}&language=${LANGUAGE}`
      fetch(url)
        .then((res) => {
          if (!res.ok) throw new Error(`suggest request failed: ${res.status}`)
          return res.json() as Promise<{ suggestions: Suggestion[] }>
        })
        .then((data) => {
          if (cancelled) return
          setResults(data.suggestions ?? [])
          setLoading(false)
        })
        .catch((err: unknown) => {
          console.error('[address-geocode-search] suggest request failed:', err)
          if (cancelled) return
          setError(true)
          setLoading(false)
        })
    }, SEARCH_DEBOUNCE_MS)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [value, open])

  function select(suggestion: Suggestion) {
    const sessionToken = sessionTokenRef.current
    if (!sessionToken) return
    setOpen(false)
    setResults([])
    setLoading(true)
    const url = `https://api.mapbox.com/search/searchbox/v1/retrieve/${suggestion.mapbox_id}?session_token=${sessionToken}&access_token=${TOKEN}`
    fetch(url)
      .then((res) => {
        if (!res.ok) throw new Error(`retrieve request failed: ${res.status}`)
        return res.json() as Promise<{ features: RetrieveFeature[] }>
      })
      .then((data) => {
        setLoading(false)
        const feature = data.features?.[0]
        if (!feature) return
        skipNextSearchRef.current = true
        onSelect(toGeocodeResult(feature))
      })
      .catch((err: unknown) => {
        console.error('[address-geocode-search] retrieve request failed:', err)
        setLoading(false)
      })
      .finally(() => {
        sessionTokenRef.current = null
      })
  }

  const showDropdown = open && TOKEN !== '' && value.trim().length >= MIN_QUERY_LENGTH

  return (
    <div style={{ position: 'relative' }}>
      <Input
        id={id}
        maxLength={500}
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === 'Escape') {
            setOpen(false)
            e.currentTarget.blur()
          }
        }}
        onBlur={() => setOpen(false)}
        autoComplete="off"
      />
      {showDropdown && (
        <div
          style={{
            position: 'absolute',
            top: '100%',
            left: 0,
            right: 0,
            zIndex: 20,
            marginTop: 4,
            maxHeight: 260,
            overflowY: 'auto',
            background: 'var(--g2)',
            border: '1px solid var(--stroke)',
            borderRadius: 10,
            boxShadow: '0 8px 24px rgba(0,0,0,.24)',
            padding: 4,
          }}
        >
          {loading && <div style={{ padding: '8px 10px', fontSize: 12, color: 'var(--t4)' }}>Đang tìm…</div>}
          {!loading && error && (
            <div style={{ padding: '8px 10px', fontSize: 12, color: 'var(--t4)' }}>Không thể tìm kiếm lúc này</div>
          )}
          {!loading && !error && results.length === 0 && (
            <div style={{ padding: '8px 10px', fontSize: 12, color: 'var(--t4)' }}>Không tìm thấy</div>
          )}
          {!loading &&
            !error &&
            results.map((suggestion) => (
              <button
                key={suggestion.mapbox_id}
                type="button"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => select(suggestion)}
                style={{
                  display: 'block',
                  width: '100%',
                  textAlign: 'left',
                  padding: '8px 10px',
                  fontSize: 13,
                  background: 'transparent',
                  border: 'none',
                  borderRadius: 8,
                  cursor: 'pointer',
                }}
              >
                <div>{suggestion.name}</div>
                {(suggestion.place_formatted || suggestion.full_address) && (
                  <div style={{ fontSize: 11, color: 'var(--t4)' }}>
                    {suggestion.place_formatted ?? suggestion.full_address}
                  </div>
                )}
              </button>
            ))}
        </div>
      )}
    </div>
  )
}
