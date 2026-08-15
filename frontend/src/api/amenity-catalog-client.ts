import type { AmenityCatalogOption } from '../types'

const BASE = (import.meta.env.VITE_API_BASE || '') + '/api/v1'

/** Returns null when the catalog service is unavailable so existing UI can degrade safely. */
export async function getHotelAmenityCatalog(): Promise<AmenityCatalogOption[] | null> {
  try {
    const response = await fetch(`${BASE}/hotel-amenities`)
    if (!response.ok) return null
    return (await response.json()) as AmenityCatalogOption[]
  } catch {
    return null
  }
}
