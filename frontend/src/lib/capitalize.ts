/**
 * capitalize.ts — uppercases only the first character of a display string,
 * leaving the rest untouched. Backend theme/preference labels are stored
 * lowercase on purpose (`_PREFERENCE_LABELS`, `backend/src/services/trip_intake.py`,
 * and free-text `daily_preferences.<day>.theme`) so they match the fixed set
 * and round-trip through comparisons unchanged; this is a display-only fix so
 * the same string still reads as a sentence lead-in ("Ẩm thực") in the UI.
 */
export function capitalizeFirst(value: string): string {
  return value ? value[0].toUpperCase() + value.slice(1) : value
}
