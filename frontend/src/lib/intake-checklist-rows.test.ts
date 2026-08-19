import { describe, expect, it } from 'vitest'
import { buildIntakeChecklistRows } from './intake-checklist-rows'
import type { IntakeStatus } from '../types'
import { intakeStatus } from '../test-fixtures'

const FULL_INTAKE: IntakeStatus = intakeStatus({
  destination: 'Đà Nẵng',
  duration: '3 ngày 2 đêm',
  start_date: '2026-10-12T00:00:00',
  end_date: '2026-10-14T00:00:00',
  people: '2 người',
  preferences: ['beach', 'food'],
  companions: null,
  pace: null,
  day_rhythm: [],
  notes: '',
  available_destinations: ['Đà Nẵng'],
  budget_options: ['Tiết kiệm (dưới 800,000 VND/đêm)'],
  missing: [],
})

const LABELS = { peopleWord: 'người', budgetSkipped: 'Không giới hạn' }

describe('buildIntakeChecklistRows', () => {
  it('renders five rows in the design order', () => {
    const rows = buildIntakeChecklistRows(FULL_INTAKE, 'en')
    expect(rows.map((row) => row.key)).toEqual([
      'destination',
      'people',
      'dates',
      'budget',
      'preferences',
    ])
  })

  it('marks every row uncollected when intake is null (pre-first-turn state)', () => {
    const rows = buildIntakeChecklistRows(null, 'en')
    expect(rows.every((row) => !row.collected)).toBe(true)
    expect(rows.every((row) => row.value == null)).toBe(true)
  })

  it('collects rows only when present AND not listed in intake.missing', () => {
    const rows = buildIntakeChecklistRows(
      { ...FULL_INTAKE, missing: ['destination', 'duration'] },
      'en',
    )
    const byKey = Object.fromEntries(rows.map((row) => [row.key, row]))
    expect(byKey.destination.collected).toBe(false)
    expect(byKey.dates.collected).toBe(false)
    expect(byKey.people.collected).toBe(true)
    expect(byKey.preferences.collected).toBe(true)
  })

  it('keeps intake.people verbatim (formatted backend string, never re-parsed)', () => {
    const rows = buildIntakeChecklistRows(FULL_INTAKE, 'en')
    expect(rows.find((row) => row.key === 'people')?.value).toBe('2 người')
  })

  it('formats the date row as a locale-aware range', () => {
    const rows = buildIntakeChecklistRows(FULL_INTAKE, 'en')
    expect(rows.find((row) => row.key === 'dates')?.value).toBe('Oct 12 - Oct 14')
  })

  it('drops the date value when it fails to format (missing/invalid dates)', () => {
    const rows = buildIntakeChecklistRows(
      { ...FULL_INTAKE, start_date: null, missing: ['start_date'] },
      'en',
    )
    const dates = rows.find((row) => row.key === 'dates')
    expect(dates?.collected).toBe(false)
    expect(dates?.value).toBeNull()
  })

  it('maps the server preference labels to canonical keys for the chips row', () => {
    const rows = buildIntakeChecklistRows(
      { ...FULL_INTAKE, preferences: ['biển', 'ẩm thực'] },
      'vi',
    )
    const prefs = rows.find((row) => row.key === 'preferences')
    expect(prefs?.preferenceKeys).toEqual(['beach', 'food'])
    expect(prefs?.value).toBeNull()
  })

  it('passes a preference label the closed set does not know through untouched', () => {
    const rows = buildIntakeChecklistRows({ ...FULL_INTAKE, preferences: ['lặn biển'] }, 'vi')
    expect(rows.find((row) => row.key === 'preferences')?.preferenceKeys).toEqual(['lặn biển'])
  })

  it('treats unknown-but-present gated keys the same as missing', () => {
    const rows = buildIntakeChecklistRows(
      { ...FULL_INTAKE, people: null, missing: ['people'] },
      'vi',
    )
    const people = rows.find((row) => row.key === 'people')
    expect(people?.collected).toBe(false)
    expect(people?.value).toBeNull()
  })

  // ---- local form fallback (checklist live-update) -------------------------

  it('lights up destination from the local form before the server confirms it (pre-first-turn empty conversation)', () => {
    const rows = buildIntakeChecklistRows(null, 'en', { destination: 'Hà Nội' }, LABELS)
    const destination = rows.find((row) => row.key === 'destination')
    expect(destination?.collected).toBe(true)
    expect(destination?.value).toBe('Hà Nội')
  })

  it('server-confirmed destination wins over a stale local pick once both exist', () => {
    const rows = buildIntakeChecklistRows(FULL_INTAKE, 'en', { destination: 'Huế' }, LABELS)
    expect(rows.find((row) => row.key === 'destination')?.value).toBe('Đà Nẵng')
  })

  it('lights up people from the local form before the server confirms it', () => {
    const rows = buildIntakeChecklistRows(
      { ...FULL_INTAKE, people: null, missing: ['people'] },
      'en',
      { guests: 3 },
      LABELS,
    )
    const people = rows.find((row) => row.key === 'people')
    expect(people?.collected).toBe(true)
    expect(people?.value).toBe('3 người')
  })

  it('server-confirmed people wins over the local guest count once both exist', () => {
    const rows = buildIntakeChecklistRows(FULL_INTAKE, 'en', { guests: 9 }, LABELS)
    expect(rows.find((row) => row.key === 'people')?.value).toBe('2 người')
  })

  it('lights up dates from the local form before the server confirms it', () => {
    const rows = buildIntakeChecklistRows(
      { ...FULL_INTAKE, start_date: null, missing: ['start_date'] },
      'en',
      { startDate: '2026-10-12', endDate: '2026-10-14' },
      LABELS,
    )
    const dates = rows.find((row) => row.key === 'dates')
    expect(dates?.collected).toBe(true)
    expect(dates?.value).toBe('Oct 12 - Oct 14')
  })

  it('budget lights up once a local range is confirmed (never server-gated)', () => {
    const rows = buildIntakeChecklistRows(
      FULL_INTAKE,
      'vi',
      { budgetMinVnd: 800_000, budgetMaxVnd: 2_500_000 },
      LABELS,
    )
    const budget = rows.find((row) => row.key === 'budget')
    expect(budget?.collected).toBe(true)
    expect(budget?.value).toBe('800.000 ₫ – 2.500.000 ₫')
  })

  it('budget shows the skipped label when the user skipped it locally', () => {
    const rows = buildIntakeChecklistRows(FULL_INTAKE, 'vi', { budgetSkipped: true }, LABELS)
    const budget = rows.find((row) => row.key === 'budget')
    expect(budget?.collected).toBe(true)
    expect(budget?.value).toBe('Không giới hạn')
  })

  it('budget stays uncollected with no local answer', () => {
    const rows = buildIntakeChecklistRows(FULL_INTAKE, 'en')
    const budget = rows.find((row) => row.key === 'budget')
    expect(budget?.collected).toBe(false)
    expect(budget?.value).toBeNull()
  })

  it('lights up budget from a server-confirmed range given via plain chat', () => {
    const rows = buildIntakeChecklistRows(
      { ...FULL_INTAKE, min_price: 800_000, max_price: 2_500_000 },
      'vi',
    )
    const budget = rows.find((row) => row.key === 'budget')
    expect(budget?.collected).toBe(true)
    expect(budget?.value).toBe('800.000 ₫ – 2.500.000 ₫')
  })

  it('shows the skipped label when the backend recorded an explicit chat skip', () => {
    const rows = buildIntakeChecklistRows({ ...FULL_INTAKE, budget_skipped: true }, 'vi', null, LABELS)
    const budget = rows.find((row) => row.key === 'budget')
    expect(budget?.collected).toBe(true)
    expect(budget?.value).toBe('Không giới hạn')
  })

  it('server-confirmed budget wins over a stale local answer once both exist', () => {
    const rows = buildIntakeChecklistRows(
      { ...FULL_INTAKE, min_price: 800_000, max_price: 2_500_000 },
      'vi',
      { budgetSkipped: true },
      LABELS,
    )
    const budget = rows.find((row) => row.key === 'budget')
    expect(budget?.value).toBe('800.000 ₫ – 2.500.000 ₫')
  })

  it('shows the chips a user just toggled, before any server round-trip', () => {
    const rows = buildIntakeChecklistRows(null, 'vi', { preferences: ['beach', 'nature'] }, LABELS)
    const prefs = rows.find((row) => row.key === 'preferences')
    expect(prefs?.collected).toBe(true)
    expect(prefs?.preferenceKeys).toEqual(['beach', 'nature'])
  })

  it('local chips win over the server snapshot they were merged from', () => {
    const rows = buildIntakeChecklistRows(
      { ...FULL_INTAKE, preferences: ['biển'] },
      'vi',
      { preferences: ['beach', 'nature'] },
      LABELS,
    )
    expect(rows.find((row) => row.key === 'preferences')?.preferenceKeys).toEqual([
      'beach',
      'nature',
    ])
  })

  it('never marks preferences collected with no chip to show', () => {
    const rows = buildIntakeChecklistRows(
      { ...FULL_INTAKE, preferences: [] },
      'vi',
      { preferences: [] },
      LABELS,
    )
    const prefs = rows.find((row) => row.key === 'preferences')
    expect(prefs?.collected).toBe(false)
    expect(prefs?.preferenceKeys).toEqual([])
  })
})
