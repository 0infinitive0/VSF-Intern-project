import type { AmenityCatalogOption } from '../types'

export interface AmenityPresentationItem {
  id: string
  label: string
  matchesPreference: boolean
}

/**
 * Produce amenity chips from canonical IDs while retaining whether each one
 * satisfies an active required preference.  Keeping this as data lets both
 * hotel and room views use the same accessible visual state.
 */
export function amenityPresentationItems(
  amenityIds: string[],
  catalog: AmenityCatalogOption[],
  language: string,
  requiredAmenityIds: readonly string[] = [],
): AmenityPresentationItem[] {
  const byId = new Map(catalog.map((amenity) => [amenity.id, amenity]))
  const required = new Set(requiredAmenityIds)
  return amenityIds.map((id) => {
    const amenity = byId.get(id)
    return {
      id,
      label: amenity
        ? (language.startsWith('en') ? amenity.label_en || amenity.label_vi : amenity.label_vi || amenity.label_en)
        : id,
      matchesPreference: required.has(id),
    }
  })
}
