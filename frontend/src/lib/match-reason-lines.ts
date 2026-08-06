/**
 * match-reason-lines.ts — turns the backend's raw `match_reasons[]`
 * ({code, value}) into render-ready lines keyed by the `matchReason.*` i18n
 * catalog (phase-08 §"Lý do đề xuất").
 *
 * The catalog is closed-set on purpose: a backend that ships a NEW code the
 * frontend doesn't know yet is skipped silently rather than rendered as a raw
 * string — that is exactly what keeps the contract evolvable without breaking
 * the UI. `budget_fit` values arrive as a 0..1 fraction and are converted to a
 * percentage here so the locale strings stay numeric-interpolation only.
 */
import type { MatchReason } from '../types'

export interface MatchReasonLine {
  code: string
  value: string | number
}

const KNOWN_CODES = new Set([
  'budget_fit',
  'high_rating',
  'amenity_match',
  'star_rating',
  'strong_similarity',
  'near_center',
])

export function buildMatchReasonLines(reasons?: MatchReason[] | null): MatchReasonLine[] {
  if (!reasons) return []
  const lines: MatchReasonLine[] = []
  for (const reason of reasons) {
    if (!KNOWN_CODES.has(reason.code)) continue
    if (reason.code === 'budget_fit' && typeof reason.value === 'number') {
      const fraction = reason.value <= 1 ? reason.value : reason.value / 100
      lines.push({ code: reason.code, value: Math.round(fraction * 100) })
    } else {
      lines.push({ code: reason.code, value: reason.value })
    }
  }
  return lines
}
