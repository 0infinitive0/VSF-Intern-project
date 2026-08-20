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
import { resyncField, serverAskedFieldFor, type IntakeField } from '../lib/next-intake-field'
import type { IntakeStatus } from '../types'

// intake.people is a formatted string like "2 người" (trip_intake.py), not a
// bare number — pull the leading count back out.
function parseLeadingCount(value: string | null | undefined): number | null {
  if (!value) return null
  const match = /^\d+/.exec(value)
  return match ? Number(match[0]) : null
}

export const EMPTY_INTAKE_FORM: IntakeFormState = {
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

function isBlank(value: unknown): boolean {
  return value == null || value === '' || (Array.isArray(value) && value.length === 0)
}

/**
 * Did the server CLEAR this slot on this snapshot — i.e. it held a value
 * before and holds none now?
 *
 * That transition is the only honest signal that the user asked to change the
 * field, and it is the one thing a single snapshot cannot express: "the server
 * never knew this" and "the server just dropped this" both arrive as null. The
 * first must keep the local answer (progressive disclosure fills the widget
 * without a chat turn, so the server legitimately doesn't know yet); the second
 * must discard it, or the widget silently re-submits the stale value the user
 * just asked to replace.
 */
function wasCleared(before: unknown, after: unknown): boolean {
  return !isBlank(before) && isBlank(after)
}

/**
 * Fold one server snapshot into the local form.
 *
 * Pure and exported so the merge rules are unit-testable without rendering the
 * hook (this project has no jsdom — see test-setup.ts).
 *
 * `editingField` is the one exemption: while the user has a field open via the
 * checklist's "Sửa" button, an incoming snapshot must not erase what they are
 * typing under their hands.
 */
export function mergeIntakeIntoForm(
  prev: IntakeFormState,
  intake: IntakeStatus,
  previousIntake: IntakeStatus | null,
  editingField: IntakeField | null,
): IntakeFormState {
  // Keep the previous local value unless the server just cleared that slot and
  // the user isn't mid-edit on the widget that owns it.
  function carry<T>(owner: IntakeField, cleared: boolean, previousValue: T, emptyValue: T): T {
    return cleared && editingField !== owner ? emptyValue : previousValue
  }

  const guests = parseLeadingCount(intake.people)
  const datesCleared =
    wasCleared(previousIntake?.start_date, intake.start_date) ||
    wasCleared(previousIntake?.end_date, intake.end_date)
  const budgetCleared =
    wasCleared(previousIntake?.min_price, intake.min_price) ||
    wasCleared(previousIntake?.max_price, intake.max_price)
  const preferencesCleared = wasCleared(previousIntake?.preferences, intake.preferences)

  return {
    destination:
      intake.destination ||
      carry('destination', wasCleared(previousIntake?.destination, intake.destination), prev.destination, ''),
    startDate: intake.start_date || carry('dates', datesCleared, prev.startDate, ''),
    endDate: intake.end_date || carry('dates', datesCleared, prev.endDate, ''),
    guests: guests ?? carry('people', wasCleared(previousIntake?.people, intake.people), prev.guests, 0),
    budgetMinVnd: intake.min_price ?? carry('budget', budgetCleared, prev.budgetMinVnd, null),
    budgetMaxVnd: intake.max_price ?? carry('budget', budgetCleared, prev.budgetMaxVnd, null),
    budgetSkipped: intake.budget_skipped ?? carry('budget', budgetCleared, prev.budgetSkipped, false),
    preferences:
      (intake.preferences?.length ?? 0) > 0
        ? intake.preferences
            .map(preferenceKeyFromWireValueVi)
            .filter((key): key is PreferenceKey => key !== null)
        : carry('preferences', preferencesCleared, prev.preferences, []),
    companions:
      companionKeyFromWireValueVi(intake.companions || '') ||
      carry('preferences', wasCleared(previousIntake?.companions, intake.companions), prev.companions, ''),
    pace:
      paceKeyFromWireValueVi(intake.pace || '') ||
      carry('preferences', wasCleared(previousIntake?.pace, intake.pace), prev.pace, ''),
    dayRhythm:
      (intake.day_rhythm?.length ?? 0) > 0
        ? intake.day_rhythm
            .map(dayRhythmKeyFromWireValueVi)
            .filter((key): key is DayRhythmKey => key !== null)
        : carry(
            'preferences',
            wasCleared(previousIntake?.day_rhythm, intake.day_rhythm),
            prev.dayRhythm,
            [],
          ),
    notes:
      intake.notes ||
      carry('preferences', wasCleared(previousIntake?.notes, intake.notes), prev.notes, ''),
  }
}

/**
 * useIntakeForm — owns IntakeParametersForm's local state, lifted out so a
 * sibling (IntakeChecklist, via StageIntake) can read the same in-progress
 * answers instead of waiting for the one combined submit at the end of the
 * widget flow to round-trip through the backend.
 *
 * Merges from every `intake` snapshot, not just the first (a user who
 * answers destination/people/dates/budget via plain chat — at any point
 * during the conversation, not only before the widget first mounted — is not
 * asked to redo those fields). Safe to re-run on every update: each field
 * keeps whatever the user already has locally (`prev.X`) and only fills in a
 * still-empty field from the newly-confirmed backend value, so an in-progress
 * local edit is never clobbered by a stale/unrelated intake update. Running
 * this only once (the original design) left any field answered via chat
 * *after* the form's first mount permanently stuck locally-empty — silently
 * dropping it from composeIntakeMessage's combined sentence and leaving the
 * backend re-asking the same still-missing field forever, even after the
 * terminal "Tìm khách sạn phù hợp" submit.
 *
 * The one case "keep whatever is local" gets wrong is a slot the server
 * CLEARED: the user asked to change that field, so the local copy is exactly
 * the stale value they are replacing. Comparing against the previous snapshot
 * is what tells that apart from a slot the server simply never had — see
 * mergeIntakeIntoForm.
 */
export function useIntakeForm(intake: IntakeStatus | null) {
  const [form, setForm] = useState<IntakeFormState>(EMPTY_INTAKE_FORM)
  // The snapshot the current `form` was last merged against — the baseline
  // `wasCleared` needs. A ref, not state: it must never trigger a re-render of
  // its own, and it is only ever read inside the merge below.
  const previousIntakeRef = useRef<IntakeStatus | null>(null)
  // Set when the user taps "Sửa" on an already-collected checklist row
  // (IntakeChecklist, via StageIntake) — forces IntakeParametersForm to show
  // that one field's widget out of progressive-disclosure order, pre-filled
  // with the current value. Cleared once the correction is sent.
  const [editingField, setEditingField] = useState<IntakeField | null>(null)
  // Best-effort guess at which field the most recent REAL backend reply is
  // about — `budget`/`preferences` are never in `intake.missing` (the
  // backend "gate", see next-intake-field.ts) so `resyncField`'s
  // nextIntakeField-based check can never catch a duplicate there. The
  // backend's own conversational flow (ask_slot.py) still asks about budget
  // by itself once dates/people are answered, in its own wording — right
  // next to the local widget's `intakeBudgetQuestion` bubble if nothing
  // suppresses it. Set once per fresh `intake` snapshot (never on a local
  // -only `setForm`, same as `previousIntakeRef`); ChatPanel suppresses the
  // local question when its active field matches this.
  const [serverAskedField, setServerAskedField] = useState<IntakeField | null>(null)

  useEffect(() => {
    if (!intake) return
    const previousIntake = previousIntakeRef.current
    previousIntakeRef.current = intake
    // `setForm`'s updater must stay pure (StrictMode double-invokes it to
    // check that) — the merged result is captured into this ref instead of
    // deciding the resync pin from inside the updater itself.
    const mergedRef: { current: IntakeFormState | null } = { current: null }
    setForm((prev) => {
      mergedRef.current = mergeIntakeIntoForm(prev, intake, previousIntake, editingField)
      return mergedRef.current
    })
    const merged = mergedRef.current
    if (!merged) return
    // Only ever evaluated here, once per NEW real backend turn (never on a
    // local-only widget tap, which doesn't touch `intake`) — see
    // resyncField's doc for why that's what makes this safe: a mismatch
    // found here means THIS turn's real reply is a still-open question the
    // widget rail has already answered-but-not-sent and walked past.
    const pin = resyncField(intake, merged, editingField)
    console.debug('useIntakeForm merge effect: pin', pin, 'editingField', editingField)
    if (pin) setEditingField(pin)
    setServerAskedField(serverAskedFieldFor(intake, merged, editingField))
    // `editingField` is deliberately not a dependency: it guards how THIS
    // snapshot merges, and re-running the merge when the user opens or closes
    // an edit would re-apply an already-folded-in snapshot against a stale
    // baseline (previousIntakeRef has moved on), clearing nothing but costing
    // a pointless render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
  // No seeded-flag to reset anymore — the merge effect above now re-runs on
  // every `intake` change, including the new session's first one.
  const resetForm = () => {
    setForm(EMPTY_INTAKE_FORM)
    setEditingField(null)
    setServerAskedField(null)
    // Drop the merge baseline too — otherwise the new session's first snapshot
    // would be diffed against the old session's, and every slot the old trip
    // had would read as "just cleared".
    previousIntakeRef.current = null
  }

  return { form, setForm, togglePreference, resetForm, editingField, setEditingField, serverAskedField }
}
