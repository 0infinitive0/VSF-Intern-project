import { describe, expect, it } from 'vitest'
import { filterAndSortHotels, hotelPriceBounds, roundedPriceSliderBounds, type HotelFilterState } from './hotel-filters'
import type { HotelOption } from '../types'

const HOTELS: HotelOption[] = [
  { index: 1, name: 'Recommended first', average_nightly_price: 2_000_000, star_rating: 5, preferences: ['breakfast'], match_score: 0.95 },
  { index: 2, name: 'Budget stay', average_nightly_price: 900_000, star_rating: 4, preferences: ['pool'], match_score: 0.8 },
  { index: 3, name: 'Price on request', star_rating: 3, preferences: ['breakfast', 'pool'], match_score: 0.7 },
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

  it('filters by canonical amenity IDs even when the API did not mark them as preferences', () => {
    const result = filterAndSortHotels(
      [{ index: 4, name: 'Catalog-only wifi', amenities: ['wifi'], preferences: [] }],
      { ...DEFAULT_FILTERS, preferenceIds: ['wifi'] },
    )

    expect(result.map((hotel) => hotel.index)).toEqual([4])
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
