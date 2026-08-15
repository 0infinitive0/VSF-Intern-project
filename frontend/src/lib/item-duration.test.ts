import { describe, expect, it } from 'vitest'
import { formatItemDuration, minutesBetween, stripSeconds } from './item-duration'

const t = (key: string, options?: Record<string, unknown>) => {
  const dict: Record<string, string> = {
    durationHoursOne: '{{count}} tiếng',
    durationHoursOther: '{{count}} tiếng',
    durationMinutesOne: '{{count}} phút',
    durationMinutesOther: '{{count}} phút',
  }
  const template = dict[key] ?? key
  return template.replace('{{count}}', String(options?.count ?? ''))
}

describe('stripSeconds', () => {
  it('drops trailing :00 seconds', () => {
    expect(stripSeconds('07:00:00')).toBe('07:00')
    expect(stripSeconds('19:30:00')).toBe('19:30')
  })

  it('passes an already-HH:MM value through unchanged', () => {
    expect(stripSeconds('07:00')).toBe('07:00')
  })

  it('passes unrecognized input through unchanged rather than guessing', () => {
    expect(stripSeconds('not-a-time')).toBe('not-a-time')
  })
})

describe('minutesBetween', () => {
  it('computes whole minutes between two HH:MM:SS times', () => {
    expect(minutesBetween('07:00:00', '08:00:00')).toBe(60)
    expect(minutesBetween('07:00:00', '07:30:00')).toBe(30)
  })

  it('returns null when either time is missing', () => {
    expect(minutesBetween(null, '08:00:00')).toBeNull()
    expect(minutesBetween('07:00:00', null)).toBeNull()
  })

  it('returns null when end is not after start (never a negative/zero duration)', () => {
    expect(minutesBetween('08:00:00', '07:00:00')).toBeNull()
    expect(minutesBetween('08:00:00', '08:00:00')).toBeNull()
  })
})

describe('formatItemDuration', () => {
  it('formats an exact hour', () => {
    expect(formatItemDuration(60, t)).toBe('1 tiếng')
  })

  it('formats minutes under an hour', () => {
    expect(formatItemDuration(30, t)).toBe('30 phút')
  })

  it('formats a mixed hour + minutes duration', () => {
    expect(formatItemDuration(90, t)).toBe('1 tiếng 30 phút')
  })

  it('formats multiple hours', () => {
    expect(formatItemDuration(120, t)).toBe('2 tiếng')
  })

  it('returns empty string for a non-positive duration', () => {
    expect(formatItemDuration(0, t)).toBe('')
    expect(formatItemDuration(-5, t)).toBe('')
  })
})
