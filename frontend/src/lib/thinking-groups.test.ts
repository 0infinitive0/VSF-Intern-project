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
  it('builds every step in render order for a full turn', () => {
    const groups = apply([
      'received', 'intake_check', 'routing', 'hotel_search',
      'itinerary_build', 'routing_legs', 'persisting', 'generating',
    ])

    expect(groups.map((g) => g.key)).toEqual(GROUP_ORDER)
  })

  it('keeps one step when the supervisor routes three times', () => {
    const groups = apply(['routing', 'routing', 'routing'])

    expect(groups).toHaveLength(1)
    expect(groups[0].key).toBe('route')
  })

  it('never lists a step the turn did not reach', () => {
    // An intake-only turn does no hotel search; drawing it greyed out would
    // describe work that will not happen.
    const groups = apply(['received', 'intake_check', 'generating'])

    expect(groups.map((g) => g.key)).toEqual(['history', 'analyze', 'reply'])
  })

  it('orders by GROUP_ORDER even when frames arrive out of order', () => {
    // `persisting` (save) really can land before `routing_legs` (itinerary).
    const groups = apply(['persisting', 'routing_legs'])

    expect(groups.map((g) => g.key)).toEqual(['itinerary', 'save'])
  })

  it('ignores an unknown key instead of creating a step for it', () => {
    const groups = apply(['intake_check', 'some_future_key'])

    expect(groups.map((g) => g.key)).toEqual(['analyze'])
  })

  it('closes a step when the node reports it finished', () => {
    let groups = applyPhaseToGroups([], 'intake_check', [], 'started')
    expect(groups[0].done).toBe(false)

    groups = applyPhaseToGroups(groups, 'intake_check', [], 'completed')
    expect(groups[0].done).toBe(true)
  })

  it('reopens a step when a second key of the same group starts', () => {
    // `itinerary` covers both `itinerary_build` and `routing_legs`.
    let groups = applyPhaseToGroups([], 'itinerary_build', [], 'completed')
    expect(groups[0].done).toBe(true)

    groups = applyPhaseToGroups(groups, 'routing_legs', [], 'started')
    expect(groups[0].done).toBe(false)
  })

  it('closes earlier steps when a later one starts', () => {
    const groups = apply(['intake_check', 'hotel_search'])

    expect(groups.find((g) => g.key === 'analyze')?.done).toBe(true)
    expect(groups.find((g) => g.key === 'hotels')?.done).toBe(false)
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
  it('files the text under the step named by the frame, not the open one', () => {
    // The real ordering: `generating` is announced only after the node that
    // produced this text has finished.
    let groups = apply(['intake_check'])
    groups = appendReasoning(groups, 'generating', 'Checking ')
    groups = appendReasoning(groups, 'generating', 'the season')

    expect(groups.find((g) => g.key === 'reply')?.reasoning).toBe('Checking the season')
    expect(groups.find((g) => g.key === 'analyze')?.reasoning).toBe('')
  })

  it('creates the step when its phase frame has not arrived yet', () => {
    const groups = appendReasoning([], 'generating', 'thinking...')

    expect(groups.map((g) => g.key)).toEqual(['reply'])
    expect(groups[0].reasoning).toBe('thinking...')
  })

  it('ignores empty text — the common case, not an error', () => {
    const groups = apply(['intake_check'])

    expect(appendReasoning(groups, 'generating', '')).toBe(groups)
  })

  it('ignores a phase key it does not know', () => {
    const groups = apply(['intake_check'])

    expect(appendReasoning(groups, 'future_key', 'x')).toBe(groups)
  })
})

describe('completeGroups', () => {
  it('closes every group when the turn ends', () => {
    const groups = completeGroups(apply(['intake_check', 'hotel_search']))

    expect(groups.every((g) => g.done)).toBe(true)
  })
})

describe('group labels', () => {
  it('has a translation in both locales for every step', () => {
    const labels = apply([
      'received', 'intake_check', 'routing', 'hotel_search',
      'itinerary_build', 'persisting', 'generating',
    ]).map((g) => g.labelKey)

    expect(labels).toHaveLength(7)
    for (const key of labels) {
      expect(vi, `vi is missing ${key}`).toHaveProperty(key)
      expect(en, `en is missing ${key}`).toHaveProperty(key)
    }
  })
})
