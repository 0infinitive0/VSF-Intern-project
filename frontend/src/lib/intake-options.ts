/**
 * intake-options.ts — the single place mapping a stable canonical key to:
 *   (a) the exact Vietnamese wire string the backend's closed sets expect, and
 *   (b) the i18n key for its display label.
 *
 * The wire values below are byte-identical to the backend closed sets
 * (source of truth per that file's own comment):
 *   - src/services/trip_intake.py:30-64 (_PREFERENCE_LABELS / _COMPANION_LABELS /
 *     _PACE_LABELS / _DAY_RHYTHM_LABELS)
 *
 * IntakeFormState stores these canonical keys, and composeIntakeMessage()
 * maps each key through the *_WIRE_VALUE_VI lookups — so the composed sentence
 * sent to the backend stays Vietnamese regardless of the UI language (a
 * deliberate decoupling of display label from wire value). The inverse lookup
 * helpers convert a server-sent Vietnamese snapshot back into keys for
 * pre-filling the form.
 */

export const PREFERENCE_KEYS = [
  'beach', 'culture', 'food', 'nature', 'history',
  'shopping', 'nightlife', 'kids', 'classic', 'cityscape',
] as const
export type PreferenceKey = (typeof PREFERENCE_KEYS)[number]

// Byte-identical to trip_intake.py:30-41 (_PREFERENCE_LABELS).
export const PREFERENCE_WIRE_VALUE_VI: Record<PreferenceKey, string> = {
  beach: 'biển',
  culture: 'văn hóa',
  food: 'ẩm thực',
  nature: 'thiên nhiên',
  history: 'lịch sử',
  shopping: 'mua sắm',
  nightlife: 'cuộc sống về đêm',
  kids: 'trẻ em',
  classic: 'cổ điển',
  cityscape: 'cảnh đô thị',
}

export const COMPANION_KEYS = ['solo', 'family', 'partner', 'friends', 'elderly'] as const
export type CompanionKey = (typeof COMPANION_KEYS)[number]
// Byte-identical to trip_intake.py:47-53 (_COMPANION_LABELS).
export const COMPANION_WIRE_VALUE_VI: Record<CompanionKey, string> = {
  solo: 'đi một mình',
  family: 'đi cùng gia đình',
  partner: 'đi cùng người yêu hoặc vợ chồng',
  friends: 'đi cùng bạn bè',
  elderly: 'có người lớn tuổi trong đoàn',
}

export const PACE_KEYS = ['packed', 'moderate', 'relaxed'] as const
export type PaceKey = (typeof PACE_KEYS)[number]
// Byte-identical to trip_intake.py:55-59 (_PACE_LABELS).
export const PACE_WIRE_VALUE_VI: Record<PaceKey, string> = {
  packed: 'dày đặc',
  moderate: 'vừa phải',
  relaxed: 'thư thái',
}

export const DAY_RHYTHM_KEYS = ['earlyStart', 'lateNight'] as const
export type DayRhythmKey = (typeof DAY_RHYTHM_KEYS)[number]
// Byte-identical to trip_intake.py:61-64 (_DAY_RHYTHM_LABELS).
export const DAY_RHYTHM_WIRE_VALUE_VI: Record<DayRhythmKey, string> = {
  earlyStart: 'bắt đầu sớm',
  lateNight: 'về khuya',
}

// Inverse lookups for pre-filling IntakeFormState from a server-sent
// (Vietnamese) intake snapshot. Return null for unknown values so callers can
// `.filter(Boolean)` and degrade gracefully rather than crash.
export function preferenceKeyFromWireValueVi(value: string): PreferenceKey | null {
  return (PREFERENCE_KEYS as readonly string[]).find(
    (key) => PREFERENCE_WIRE_VALUE_VI[key as PreferenceKey] === value,
  ) as PreferenceKey | null
}

export function companionKeyFromWireValueVi(value: string): CompanionKey | null {
  return (COMPANION_KEYS as readonly string[]).find(
    (key) => COMPANION_WIRE_VALUE_VI[key as CompanionKey] === value,
  ) as CompanionKey | null
}

export function paceKeyFromWireValueVi(value: string): PaceKey | null {
  return (PACE_KEYS as readonly string[]).find(
    (key) => PACE_WIRE_VALUE_VI[key as PaceKey] === value,
  ) as PaceKey | null
}

export function dayRhythmKeyFromWireValueVi(value: string): DayRhythmKey | null {
  return (DAY_RHYTHM_KEYS as readonly string[]).find(
    (key) => DAY_RHYTHM_WIRE_VALUE_VI[key as DayRhythmKey] === value,
  ) as DayRhythmKey | null
}