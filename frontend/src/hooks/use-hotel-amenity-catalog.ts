import { useEffect, useState } from 'react'
import { getHotelAmenityCatalog } from '../api/amenity-catalog-client'
import type { AmenityCatalogOption } from '../types'

/** Loads the approved shared catalog once; null retains the legacy-response fallback. */
export function useHotelAmenityCatalog(): AmenityCatalogOption[] | null {
  const [catalog, setCatalog] = useState<AmenityCatalogOption[] | null>(null)

  useEffect(() => {
    let cancelled = false
    void getHotelAmenityCatalog().then((entries) => {
      if (!cancelled && entries != null) setCatalog(entries)
    })
    return () => { cancelled = true }
  }, [])

  return catalog
}
