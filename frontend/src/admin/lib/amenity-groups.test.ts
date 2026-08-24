import { describe, expect, it } from 'vitest'
import { AMENITY_GROUP_ORDER, GENERAL_GROUP_LABEL, groupLabelForCategory } from './amenity-groups'

// Mirrors AMENITY_CATEGORIES in backend/src/services/amenity_catalog.py --
// keep in sync manually (no shared source across the Python/TS boundary).
// The expected group for each is spelled out explicitly below: asserting
// only `AMENITY_GROUP_ORDER.toContain(...)` would pass trivially for ANY
// category (including a wrong or made-up one), since
// groupLabelForCategory's `??` fallback always returns a value from that
// same array. Explicit expected values are the only thing that actually
// pins the 4-named/10-general split L33 specifies.
const EXPECTED_GROUP_BY_CATEGORY: Record<string, string> = {
  wellness: 'Bể bơi & Spa',
  food: 'Ăn uống',
  transport: 'Đưa đón & Di chuyển',
  family: 'Gia đình & Trẻ em',
  accessibility: GENERAL_GROUP_LABEL,
  business: GENERAL_GROUP_LABEL,
  connectivity: GENERAL_GROUP_LABEL,
  facility: GENERAL_GROUP_LABEL,
  general: GENERAL_GROUP_LABEL,
  language: GENERAL_GROUP_LABEL,
  outdoor: GENERAL_GROUP_LABEL,
  policies: GENERAL_GROUP_LABEL,
  room_comfort: GENERAL_GROUP_LABEL,
  safety: GENERAL_GROUP_LABEL,
}

describe('groupLabelForCategory', () => {
  it('mirrors all 14 backend AMENITY_CATEGORIES values (fails if the backend enum grows/shrinks)', () => {
    expect(Object.keys(EXPECTED_GROUP_BY_CATEGORY)).toHaveLength(14)
  })

  it('maps every known backend category to its exact designed group (L33)', () => {
    for (const [category, expectedGroup] of Object.entries(EXPECTED_GROUP_BY_CATEGORY)) {
      expect(groupLabelForCategory(category)).toBe(expectedGroup)
    }
  })

  it('falls back to "Tiện ích chung" for an unrecognized category instead of dropping it', () => {
    expect(groupLabelForCategory('some_future_category')).toBe(GENERAL_GROUP_LABEL)
  })

  it('every group label used above is a real entry in AMENITY_GROUP_ORDER', () => {
    for (const group of Object.values(EXPECTED_GROUP_BY_CATEGORY)) {
      expect(AMENITY_GROUP_ORDER).toContain(group)
    }
  })
})
