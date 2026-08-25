import { describe, expect, it } from 'vitest'
import { AMENITY_CATEGORY_LABELS, AMENITY_CATEGORY_ORDER, categoryLabel } from './amenity-categories'

// Mirrors AMENITY_CATEGORIES in backend/src/services/amenity_catalog.py --
// keep in sync manually (no shared source across the Python/TS boundary).
const EXPECTED_LABEL_BY_CATEGORY: Record<string, string> = {
  accessibility: 'Hỗ trợ người khuyết tật',
  business: 'Công tác & Hội nghị',
  connectivity: 'Kết nối & Internet',
  facility: 'Cơ sở vật chất',
  family: 'Gia đình & Trẻ em',
  food: 'Ăn uống',
  general: 'Tổng quan',
  language: 'Ngôn ngữ hỗ trợ',
  outdoor: 'Ngoài trời',
  policies: 'Chính sách',
  room_comfort: 'Tiện nghi phòng',
  safety: 'An ninh & An toàn',
  transport: 'Đưa đón & Di chuyển',
  wellness: 'Bể bơi & Spa',
}

describe('categoryLabel', () => {
  it('mirrors all 14 backend AMENITY_CATEGORIES values (fails if the backend enum grows/shrinks)', () => {
    expect(Object.keys(EXPECTED_LABEL_BY_CATEGORY)).toHaveLength(14)
    expect(Object.keys(AMENITY_CATEGORY_LABELS)).toHaveLength(14)
  })

  it('maps every known backend category to its exact Vietnamese label', () => {
    for (const [category, expectedLabel] of Object.entries(EXPECTED_LABEL_BY_CATEGORY)) {
      expect(categoryLabel(category)).toBe(expectedLabel)
    }
  })

  it('falls back to the raw category string for an unrecognized category instead of dropping it', () => {
    expect(categoryLabel('some_future_category')).toBe('some_future_category')
  })

  it('AMENITY_CATEGORY_ORDER lists exactly the known categories, each once', () => {
    expect(new Set(AMENITY_CATEGORY_ORDER)).toEqual(new Set(Object.keys(EXPECTED_LABEL_BY_CATEGORY)))
    expect(AMENITY_CATEGORY_ORDER).toHaveLength(14)
  })
})
