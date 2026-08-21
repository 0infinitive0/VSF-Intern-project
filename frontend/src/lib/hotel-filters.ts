import type { AmenityCatalogOption, HotelOption, PreferencePayload } from '../types'

export type HotelSortOrder = 'match' | 'priceAsc' | 'priceDesc'

export const PRICE_SLIDER_STEP = 10_000

export interface HotelFilterState {
  minPrice: number | null
  maxPrice: number | null
  minStars: number | null
  preferenceIds: string[]
  sortOrder: HotelSortOrder
}

/** Resolve the user's active hotel-amenity IDs through the approved catalog. */
export function activeAmenityPills(
  activePreferences: PreferencePayload[],
  catalog: AmenityCatalogOption[] | null,
  language: string,
): PreferencePayload[] {
  const byId = new Map(catalog?.map((amenity) => [amenity.id, amenity]))
  return activePreferences.map((preference) => {
    const amenity = byId.get(preference.id)
    if (!amenity) return preference
    return {
      id: preference.id,
      label: language.startsWith('en') ? amenity.label_en || amenity.label_vi : amenity.label_vi || amenity.label_en,
    }
  })
}

/** Localize joined hotel amenity records without changing canonical filter IDs. */
export function displayAmenityLabels(
  amenityIds: string[],
  details: AmenityCatalogOption[],
  language: string,
): string[] {
  const byId = new Map(details.map((amenity) => [amenity.id, amenity]))
  return amenityIds.map((id) => {
    const amenity = byId.get(id)
    if (!amenity) return id
    return language.startsWith('en') ? amenity.label_en || amenity.label_vi : amenity.label_vi || amenity.label_en
  })
}

/** Prefer the session-wide catalog while retaining the existing per-turn fallback. */
export function resolveAmenityCatalog(
  catalog: AmenityCatalogOption[] | null,
  fallback: AmenityCatalogOption[],
): AmenityCatalogOption[] {
  return catalog && catalog.length > 0 ? catalog : fallback
}

/** Present a full amenity list deterministically in the active UI language. */
export function sortAmenityLabels(labels: string[], language: string): string[] {
  const locale = language.startsWith('vi') ? 'vi' : 'en'
  return [...new Set(labels.filter(Boolean))].sort(
    new Intl.Collator(locale, { sensitivity: 'base' }).compare,
  )
}

export function hotelPriceBounds(
  hotels: HotelOption[],
  apiMinPrice: number | null,
  apiMaxPrice: number | null,
): { min: number; max: number } | null {
  if (apiMinPrice != null && apiMaxPrice != null && apiMinPrice > 0 && apiMaxPrice >= apiMinPrice) {
    return { min: apiMinPrice, max: apiMaxPrice }
  }

  const prices = hotels
    .map((hotel) => hotel.average_nightly_price)
    .filter((price): price is number => price != null && price > 0)
  return prices.length > 0 ? { min: Math.min(...prices), max: Math.max(...prices) } : null
}

export function roundedPriceSliderBounds(bounds: { min: number; max: number }): { min: number; max: number } {
  return {
    min: Math.floor(bounds.min / PRICE_SLIDER_STEP) * PRICE_SLIDER_STEP,
    max: Math.ceil(bounds.max / PRICE_SLIDER_STEP) * PRICE_SLIDER_STEP,
  }
}

function hasPreference(hotel: HotelOption, preferenceId: string): boolean {
  return (hotel.amenities ?? []).includes(preferenceId)
}

function priceForSort(hotel: HotelOption, direction: HotelSortOrder): number {
  if (hotel.average_nightly_price != null && hotel.average_nightly_price > 0) {
    return hotel.average_nightly_price
  }
  return direction === 'priceAsc' ? Number.POSITIVE_INFINITY : Number.NEGATIVE_INFINITY
}

export function filterAndSortHotels(hotels: HotelOption[], filters: HotelFilterState): HotelOption[] {
  const filtered = hotels.filter((hotel) => {
    const priceMatches =
      hotel.average_nightly_price == null ||
      ((filters.minPrice == null || hotel.average_nightly_price >= filters.minPrice) &&
        (filters.maxPrice == null || hotel.average_nightly_price <= filters.maxPrice))
    const starsMatch = filters.minStars == null || (hotel.star_rating ?? 0) >= filters.minStars
    const preferencesMatch = filters.preferenceIds.every((preferenceId) => hasPreference(hotel, preferenceId))

    return priceMatches && starsMatch && preferencesMatch
  })

  if (filters.sortOrder === 'match') return filtered

  return [...filtered].sort((left, right) => {
    const difference = priceForSort(left, filters.sortOrder) - priceForSort(right, filters.sortOrder)
    return filters.sortOrder === 'priceAsc' ? difference : -difference
  })
}
