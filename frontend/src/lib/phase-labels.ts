/**
 * phase-labels.ts — maps opaque backend `phase.key` values to i18n keys.
 *
 * The backend never sends display text (docs/chat_api_contract.md §Streaming:
 * "phase.key là khoá đục"). An unknown key (backend ships a new one before the
 * frontend knows its label) must be ignored silently — never render the raw
 * key string on screen.
 */

import type { PhaseKey } from '../types'

const PHASE_LABEL_I18N_KEY: Record<PhaseKey, string> = {
  received: 'phaseReceived',
  routing: 'phaseRouting',
  compacting_history: 'phaseCompactingHistory',
  intake_check: 'phaseIntakeCheck',
  hotel_search: 'phaseHotelSearch',
  itinerary_build: 'phaseItineraryBuild',
  routing_legs: 'phaseRoutingLegs',
  persisting: 'phasePersisting',
  generating: 'phaseGenerating',
}

/** Returns the i18n key for a phase key, or null for an unrecognized key. */
export function phaseLabelKey(key: string): string | null {
  return (PHASE_LABEL_I18N_KEY as Record<string, string>)[key] ?? null
}
