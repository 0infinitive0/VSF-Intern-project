/**
 * activity-name.ts — splits the backend's composed `DayItem.activity` string
 * into the place's own name and the sentence describing what happens there.
 *
 * `DayItem` has no separate "venue name" field (trip_formatter.py only emits
 * activity/kind/start_time/end_time/coordinates/route_to_next — see plan.md's
 * "Phần chưa làm" #24). `activity` is the only real string that contains the
 * name, and it is always ONE of a small closed set of Vietnamese templates —
 * always Vietnamese regardless of UI language, since `_activity_label`
 * (backend/src/services/trip_scheduler.py:1347-1373) and
 * `_local_exploration_item` (same file, line 1344) take no language
 * parameter. Matching those exact templates — not a fuzzy heuristic — is
 * what makes stripping the prefix safe: every one is deterministic backend
 * output, never free-form AI text.
 */

// One entry per `_activity_label` branch, plus `_local_exploration_item`'s
// fallback. Order doesn't affect correctness (no two prefixes share the same
// leading words, so none can shadow another), kept roughly longest-first for
// readability.
const ACTIVITY_PREFIXES = [
  'Ăn trưa đã bao gồm và nghỉ ngơi tại ',
  'Ăn trưa và nghỉ ngơi tại ',
  'Tự do khám phá khu vực quanh ',
  'Ăn sáng đã bao gồm tại ',
  'Ăn tối đã bao gồm tại ',
  'Nghỉ ngơi tại ',
  'Thư giãn tại ',
  'Dạo chơi tại ',
  'Ăn sáng tại ',
  'Ăn trưa tại ',
  'Ăn tối tại ',
  'Tham quan ',
] as const

/**
 * The place's own name, with the activity sentence's lead-in stripped —
 * "Ăn trưa tại NHÀ HÀNG NGON" -> "NHÀ HÀNG NGON". Falls back to the full
 * string unchanged when no known template matches (never invents a name).
 */
export function placeNameFromActivity(activity: string | null | undefined): string {
  // `ItineraryItem.activity` is genuinely nullable on the wire (trip_formatter
  // passes the DB value straight through), and an item with no activity has no
  // place name to extract — '' is the honest answer, not a crash.
  if (!activity) return ''
  for (const prefix of ACTIVITY_PREFIXES) {
    if (activity.startsWith(prefix)) return activity.slice(prefix.length)
  }
  return activity
}
