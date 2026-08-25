/**
 * amenity-categories.ts — L33 (phase-09-hotel-edit.md). `amenity_catalog.category`
 * is a fixed 14-value enum (`AMENITY_CATEGORIES` in
 * backend/src/services/amenity_catalog.py). This used to consolidate those 14
 * into 5 artboard display groups (a "Tiện ích chung" catch-all bucketed 10 of
 * them together); that consolidation is gone -- each category now gets its
 * own Vietnamese label and its own section, one-to-one with the backend enum.
 * `AMENITY_CATEGORY_ORDER` lists the 14 keys in the same order as the backend
 * frozenset so a diff against it is line-for-line. `categoryLabel`'s fallback
 * to the raw category string is a safety net for a category the DB gains
 * before this file is updated for it -- see amenity-categories.test.ts's
 * coverage assertion, which is the actual guarantee that no known category is
 * lost either way.
 */

export const AMENITY_CATEGORY_LABELS: Record<string, string> = {
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

/** Display order for the tab -- mirrors AMENITY_CATEGORIES' declaration order. */
export const AMENITY_CATEGORY_ORDER = Object.keys(AMENITY_CATEGORY_LABELS)

export function categoryLabel(category: string): string {
  return AMENITY_CATEGORY_LABELS[category] ?? category
}
