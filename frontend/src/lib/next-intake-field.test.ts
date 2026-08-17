import { describe, expect, it } from 'vitest'
import {
  INTAKE_FIELD_ORDER,
  currentIntakeField,
  isFieldMissing,
  locallyAdvancedField,
  nextIntakeField,
  type IntakeField,
} from './next-intake-field'
import type { IntakeStatus } from '../types'
import { intakeStatus } from '../test-fixtures'

const BASE_INTAKE: IntakeStatus = intakeStatus({
  destination: null,
  duration: null,
  start_date: null,
  end_date: null,
  people: null,
  preferences: [],
  companions: null,
  pace: null,
  day_rhythm: [],
  notes: '',
  available_destinations: ['Đà Nẵng'],
  budget_options: [],
  missing: [],
})

function intakeWith(missing: string[], overrides: Partial<IntakeStatus> = {}): IntakeStatus {
  return { ...BASE_INTAKE, missing, budget_options: ['Khách sạn 4 sao'], ...overrides }
}

function form(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    destination: '',
    startDate: '',
    endDate: '',
    guests: 0,
    budgetMinVnd: null,
    budgetMaxVnd: null,
    budgetSkipped: false,
    preferences: [],
    ...overrides,
  }
}

describe('isFieldMissing', () => {
  it('maps only the real backend missing keys onto the widget fields', () => {
    const intake = intakeWith(['destination', 'start_date', 'duration', 'people'])
    expect(isFieldMissing(intake, 'destination')).toBe(true)
    expect(isFieldMissing(intake, 'people')).toBe(true)
    expect(isFieldMissing(intake, 'dates')).toBe(true)
    expect(isFieldMissing(intake, 'budget')).toBe(false)
    expect(isFieldMissing(intake, 'preferences')).toBe(false)
  })

  it('treats start_date and duration as one "dates" field', () => {
    expect(isFieldMissing(intakeWith(['start_date']), 'dates')).toBe(true)
    expect(isFieldMissing(intakeWith(['duration']), 'dates')).toBe(true)
  })

  it('returns false for a null intake', () => {
    expect(isFieldMissing(null, 'destination')).toBe(false)
  })
})

describe('nextIntakeField', () => {
  it('returns null when nothing is missing', () => {
    expect(nextIntakeField(intakeWith([]))).toBeNull()
  })

  it('returns the first missing field in widget order', () => {
    expect(nextIntakeField(intakeWith(['people', 'destination']))).toBe('destination')
  })

  it('never surfaces budget/preferences as server-required', () => {
    expect(nextIntakeField(intakeWith(['budget']))).toBeNull()
    expect(nextIntakeField(intakeWith(['preferences']))).toBeNull()
  })
})

describe('locallyAdvancedField', () => {
  it('asks nothing when the widget matches what the backend just asked for', () => {
    // Backend replied "how many people?" and the people stepper is what's open
    // — its own message already covers it.
    expect(locallyAdvancedField(intakeWith(['people', 'start_date']), 'people', form())).toBeNull()
  })

  it('asks the question when the widget has walked past the backend', () => {
    // People answered locally (no chat turn), so the backend still considers
    // people missing while the dates picker is already open — nobody has asked
    // about dates yet.
    expect(locallyAdvancedField(intakeWith(['people', 'start_date']), 'dates', form())).toBe('dates')
  })

  it('asks for the ungated optional fields, which the backend never requests', () => {
    expect(locallyAdvancedField(intakeWith([]), 'budget', form())).toBe('budget')
    expect(locallyAdvancedField(intakeWith([]), 'preferences', form())).toBe('preferences')
  })

  it('returns null when no widget is open', () => {
    expect(locallyAdvancedField(intakeWith(['people']), null, form())).toBeNull()
  })

  // The persistent-duplicate-bubble bug. Once every gated field is answered,
  // nextIntakeField is null forever while the terminal preferences card stays
  // open — so "preferences !== null" kept re-rendering its question on every
  // single intake-stage turn, including turns about something else entirely.
  it('stops asking a field the user has already answered locally', () => {
    const answered = form({
      destination: 'Đà Nẵng',
      guests: 2,
      startDate: '2026-08-10',
      endDate: '2026-08-13',
      budgetSkipped: true,
      preferences: ['amusement'],
    })
    expect(locallyAdvancedField(intakeWith([]), 'preferences', answered)).toBeNull()
  })

  it('still asks the preferences question while no chip has been picked', () => {
    const filled = form({ destination: 'Đà Nẵng', guests: 2, startDate: 'a', endDate: 'b', budgetSkipped: true })
    expect(locallyAdvancedField(intakeWith([]), 'preferences', filled)).toBe('preferences')
  })
})

describe('currentIntakeField', () => {
  // Pre-first-turn (empty-conversation quick-start destination chips): no
  // backend snapshot exists yet, so the walk is local-only, in the full
  // destination -> people -> dates -> budget -> preferences order — budget's
  // `intake.budget_options` existence gate only applies once a real intake
  // snapshot exists (see currentIntakeField's pre-intake doc).
  it('walks destination -> people -> dates -> budget -> preferences locally when there is no intake yet', () => {
    expect(currentIntakeField(null, form())).toBe('destination')
    expect(currentIntakeField(null, form({ destination: 'Hà Nội' }))).toBe('people')
    expect(currentIntakeField(null, form({ destination: 'Hà Nội', guests: 2 }))).toBe('dates')
    const withDates = form({ destination: 'Hà Nội', guests: 2, startDate: '2026-08-10', endDate: '2026-08-13' })
    expect(currentIntakeField(null, withDates)).toBe('budget')
    expect(currentIntakeField(null, { ...withDates, budgetSkipped: true })).toBe('preferences')
  })

  it('walks required fields first, in order, until one is missing', () => {
    const intake = intakeWith(['destination', 'people', 'start_date', 'duration'])
    expect(currentIntakeField(intake, form())).toBe('destination')
    expect(
      currentIntakeField(intake, form({ destination: 'Đà Nẵng' })),
    ).toBe('people')
    expect(
      currentIntakeField(intake, form({ destination: 'Đà Nẵng', guests: 2 })),
    ).toBe('dates')
    expect(
      currentIntakeField(
        intake,
        form({ destination: 'Đà Nẵng', guests: 2, startDate: '2026-08-10', endDate: '2026-08-13' }),
      ),
    ).toBe('budget')
  })

  it('treats an end date earlier than start as not filled', () => {
    const intake = intakeWith(['start_date', 'duration'])
    const f = form({ destination: 'Đà Nẵng', startDate: '2026-08-13', endDate: '2026-08-10' })
    expect(currentIntakeField(intake, f)).toBe('dates')
  })

  it('surfaces optional budget once required fields are filled and options exist', () => {
    const intake = intakeWith([])
    const filled = form({ destination: 'Đà Nẵng', guests: 2, startDate: 'a', endDate: 'b' })
    expect(currentIntakeField(intake, filled)).toBe('budget')
  })

  it('skips budget when the backend offered no budget_options', () => {
    const intake = intakeWith([], { budget_options: [] })
    const filled = form({ destination: 'Đà Nẵng', guests: 2, startDate: 'a', endDate: 'b' })
    expect(currentIntakeField(intake, filled)).toBe('preferences')
  })

  it('surfaces preferences only after budget is answered', () => {
    const intake = intakeWith([])
    const f = form({
      destination: 'Đà Nẵng',
      guests: 2,
      startDate: 'a',
      endDate: 'b',
      budgetMinVnd: 800_000,
      budgetMaxVnd: 2_500_000,
    })
    expect(currentIntakeField(intake, f)).toBe('preferences')
  })

  it('treats a skipped budget as answered too', () => {
    const intake = intakeWith([])
    const f = form({ destination: 'Đà Nẵng', guests: 2, startDate: 'a', endDate: 'b', budgetSkipped: true })
    expect(currentIntakeField(intake, f)).toBe('preferences')
  })

  it('skips the widget when the backend already has a budget range from plain chat', () => {
    const intake = intakeWith([], { min_price: 800_000, max_price: 2_500_000 })
    const f = form({ destination: 'Đà Nẵng', guests: 2, startDate: 'a', endDate: 'b' })
    expect(currentIntakeField(intake, f)).toBe('preferences')
  })

  it('skips the widget when the backend recorded an explicit budget skip from plain chat', () => {
    const intake = intakeWith([], { budget_skipped: true })
    const f = form({ destination: 'Đà Nẵng', guests: 2, startDate: 'a', endDate: 'b' })
    expect(currentIntakeField(intake, f)).toBe('preferences')
  })

  it('keeps preferences active once toggled — it is terminal, not a gate', () => {
    const intake = intakeWith([])
    const f = form({
      destination: 'Đà Nẵng',
      guests: 2,
      startDate: 'a',
      endDate: 'b',
      budgetMinVnd: 800_000,
      budgetMaxVnd: 2_500_000,
      preferences: ['amusement'],
    })
    expect(currentIntakeField(intake, f)).toBe('preferences')
  })

  it('keeps required fields in front of optional ones even when optional are pre-filled', () => {
    const intake = intakeWith(['destination'])
    const f = form({
      budgetMinVnd: 800_000,
      budgetMaxVnd: 2_500_000,
      preferences: ['amusement'],
      startDate: 'a',
      endDate: 'b',
      guests: 2,
    })
    expect(currentIntakeField(intake, f)).toBe('destination')
  })
})

// The phase-06 state table: which widget is open, and whether the frontend
// asks its question, for each way the local form and the server snapshot can
// disagree. `question` is what the user actually sees as an extra AI bubble.
describe('intake state table (widget vs question)', () => {
  const filledDates = { startDate: '2026-08-10', endDate: '2026-08-13' }

  it('backend asks destination → destination widget, no duplicate question', () => {
    const intake = intakeWith(['destination', 'people', 'start_date', 'duration'])
    const f = form()
    expect(nextIntakeField(intake)).toBe('destination')
    expect(currentIntakeField(intake, f)).toBe('destination')
    expect(locallyAdvancedField(intake, currentIntakeField(intake, f), f)).toBeNull()
  })

  it('user answered people locally → dates widget, frontend asks the dates question', () => {
    const intake = intakeWith(['people', 'start_date', 'duration'])
    const f = form({ destination: 'Đà Nẵng', guests: 2 })
    expect(nextIntakeField(intake)).toBe('people')
    expect(currentIntakeField(intake, f)).toBe('dates')
    expect(locallyAdvancedField(intake, currentIntakeField(intake, f), f)).toBe('dates')
  })

  it('backend re-opened dates → dates widget, no duplicate question', () => {
    // The form has already been cleared for this field by mergeIntakeIntoForm
    // (that is what makes the backend's re-opened slot win over the stale
    // local answer) — so the widget goes back to the date picker.
    const intake = intakeWith(['start_date', 'duration'])
    const f = form({ destination: 'Đà Nẵng', guests: 2 })
    expect(nextIntakeField(intake)).toBe('dates')
    expect(currentIntakeField(intake, f)).toBe('dates')
    expect(locallyAdvancedField(intake, currentIntakeField(intake, f), f)).toBeNull()
  })

  it('everything answered, no chip picked → preferences card and its question', () => {
    const intake = intakeWith([])
    const f = form({ destination: 'Đà Nẵng', guests: 2, ...filledDates, budgetSkipped: true })
    expect(nextIntakeField(intake)).toBeNull()
    expect(currentIntakeField(intake, f)).toBe('preferences')
    expect(locallyAdvancedField(intake, currentIntakeField(intake, f), f)).toBe('preferences')
  })

  it('everything answered, a chip picked → preferences card STAYS, question goes', () => {
    // The card must survive: its "Tìm khách sạn phù hợp" button is the only
    // path to submitAll. Only the repeated question disappears.
    const intake = intakeWith([])
    const f = form({
      destination: 'Đà Nẵng',
      guests: 2,
      ...filledDates,
      budgetSkipped: true,
      preferences: ['amusement'],
    })
    expect(nextIntakeField(intake)).toBeNull()
    expect(currentIntakeField(intake, f)).toBe('preferences')
    expect(locallyAdvancedField(intake, currentIntakeField(intake, f), f)).toBeNull()
  })
})

describe('INTAKE_FIELD_ORDER', () => {
  it('is the canonical widget order: destination → people → dates → budget → preferences', () => {
    const order: IntakeField[] = ['destination', 'people', 'dates', 'budget', 'preferences']
    expect([...INTAKE_FIELD_ORDER]).toEqual(order)
  })
})
