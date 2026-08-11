import type { StageView } from './derive-stage'

export interface PhaseAvailability {
  intakeComplete: boolean
  hotelOptionsAvailable: boolean
  hotelPicked: boolean
}

/** Phase switching is local; only confirmations submit chat messages. */
export function navigationTarget(target: Extract<StageView, 'intake' | 'hotels' | 'workspace'>, availability: PhaseAvailability) {
  if (target === 'intake') return target
  if (target === 'hotels') return availability.intakeComplete && availability.hotelOptionsAvailable ? target : null
  return availability.hotelPicked ? target : null
}
