import { useEffect, useRef, useState } from 'react'
import {
  composeIntakeMessage,
  type IntakeFormState,
} from '../lib/compose-intake-message'
import {
  companionKeyFromWireValueVi,
  dayRhythmKeyFromWireValueVi,
  paceKeyFromWireValueVi,
  preferenceKeyFromWireValueVi,
  type DayRhythmKey,
  type PreferenceKey,
} from '../lib/intake-options'
import { currentIntakeField } from '../lib/next-intake-field'
import type { IntakeStatus } from '../types'
import IntakeDestinationChips from './intake-destination-chips'
import IntakePeopleStepper from './intake-people-stepper'
import IntakeDateRange from './intake-date-range'
import IntakeBudgetTiers from './intake-budget-tiers'
import IntakePreferenceChips from './intake-preference-chips'

// intake.people is a formatted string like "2 người" (trip_intake.py), not a
// bare number — pull the leading count back out.
function parseLeadingCount(value: string | null | undefined): number | null {
  if (!value) return null
  const match = /^\d+/.exec(value)
  return match ? Number(match[0]) : null
}

/**
 * IntakeParametersForm — thin orchestrator (phase-06). Renders exactly ONE
 * intake widget at a time, driven by `currentIntakeField` (which walks the real
 * `intake.missing` keys in widget order and surfaces optional budget/
 * preferences only once the required fields are filled). The widgets collect
 * locally; the final widget's button submits ONE full composeIntakeMessage
 * sentence — byte-identical to the pre-refactor wire protocol (regression
 * guarded by compose-intake-message.test.ts).
 *
 * Pre-fills from the `intake` snapshot once (a user who already answered via
 * plain chat before the form loaded is not asked to redo those fields).
 */
export default function IntakeParametersForm({
  intake,
  onSubmit,
  disabled,
}: {
  intake: IntakeStatus | null
  onSubmit: (message: string) => void
  disabled: boolean
}) {
  const [form, setForm] = useState<IntakeFormState>({
    destination: '',
    startDate: '',
    endDate: '',
    guests: 0,
    budget: '',
    preferences: [],
    companions: '',
    pace: '',
    dayRhythm: [],
    notes: '',
  })
  const seededRef = useRef(false)

  // Pre-fill from the intake snapshot once (null → non-null first time), never
  // on every render — re-seeding would clobber in-progress edits.
  useEffect(() => {
    if (!intake || seededRef.current) return
    seededRef.current = true
    const guests = parseLeadingCount(intake.people)
    setForm((prev) => ({
      destination: intake.destination || prev.destination,
      startDate: intake.start_date || prev.startDate,
      endDate: intake.end_date || prev.endDate,
      guests: guests ?? prev.guests,
      budget: prev.budget,
      preferences:
        (intake.preferences?.length ?? 0) > 0
          ? intake.preferences
              .map(preferenceKeyFromWireValueVi)
              .filter((key): key is PreferenceKey => key !== null)
          : prev.preferences,
      companions:
        companionKeyFromWireValueVi(intake.companions || '') || prev.companions,
      pace: paceKeyFromWireValueVi(intake.pace || '') || prev.pace,
      dayRhythm:
        (intake.day_rhythm?.length ?? 0) > 0
          ? intake.day_rhythm
              .map(dayRhythmKeyFromWireValueVi)
              .filter((key): key is DayRhythmKey => key !== null)
          : prev.dayRhythm,
      notes: intake.notes || prev.notes,
    }))
  }, [intake])

  const destinations = intake?.available_destinations ?? []
  const budgetOptions = intake?.budget_options ?? []

  const activeField = currentIntakeField(intake, form)

  const togglePreference = (key: PreferenceKey) => {
    setForm((prev) => ({
      ...prev,
      preferences: prev.preferences.includes(key)
        ? prev.preferences.filter((p) => p !== key)
        : [...prev.preferences, key],
    }))
  }

  // Required fields are filled and the final optional card is confirmed — submit
  // the full sentence through the unchanged composeIntakeMessage.
  const submitAll = () => onSubmit(composeIntakeMessage(form))

  // The preferences card is terminal and stays mounted (with its own submit
  // button) until submitAll actually sends — see currentIntakeField's doc.
  if (!intake) return null
  if (disabled) return null

  switch (activeField) {
    case 'destination':
      return (
        <IntakeDestinationChips
          destinations={destinations}
          selected={form.destination}
          onPick={(destination) => setForm((prev) => ({ ...prev, destination }))}
          disabled={false}
        />
      )
    case 'people':
      return (
        <IntakePeopleStepper
          value={form.guests}
          onCommit={(guests) => setForm((prev) => ({ ...prev, guests }))}
          disabled={false}
        />
      )
    case 'dates':
      return (
        <IntakeDateRange
          start={form.startDate}
          end={form.endDate}
          onCommit={({ start, end }) =>
            setForm((prev) => ({ ...prev, startDate: start, endDate: end }))
          }
          disabled={false}
        />
      )
    case 'budget':
      return (
        <IntakeBudgetTiers
          options={budgetOptions}
          selected={form.budget}
          onCommit={(budget) => setForm((prev) => ({ ...prev, budget }))}
          disabled={false}
        />
      )
    case 'preferences':
      return (
        <IntakePreferenceChips
          selected={form.preferences}
          onToggle={togglePreference}
          onSubmit={submitAll}
          disabled={false}
        />
      )
    default:
      return null
  }
}
