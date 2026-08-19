import { describe, expect, it } from 'vitest'
import {
  GROUP_ORDER,
  appendReasoning,
  applyPhaseToGroups,
  completeGroups,
  groupForPhase,
} from './thinking-groups'
import type { ThinkingGroup } from '../types'
import en from '../i18n/locales/en.json'
import vi from '../i18n/locales/vi.json'

const apply = (keys: string[], lines: string[] = []): ThinkingGroup[] =>
  keys.reduce((groups, key) => applyPhaseToGroups(groups, key, lines), [] as ThinkingGroup[])

describe('groupForPhase', () => {
  it('folds every phase key the backend can send into a group', () => {
    const allKeys = [
      'received', 'routing', 'compacting_history', 'intake_check', 'hotel_search',
      'itinerary_build', 'routing_legs', 'persisting', 'generating',
    ]

    for (const key of allKeys) expect(groupForPhase(key)).not.toBeNull()
  })

  it('returns null for a key it does not know', () => {
    expect(groupForPhase('a_key_shipped_after_this_build')).toBeNull()
  })
})

describe('applyPhaseToGroups', () => {
  it('builds the four groups in render order for a full turn', () => {
    const groups = apply([
      'received', 'intake_check', 'routing', 'hotel_search',
      'itinerary_build', 'routing_legs', 'persisting', 'generating',
    ])

    expect(groups.map((g) => g.key)).toEqual(GROUP_ORDER)
  })

  it('keeps one group when the supervisor routes three times', () => {
    const groups = apply(['routing', 'routing', 'routing'])

    expect(groups).toHaveLength(1)
    expect(groups[0].key).toBe('understand')
  })

  it('omits the build group on an intake-only turn', () => {
    const groups = apply(['received', 'intake_check', 'generating'])

    expect(groups.map((g) => g.key)).toEqual(['understand', 'finalize'])
  })

  it('orders by GROUP_ORDER even when frames arrive out of order', () => {
    // `persisting` (finalize) really can land before `routing_legs` (build).
    const groups = apply(['persisting', 'routing_legs'])

    expect(groups.map((g) => g.key)).toEqual(['build', 'finalize'])
  })

  it('ignores an unknown key instead of creating a group for it', () => {
    const groups = apply(['intake_check', 'some_future_key'])

    expect(groups.map((g) => g.key)).toEqual(['understand'])
  })

  it('closes earlier groups when a later one starts', () => {
    const groups = apply(['intake_check', 'hotel_search'])

    expect(groups.find((g) => g.key === 'understand')?.done).toBe(true)
    expect(groups.find((g) => g.key === 'gather')?.done).toBe(false)
  })

  it('appends new lines to a group that already exists', () => {
    let groups = applyPhaseToGroups([], 'hotel_search', ['tìm ở Đà Nẵng'])
    groups = applyPhaseToGroups(groups, 'hotel_search', ['giữ lại 8 lựa chọn'])

    expect(groups[0].lines).toEqual(['tìm ở Đà Nẵng', 'giữ lại 8 lựa chọn'])
  })

  it('does not repeat a line the group already shows', () => {
    let groups = applyPhaseToGroups([], 'routing', ['chuyển cho tìm khách sạn'])
    groups = applyPhaseToGroups(groups, 'routing', ['chuyển cho tìm khách sạn'])

    expect(groups[0].lines).toEqual(['chuyển cho tìm khách sạn'])
  })

  it('never mutates the array it is given', () => {
    const before: ThinkingGroup[] = []
    applyPhaseToGroups(before, 'intake_check', ['x'])

    expect(before).toEqual([])
  })

  it('creates a group with no lines when the step reported no facts', () => {
    const groups = applyPhaseToGroups([], 'compacting_history', [])

    expect(groups[0].lines).toEqual([])
    expect(groups[0].reasoning).toBe('')
  })
})

describe('appendReasoning', () => {
  it('accumulates text on the group still running', () => {
    let groups = apply(['intake_check', 'hotel_search'])
    groups = appendReasoning(groups, 'Checking ')
    groups = appendReasoning(groups, 'amenities')

    expect(groups.find((g) => g.key === 'gather')?.reasoning).toBe('Checking amenities')
    expect(groups.find((g) => g.key === 'understand')?.reasoning).toBe('')
  })

  it('ignores empty text — the common case, not an error', () => {
    const groups = apply(['intake_check'])

    expect(appendReasoning(groups, '')).toBe(groups)
  })

  it('does not crash when reasoning arrives before any group exists', () => {
    expect(appendReasoning([], 'thinking...')).toEqual([])
  })
})

describe('completeGroups', () => {
  it('closes every group when the turn ends', () => {
    const groups = completeGroups(apply(['intake_check', 'hotel_search']))

    expect(groups.every((g) => g.done)).toBe(true)
  })
})

describe('group labels', () => {
  it('has a translation in both locales for every group', () => {
    const labels = apply([
      'intake_check', 'hotel_search', 'itinerary_build', 'persisting',
    ]).map((g) => g.labelKey)

    expect(labels).toHaveLength(4)
    for (const key of labels) {
      expect(vi, `vi is missing ${key}`).toHaveProperty(key)
      expect(en, `en is missing ${key}`).toHaveProperty(key)
    }
  })
})
