import { useEffect, useRef, useState } from 'react'
import {
  companionKeyFromWireValueVi,
  dayRhythmKeyFromWireValueVi,
  paceKeyFromWireValueVi,
  preferenceKeyFromWireValueVi,
  type DayRhythmKey,
  type PreferenceKey,
} from '../lib/intake-options'
import type { IntakeFormState } from '../lib/compose-intake-message'
import type { IntakeField } from '../lib/next-intake-field'
import type { IntakeStatus } from '../types'

// intake.people is a formatted string like "2 người" (trip_intake.py), not a
// bare number — pull the leading count back out.
function parseLeadingCount(value: string | null | undefined): number | null {
  if (!value) return null
  const match = /^\d+/.exec(value)
  return match ? Number(match[0]) : null
}

const EMPTY_FORM: IntakeFormState = {
  destination: '',
  startDate: '',
  endDate: '',
  guests: 0,
  budgetMinVnd: null,
  budgetMaxVnd: null,
  budgetSkipped: false,
  preferences: [],
  companions: '',
  pace: '',
  dayRhythm: [],
  notes: '',
}

/**
 * useIntakeForm — owns IntakeParametersForm's local state, lifted out so a
 * sibling (IntakeChecklist, via StageIntake) can read the same in-progress
 * answers instead of waiting for the one combined submit at the end of the
 * widget flow to round-trip through the backend.
 *
 * Pre-fills from the `intake` snapshot once (a user who already answered via
 * plain chat before the form loaded is not asked to redo those fields) —
 * moved verbatim from the old in-component effect, same seed-once semantics.
 */
export function useIntakeForm(intake: IntakeStatus | null) {
  const [form, setForm] = useState<IntakeFormState>(EMPTY_FORM)
  const seededRef = useRef(false)
  // Set when the user taps "Sửa" on an already-collected checklist row
  // (IntakeChecklist, via StageIntake) — forces IntakeParametersForm to show
  // that one field's widget out of progressive-disclosure order, pre-filled
  // with the current value. Cleared once the correction is sent.
  const [editingField, setEditingField] = useState<IntakeField | null>(null)

  useEffect(() => {
    if (!intake || seededRef.current) return
    seededRef.current = true
    const guests = parseLeadingCount(intake.people)
    setForm((prev) => ({
      destination: intake.destination || prev.destination,
      startDate: intake.start_date || prev.startDate,
      endDate: intake.end_date || prev.endDate,
      guests: guests ?? prev.guests,
      budgetMinVnd: prev.budgetMinVnd,
      budgetMaxVnd: prev.budgetMaxVnd,
      budgetSkipped: prev.budgetSkipped,
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

  const togglePreference = (key: PreferenceKey) => {
    setForm((prev) => ({
      ...prev,
      preferences: prev.preferences.includes(key)
        ? prev.preferences.filter((p) => p !== key)
        : [...prev.preferences, key],
    }))
  }

  // "New Trip" starts a fresh session (intake goes back to null) — this hook
  // now outlives that reset (it used to live inside IntakeParametersForm,
  // which unmounted and lost its state for free), so the caller must clear
  // it explicitly instead of carrying stale answers into the new session.
  const resetForm = () => {
    seededRef.current = false
    setForm(EMPTY_FORM)
    setEditingField(null)
  }

  return { form, setForm, togglePreference, resetForm, editingField, setEditingField }
}
