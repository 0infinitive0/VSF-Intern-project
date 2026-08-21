import { describe, expect, it } from 'vitest'
import { activeAmenityPills, displayAmenityLabels, filterAndSortHotels, hotelPriceBounds, resolveAmenityCatalog, roundedPriceSliderBounds, sortAmenityLabels, type HotelFilterState } from './hotel-filters'
import type { AmenityCatalogOption, HotelOption, PreferencePayload } from '../types'
import { hotelOption } from '../test-fixtures'

const HOTELS: HotelOption[] = [
  hotelOption({ index: 1, name: 'Recommended first', average_nightly_price: 2_000_000, star_rating: 5, amenities: ['breakfast'], match_score: 0.95 }),
  hotelOption({ index: 2, name: 'Budget stay', average_nightly_price: 900_000, star_rating: 4, amenities: ['swimming_pool'], match_score: 0.8 }),
  hotelOption({ index: 3, name: 'Price on request', star_rating: 3, amenities: ['breakfast', 'swimming_pool'], match_score: 0.7 }),
]

const DEFAULT_FILTERS: HotelFilterState = {
  minPrice: null,
  maxPrice: null,
  minStars: null,
  preferenceIds: [],
  sortOrder: 'match',
}

describe('filterAndSortHotels', () => {
  it('preserves the backend order when filters are cleared', () => {
    expect(filterAndSortHotels(HOTELS, DEFAULT_FILTERS).map((hotel) => hotel.index)).toEqual([1, 2, 3])
  })

  it('applies price, minimum-star, and API preference filters without excluding unknown prices', () => {
    const result = filterAndSortHotels(HOTELS, {
      ...DEFAULT_FILTERS,
      maxPrice: 1_000_000,
      minStars: 3,
      preferenceIds: ['breakfast'],
    })

    expect(result.map((hotel) => hotel.index)).toEqual([3])
  })

  it('filters by canonical amenity IDs', () => {
    const result = filterAndSortHotels(
      [hotelOption({ index: 4, name: 'Catalog-only wifi', amenities: ['wifi'] })],
      { ...DEFAULT_FILTERS, preferenceIds: ['wifi'] },
    )

    expect(result.map((hotel) => hotel.index)).toEqual([4])
  })

  it('does not use the removed legacy preferences field as an amenity source', () => {
    const legacyOnlyHotel = Object.assign(hotelOption({ index: 5, amenities: [] }), { preferences: ['wifi'] })

    expect(filterAndSortHotels([legacyOnlyHotel], { ...DEFAULT_FILTERS, preferenceIds: ['wifi'] })).toEqual([])
  })

  it('applies both ends of the price range', () => {
    const result = filterAndSortHotels(HOTELS, { ...DEFAULT_FILTERS, minPrice: 1_000_000, maxPrice: 2_000_000 })

    expect(result.map((hotel) => hotel.index)).toEqual([1, 3])
  })

  it('sorts known prices before hotels whose price is unavailable', () => {
    const result = filterAndSortHotels(HOTELS, { ...DEFAULT_FILTERS, sortOrder: 'priceAsc' })

    expect(result.map((hotel) => hotel.index)).toEqual([2, 1, 3])
  })

  it('uses API price bounds when present and otherwise derives them from hotel options', () => {
    expect(hotelPriceBounds(HOTELS, 500_000, 3_000_000)).toEqual({ min: 500_000, max: 3_000_000 })
    expect(hotelPriceBounds(HOTELS, null, null)).toEqual({ min: 900_000, max: 2_000_000 })
  })

  it('rounds slider bounds to VND 10,000 increments', () => {
    expect(roundedPriceSliderBounds({ min: 803_123, max: 2_507_888 })).toEqual({ min: 800_000, max: 2_510_000 })
  })
})

describe('activeAmenityPills', () => {
  const active: PreferencePayload[] = [
    { id: 'swimming_pool', label: 'generated pool label' },
    { id: 'breakfast', label: 'generated breakfast label' },
  ]
  const catalog: AmenityCatalogOption[] = [
    { id: 'swimming_pool', label_vi: 'Hồ bơi', label_en: 'Swimming pool', category: 'wellness', icon_key: 'pool' },
    { id: 'breakfast', label_vi: 'Bao gồm bữa sáng', label_en: 'Breakfast included', category: 'food', icon_key: 'breakfast' },
    { id: 'wifi', label_vi: 'Wi-Fi', label_en: 'Wi-Fi', category: 'connectivity', icon_key: 'wifi' },
  ]

  it('shows only user-requested hotel amenities and resolves their labels from the catalog', () => {
    expect(activeAmenityPills(active, catalog, 'vi')).toEqual([
      { id: 'swimming_pool', label: 'Hồ bơi' },
      { id: 'breakfast', label: 'Bao gồm bữa sáng' },
    ])
  })

  it('retains the active payload label while the catalog is unavailable', () => {
    expect(activeAmenityPills(active, null, 'en')).toEqual(active)
  })
})

describe('displayAmenityLabels', () => {
  const details: AmenityCatalogOption[] = [
    { id: 'swimming_pool', label_vi: 'Hồ bơi', label_en: 'Swimming pool', category: 'wellness', icon_key: 'pool' },
    { id: 'wifi', label_vi: 'Wi-Fi', label_en: 'Wi-Fi', category: 'connectivity', icon_key: 'wifi' },
  ]

  it('uses joined amenity metadata in the selected language', () => {
    expect(displayAmenityLabels(['swimming_pool', 'wifi'], details, 'en')).toEqual(['Swimming pool', 'Wi-Fi'])
    expect(displayAmenityLabels(['swimming_pool', 'wifi'], details, 'vi')).toEqual(['Hồ bơi', 'Wi-Fi'])
  })
})

describe('resolveAmenityCatalog', () => {
  const fallback: AmenityCatalogOption[] = [
    { id: 'swimming_pool', label_vi: 'Hồ bơi', label_en: 'Swimming pool', category: 'wellness', icon_key: 'pool' },
  ]
  const fullCatalog: AmenityCatalogOption[] = [
    ...fallback,
    { id: 'kitchen', label_vi: 'Bếp', label_en: 'Kitchen', category: 'room_comfort', icon_key: 'kitchen' },
  ]

  it('uses the full session catalog when it has loaded, including room-only entries', () => {
    expect(resolveAmenityCatalog(fullCatalog, fallback)).toBe(fullCatalog)
    expect(displayAmenityLabels(['kitchen'], resolveAmenityCatalog(fullCatalog, fallback), 'en')).toEqual(['Kitchen'])
  })

  it('retains the per-turn catalog when the session catalog request fails', () => {
    expect(resolveAmenityCatalog(null, fallback)).toBe(fallback)
  })

  it('treats an empty cache response as unavailable instead of hiding the fallback', () => {
    expect(resolveAmenityCatalog([], fallback)).toBe(fallback)
  })
})

describe('sortAmenityLabels', () => {
  it('deduplicates and sorts localized amenity labels alphabetically', () => {
    expect(sortAmenityLabels(['Wi-Fi', 'Bữa sáng', 'Hồ bơi', 'Wi-Fi'], 'vi')).toEqual([
      'Bữa sáng',
      'Hồ bơi',
      'Wi-Fi',
    ])
  })
})
