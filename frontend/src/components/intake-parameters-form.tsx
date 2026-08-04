import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  composeIntakeMessage,
  type IntakeFormState,
} from '../lib/compose-intake-message'
import {
  COMPANION_KEYS,
  DAY_RHYTHM_KEYS,
  PACE_KEYS,
  PREFERENCE_KEYS,
  companionKeyFromWireValueVi,
  dayRhythmKeyFromWireValueVi,
  paceKeyFromWireValueVi,
  preferenceKeyFromWireValueVi,
  type DayRhythmKey,
  type PreferenceKey,
} from '../lib/intake-options'
import type { IntakeStatus } from '../types'
import DateField from './date-field'

// intake.people is a formatted string like "2 người" (trip_intake.py), not a
// bare number — pull the leading count back out.
function parseLeadingCount(value: string | null | undefined): number | null {
  if (!value) return null
  const match = /^\d+/.exec(value)
  return match ? Number(match[0]) : null
}

function Chip({
  label,
  selected,
  onClick,
  disabled,
}: {
  label: string
  selected: boolean
  onClick: () => void
  disabled: boolean
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      aria-pressed={selected}
      onClick={onClick}
      className={`px-3 py-1.5 rounded-full text-xs font-medium whitespace-nowrap transition-colors disabled:opacity-60 ${
        selected
          ? 'bg-primary text-on-primary'
          : 'bg-surface-background border border-outline-variant text-secondary hover:bg-surface-muted hover:text-on-surface'
      }`}
    >
      {label}
    </button>
  )
}

function FieldLabel({ text }: { text: string }) {
  return (
    <label className="text-xs text-on-surface-variant block mb-1.5">{text}</label>
  )
}

const NOTES_LIMIT = 1000

/**
 * IntakeParametersForm — the interactive replacement for sequential intake Q&A.
 * Renders once `stage === 'intake'`; composes ONE Vietnamese sentence from the
 * selected fields and calls `onSubmit(message)` through the existing send path.
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
  const { t } = useTranslation()
  const [form, setForm] = useState<IntakeFormState>({
    destination: '',
    startDate: '',
    endDate: '',
    guests: 2,
    budget: '',
    preferences: [],
    companions: '',
    pace: '',
    dayRhythm: [],
    notes: '',
  })
  const seededRef = useRef(false)

  // Pre-fill from the intake snapshot once (null → non-null first time), never
  // on every render — re-seeding would clobber in-progress edits. The snapshot's
  // closed-set fields arrive as Vietnamese wire strings; map them back through
  // the canonical-key lookups so the canonical-key state round-trips.
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

  const requiredOk = Boolean(
    form.destination &&
      form.startDate &&
      form.endDate &&
      form.endDate > form.startDate &&
      form.guests > 0,
  )
  const canSubmit = requiredOk && !disabled

  const togglePreference = (key: PreferenceKey) => {
    setForm((prev) => ({
      ...prev,
      preferences: prev.preferences.includes(key)
        ? prev.preferences.filter((p) => p !== key)
        : [...prev.preferences, key],
    }))
  }

  const toggleDayRhythm = (key: DayRhythmKey) => {
    setForm((prev) => ({
      ...prev,
      dayRhythm: prev.dayRhythm.includes(key)
        ? prev.dayRhythm.filter((r) => r !== key)
        : [...prev.dayRhythm, key],
    }))
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!canSubmit) return
    onSubmit(composeIntakeMessage(form))
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="bg-surface-background border border-outline-variant rounded-xl p-4 mb-3"
    >
      <h3 className="text-sm font-medium text-on-surface mb-3 flex items-center gap-2">
        <span className="material-symbols-outlined text-primary text-sm" aria-hidden="true">
          tune
        </span>
        {t('tripParamsTitle')}
      </h3>

      {/* Destination */}
      <div className="mb-4">
        <FieldLabel text={t('intakeDestinationLabel')} />
        <select
          value={form.destination}
          onChange={(e) => setForm({ ...form, destination: e.target.value })}
          disabled={disabled}
          className="w-full bg-surface-muted p-2 rounded-lg text-sm text-on-surface focus:outline-none focus:ring-1 focus:ring-primary disabled:opacity-60"
        >
          <option value="">{t('intakeDestinationPlaceholder')}</option>
          {destinations.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
      </div>

      {/* Dates & guests */}
      <div className="grid grid-cols-3 gap-3 mb-4">
        <div className="col-span-1">
          <FieldLabel text={t('intakeStartDateLabel')} />
          <DateField
            value={form.startDate}
            onChange={(startDate) =>
              setForm((prev) => ({
                ...prev,
                startDate,
                // An end date earlier than the new start date is no longer valid.
                endDate: prev.endDate && prev.endDate < startDate ? '' : prev.endDate,
              }))
            }
            disabled={disabled}
            placeholder={t('intakeDatePlaceholder')}
          />
        </div>
        <div>
          <FieldLabel text={t('intakeEndDateLabel')} />
          <DateField
            value={form.endDate}
            onChange={(endDate) => setForm({ ...form, endDate })}
            disabled={disabled}
            placeholder={t('intakeDatePlaceholder')}
            minDate={form.startDate}
          />
        </div>
        <div>
          <FieldLabel text={t('intakeGuestsLabel')} />
          <div className="flex items-center gap-2 bg-surface-muted p-1.5 rounded-lg">
            <button
              type="button"
              disabled={disabled || form.guests <= 1}
              onClick={() => setForm({ ...form, guests: form.guests - 1 })}
              className="w-7 h-7 flex items-center justify-center rounded-md bg-surface-background border border-outline-variant text-on-surface hover:bg-surface-container disabled:opacity-40"
              aria-label={t('intakeDecreaseGuests')}
            >
              −
            </button>
            <span className="flex-1 text-center text-sm text-on-surface">
              {form.guests}
            </span>
            <button
              type="button"
              disabled={disabled || form.guests >= 20}
              onClick={() => setForm({ ...form, guests: form.guests + 1 })}
              className="w-7 h-7 flex items-center justify-center rounded-md bg-surface-background border border-outline-variant text-on-surface hover:bg-surface-container disabled:opacity-40"
              aria-label={t('intakeIncreaseGuests')}
            >
              +
            </button>
          </div>
        </div>
      </div>

      {/* Budget & accommodation */}
      <div className="mb-4">
        <FieldLabel text={t('intakeBudgetLabel')} />
        {budgetOptions.length > 0 ? (
          <div className="flex flex-wrap gap-2" role="group">
            {budgetOptions.map((label) => (
              <Chip
                key={label}
                label={label}
                selected={form.budget === label}
                onClick={() => setForm({ ...form, budget: label })}
                disabled={disabled}
              />
            ))}
          </div>
        ) : (
          <p className="text-xs text-on-surface-variant">
            {t('intakeNoBudgetOptions')}
          </p>
        )}
      </div>

      {/* Other options — preferences/companions/pace/day rhythm/notes, collapsed
          by default so the core required fields above aren't crowded out. */}
      <details className="group mb-4">
        <summary className="flex items-center gap-2 text-sm font-medium text-on-surface cursor-pointer list-none [&::-webkit-details-marker]:hidden">
          <span className="material-symbols-outlined text-primary text-sm" aria-hidden="true">
            favorite
          </span>
          {t('intakeOtherOptionsLabel')}
          <span
            className="material-symbols-outlined text-on-surface-variant text-sm ml-auto transition-transform group-open:rotate-180"
            aria-hidden="true"
          >
            expand_more
          </span>
        </summary>

        <div className="mt-3 space-y-4">
          {/* Preferences */}
          <div>
            <FieldLabel text={t('intakePreferencesLabel')} />
            <div className="flex flex-wrap gap-2" role="group">
              {PREFERENCE_KEYS.map((key) => (
                <Chip
                  key={key}
                  label={t(`intake.preferenceOptions.${key}`)}
                  selected={form.preferences.includes(key)}
                  onClick={() => togglePreference(key)}
                  disabled={disabled}
                />
              ))}
            </div>
          </div>

          {/* Companions */}
          <div>
            <FieldLabel text={t('intakeCompanionsLabel')} />
            <div className="flex flex-wrap gap-2" role="group">
              {COMPANION_KEYS.map((key) => (
                <Chip
                  key={key}
                  label={t(`intake.companionOptions.${key}`)}
                  selected={form.companions === key}
                  onClick={() => setForm({ ...form, companions: key })}
                  disabled={disabled}
                />
              ))}
            </div>
          </div>

          {/* Pace */}
          <div>
            <FieldLabel text={t('intakePaceLabel')} />
            <div className="flex flex-wrap gap-2" role="group">
              {PACE_KEYS.map((key) => (
                <Chip
                  key={key}
                  label={t(`intake.paceOptions.${key}`)}
                  selected={form.pace === key}
                  onClick={() => setForm({ ...form, pace: key })}
                  disabled={disabled}
                />
              ))}
            </div>
          </div>

          {/* Day's rhythm */}
          <div>
            <FieldLabel text={t('intakeDayRhythmLabel')} />
            <div className="flex flex-wrap gap-2" role="group">
              {DAY_RHYTHM_KEYS.map((key) => (
                <Chip
                  key={key}
                  label={t(`intake.dayRhythmOptions.${key}`)}
                  selected={form.dayRhythm.includes(key)}
                  onClick={() => toggleDayRhythm(key)}
                  disabled={disabled}
                />
              ))}
            </div>
          </div>

          {/* Notes */}
          <div>
            <FieldLabel text={t('intakeNotesLabel')} />
            <textarea
              value={form.notes}
              maxLength={NOTES_LIMIT}
              rows={2}
              placeholder={t('intakeNotesPlaceholder')}
              onChange={(e) => setForm({ ...form, notes: e.target.value })}
              disabled={disabled}
              className="w-full bg-surface-muted p-2 rounded-lg text-sm text-on-surface focus:outline-none focus:ring-1 focus:ring-primary disabled:opacity-60"
            />
            <p className="text-right text-[10px] text-on-surface-variant mt-1">
              {t('intakeNotesCounter', { n: form.notes.length })}
            </p>
          </div>
        </div>
      </details>

      <div className="flex items-center justify-between gap-3">
        <p className="text-[10px] text-on-surface-variant">{t('intakeRequiredHint')}</p>
        <button
          type="submit"
          disabled={!canSubmit}
          className="px-4 py-2 rounded-full bg-primary text-on-primary text-sm font-medium hover:bg-primary-container disabled:opacity-50 transition-colors"
        >
          {t('intakeSubmit')}
        </button>
      </div>
    </form>
  )
}
