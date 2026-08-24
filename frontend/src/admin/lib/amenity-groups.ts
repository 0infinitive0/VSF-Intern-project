/**
 * amenity-groups.ts — L33 (phase-09-hotel-edit.md). `amenity_catalog.category`
 * is a fixed 14-value enum (`AMENITY_CATEGORIES` in
 * backend/src/services/amenity_catalog.py), not the 5 free-form Vietnamese
 * group names the design artboard shows. This maps the 14 real categories to
 * 5 display groups: wellness/food/transport/family get their own group, the
 * remaining 10 (accessibility, business, connectivity, facility, general,
 * language, outdoor, policies, room_comfort, safety) fall into "Tiện ích
 * chung". `groupLabelForCategory` defaults unknown categories to "Tiện ích
 * chung" too, rather than throwing or dropping them, so a category added to
 * the catalog after this file was written still renders somewhere instead of
 * silently vanishing from the tab -- see amenity-groups.test.ts's coverage
 * assertion, which is the actual guarantee that no known category is lost.
 */

export const AMENITY_CATEGORY_GROUPS: Record<string, string> = {
  wellness: 'Bể bơi & Spa',
  food: 'Ăn uống',
  transport: 'Đưa đón & Di chuyển',
  family: 'Gia đình & Trẻ em',
}

export const GENERAL_GROUP_LABEL = 'Tiện ích chung'

/** Display order for the tab -- unmapped categories always land in the last group. */
export const AMENITY_GROUP_ORDER = ['Bể bơi & Spa', 'Ăn uống', 'Đưa đón & Di chuyển', 'Gia đình & Trẻ em', GENERAL_GROUP_LABEL]

export function groupLabelForCategory(category: string): string {
  return AMENITY_CATEGORY_GROUPS[category] ?? GENERAL_GROUP_LABEL
}
