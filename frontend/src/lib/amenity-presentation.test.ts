import { describe, expect, it } from 'vitest'
import { amenityPresentationItems } from './amenity-presentation'

describe('amenityPresentationItems', () => {
  it('marks only room amenities that satisfy active required preferences', () => {
    expect(amenityPresentationItems(
      ['wifi', 'swimming_pool', 'tv'],
      [
        { id: 'wifi', label_vi: 'Wi-Fi', label_en: 'Wi-Fi', category: 'connectivity', icon_key: null },
        { id: 'swimming_pool', label_vi: 'Hồ bơi', label_en: 'Swimming pool', category: 'leisure', icon_key: null },
      ],
      'vi',
      ['wifi', 'swimming_pool'],
    )).toEqual([
      { id: 'wifi', label: 'Wi-Fi', matchesPreference: true },
      { id: 'swimming_pool', label: 'Hồ bơi', matchesPreference: true },
      { id: 'tv', label: 'tv', matchesPreference: false },
    ])
  })
})
