import { describe, expect, it } from 'vitest'
import { phaseLabelKey } from './phase-labels'
import en from '../i18n/locales/en.json'
import vi from '../i18n/locales/vi.json'

const ALL_PHASE_KEYS = [
  'received',
  'routing',
  'compacting_history',
  'intake_check',
  'hotel_search',
  'itinerary_build',
  'routing_legs',
  'persisting',
  'generating',
] as const

describe('phaseLabelKey', () => {
  it('maps every documented phase key to an i18n key present in both locales', () => {
    for (const key of ALL_PHASE_KEYS) {
      const i18nKey = phaseLabelKey(key)
      expect(i18nKey, `${key} should map to a label`).not.toBeNull()
      expect((en as unknown as Record<string, string>)[i18nKey as string], `en.json missing ${i18nKey}`).toBeTruthy()
      expect((vi as unknown as Record<string, string>)[i18nKey as string], `vi.json missing ${i18nKey}`).toBeTruthy()
    }
  })

  it('ignores an unrecognized key silently instead of rendering it raw', () => {
    expect(phaseLabelKey('some_future_key_the_frontend_does_not_know')).toBeNull()
  })
})
