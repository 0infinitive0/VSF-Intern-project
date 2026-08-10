---
phase: 2
title: "Frontend String Migration & Wire-Protocol Decoupling"
status: pending
priority: P1
effort: "1.5d"
dependencies: [1]
---

# Phase 2: Frontend String Migration & Wire-Protocol Decoupling

## Overview

Migrate all 12 files currently importing `S` from `strings.ts` to
`useTranslation()` / `t()`, and decouple the intake form's chip *values* from
their *display labels* so English-language chip selections still compose the
Vietnamese sentence the backend's closed-set matching expects.

## Requirements

- Functional: every string previously from `S.*` renders correctly in both
  languages; `composeIntakeMessage()` output is unchanged (still Vietnamese)
  regardless of `i18n.language`.
- Functional: `IntakeFormState.preferences/companions/pace/dayRhythm` store
  canonical keys, not display strings, so `intake` snapshot pre-fill
  (`frontend/src/components/intake-parameters-form.tsx:86-108`, which seeds
  from server-returned Vietnamese values) still round-trips correctly.
- Non-functional: no behavior change to `destinations`/`budgetOptions`
  (server-sourced, stay Vietnamese, out of scope — see plan.md).

## Architecture

### Canonical intake option keys

New file `frontend/src/lib/intake-options.ts` is the single place mapping a
stable canonical key to (a) the exact Vietnamese wire string the backend's
closed sets expect, and (b) the i18n key for its display label. Order and
Vietnamese text mirror `src/services/trip_intake.py:30-64` exactly (source of
truth per that file's own comment):

```ts
export const PREFERENCE_KEYS = [
  'beach', 'culture', 'food', 'nature', 'history',
  'shopping', 'nightlife', 'kids', 'classic', 'cityscape',
] as const
export type PreferenceKey = (typeof PREFERENCE_KEYS)[number]

// Byte-identical to src/services/trip_intake.py:30-41 (_PREFERENCE_LABELS).
export const PREFERENCE_WIRE_VALUE_VI: Record<PreferenceKey, string> = {
  beach: 'biển', culture: 'văn hóa', food: 'ẩm thực', nature: 'thiên nhiên',
  history: 'lịch sử', shopping: 'mua sắm', nightlife: 'cuộc sống về đêm',
  kids: 'trẻ em', classic: 'cổ điển', cityscape: 'cảnh đô thị',
}
// display label -> i18n key: `intake.preferenceOptions.${key}`

export const COMPANION_KEYS = ['solo', 'family', 'partner', 'friends', 'elderly'] as const
export type CompanionKey = (typeof COMPANION_KEYS)[number]
// Byte-identical to trip_intake.py:47-53 (_COMPANION_LABELS).
export const COMPANION_WIRE_VALUE_VI: Record<CompanionKey, string> = {
  solo: 'đi một mình', family: 'đi cùng gia đình',
  partner: 'đi cùng người yêu hoặc vợ chồng', friends: 'đi cùng bạn bè',
  elderly: 'có người lớn tuổi trong đoàn',
}

export const PACE_KEYS = ['packed', 'moderate', 'relaxed'] as const
export type PaceKey = (typeof PACE_KEYS)[number]
// Byte-identical to trip_intake.py:55-59 (_PACE_LABELS).
export const PACE_WIRE_VALUE_VI: Record<PaceKey, string> = {
  packed: 'dày đặc', moderate: 'vừa phải', relaxed: 'thư thái',
}

export const DAY_RHYTHM_KEYS = ['earlyStart', 'lateNight'] as const
export type DayRhythmKey = (typeof DAY_RHYTHM_KEYS)[number]
// Byte-identical to trip_intake.py:61-64 (_DAY_RHYTHM_LABELS).
export const DAY_RHYTHM_WIRE_VALUE_VI: Record<DayRhythmKey, string> = {
  earlyStart: 'bắt đầu sớm', lateNight: 'về khuya',
}

// Inverse lookups for pre-filling IntakeFormState from a server-sent
// (Vietnamese) intake snapshot — see intake-parameters-form.tsx's seed effect.
export function preferenceKeyFromWireValueVi(value: string): PreferenceKey | null { /* ... */ }
export function companionKeyFromWireValueVi(value: string): CompanionKey | null { /* ... */ }
export function paceKeyFromWireValueVi(value: string): PaceKey | null { /* ... */ }
export function dayRhythmKeyFromWireValueVi(value: string): DayRhythmKey | null { /* ... */ }
```

Add matching i18n entries under `intake.preferenceOptions.*`,
`intake.companionOptions.*`, `intake.paceOptions.*`, `intake.dayRhythmOptions.*`
in both `locales/en.json` and `locales/vi.json` (Phase 1 created the files;
this phase adds these nested keys since they didn't exist as flat `S.*`
entries before — they were arrays, now they're per-key labels).

### `IntakeFormState` changes (`frontend/src/lib/compose-intake-message.ts`)

- `preferences: string[]` → `preferences: PreferenceKey[]`
- `companions: string` → `companions: CompanionKey | ''`
- `pace: string` → `pace: PaceKey | ''`
- `dayRhythm: string[]` → `dayRhythm: DayRhythmKey[]`
- `budget: string` stays as-is (server-sourced Vietnamese label, out of
  scope — see plan.md).
- `composeIntakeMessage()` maps each canonical key through its
  `*_WIRE_VALUE_VI` lookup before building sentences, e.g.:
  ```ts
  if (form.preferences.length > 0) {
    const labels = form.preferences.map((k) => PREFERENCE_WIRE_VALUE_VI[k])
    sentences.push(`Sở thích: ${labels.join(', ')}.`)
  }
  ```
  This is the ONLY change to `composeIntakeMessage.ts`'s output-producing
  logic — the composed sentence text itself is unchanged, byte-for-byte,
  because the wire-value maps equal the current literal strings.

### `intake-parameters-form.tsx` changes

- `Chip` components render `t(`intake.preferenceOptions.${key}`)` for label,
  but `key`/selection state uses the canonical key, not the label.
- Map over `PREFERENCE_KEYS`/`COMPANION_KEYS`/`PACE_KEYS`/`DAY_RHYTHM_KEYS`
  (imported from `intake-options.ts`) instead of `S.intakePreferenceOptions`
  etc.
- The pre-fill effect (lines 86-108) currently does
  `preferences: intake.preferences?.length ? intake.preferences : prev.preferences`
  — `intake.preferences` comes from the server as Vietnamese wire strings.
  Convert with `intake.preferences.map(preferenceKeyFromWireValueVi).filter(Boolean)`
  before storing into `form.preferences`. Same pattern for
  `companions`/`pace`/`day_rhythm`.
- `budgetOptions`/`destinations` continue to render server strings verbatim
  (unchanged, out of scope).

### Plain component migration (the other 10 files)

Mechanical: replace `import { S } from '../strings'` with
`import { useTranslation } from 'react-i18next'` + `const { t } = useTranslation()`
inside the component, and `S.someKey` → `t('someKey')` /
`S.someKey(arg)` → `t('someKey', { n: arg })` (or the relevant placeholder
name from Phase 1's JSON). Files to touch (all currently importing `strings.ts`):

- `frontend/src/App.tsx`
- `frontend/src/components/chat-panel.tsx`
- `frontend/src/components/composer.tsx`
- `frontend/src/components/day-card.tsx`
- `frontend/src/components/elapsed-spinner.tsx`
- `frontend/src/components/hotel-option-card.tsx`
- `frontend/src/components/intake-parameters-form.tsx` (also gets the
  canonical-key changes above)
- `frontend/src/components/itinerary-panel.tsx`
- `frontend/src/components/map-panel.tsx`
- `frontend/src/components/message-list.tsx`
- `frontend/src/components/trip-parameters-card.tsx`
- `frontend/src/hooks/use-chat-session.ts` (non-component; use `i18n.t`
  directly via the shared `i18n` instance from `frontend/src/i18n/index.ts`,
  not the `useTranslation()` hook, since hooks are for components)

`hotelStars` call sites switch from `S.hotelStars(n)` to
`formatHotelStars(n)` (Phase 1's `lib/format-stars.ts`).

Any inline hardcoded strings not currently in `strings.ts` but visible in JSX
(spot-checked during Phase 1 grep, e.g. `aria-label="Giảm số khách"` /
`"Tăng số khách"` in `intake-parameters-form.tsx:212,224`, and the "Không có
tùy chọn ngân sách." fallback at line 249) get promoted into the locale JSON
files as new keys in this phase — they were missed by the original "seam"
because they predate this plan's audit.

### Wire the selected language to outgoing chat requests

- `frontend/src/api/chat-client.ts`: `sendMessage(sessionId, message, language)`
  adds `language` to the POST body.
- `frontend/src/hooks/use-chat-session.ts`: reads `i18n.language` at send
  time and passes it through.

### Delete `strings.ts`

Only after every import above is migrated and `grep -rl "strings'" frontend/src`
returns nothing. Delete `frontend/src/strings.ts`.

## Related Code Files

- Create: `frontend/src/lib/intake-options.ts`
- Modify: `frontend/src/lib/compose-intake-message.ts`
- Modify: `frontend/src/components/intake-parameters-form.tsx`
- Modify: all 10 other files listed above
- Modify: `frontend/src/api/chat-client.ts`, `frontend/src/i18n/locales/en.json`, `frontend/src/i18n/locales/vi.json`
- Delete: `frontend/src/strings.ts` (last step, once nothing imports it)

## Implementation Steps

1. Create `frontend/src/lib/intake-options.ts` per the sketch above; add the
   inverse-lookup helper implementations.
2. Add `intake.preferenceOptions.*` / `companionOptions.*` / `paceOptions.*` /
   `dayRhythmOptions.*` nested keys to both locale JSON files.
3. Update `compose-intake-message.ts`'s `IntakeFormState` type and
   `composeIntakeMessage()` body to use canonical keys + wire-value maps.
   Update its unit tests' fixtures to build `IntakeFormState` with canonical
   keys (existing composed-sentence assertions should need NO text changes,
   since output is unchanged).
4. Update `intake-parameters-form.tsx`: chip option lists, pre-fill
   conversion, `t()` calls for labels.
5. Migrate the remaining 10 files from `S.*` to `t()`, one file at a time,
   running `npm run typecheck` after each to catch missed call sites (a
   function-valued `S.foo(x)` left un-migrated fails typecheck once `S` no
   longer exists).
6. Add `language` to `sendMessage()` and wire it from `use-chat-session.ts`.
7. Promote the stray hardcoded strings found in step-by-step review (aria
   labels, "no budget options" fallback, etc.) into the locale files.
8. `grep -rl "from '../strings'\|from './strings'" frontend/src` — must be
   empty. Delete `frontend/src/strings.ts`.
9. `npm run typecheck && npm run lint && npm run build` in `frontend/`.

## Success Criteria

- [ ] `strings.ts` no longer exists; nothing imports it.
- [ ] Toggling the nav language switch (Phase 1) now visibly changes every
      piece of static text in the app, including intake form chip labels.
- [ ] Submitting the intake form with language = English still sends the
      exact same Vietnamese sentence to `/api/v1/planner_chat` as it did
      before this plan (verified in Phase 5 with a characterization test).
- [ ] `frontend/src/lib/compose-intake-message.test.*` (existing tests, if
      any, or the Python characterization test asserting on the composed
      message shape) pass unchanged.
- [ ] `npm run typecheck`, `npm run lint`, `npm run build` all pass.

## Risk Assessment

- **Risk:** missing a `preferenceKeyFromWireValueVi` match when the server
  pre-fills `intake.preferences` with a value that doesn't exactly match a
  known wire value (e.g. future backend label drift) silently drops that
  preference from the pre-filled form. **Mitigation:** the lookup helpers
  return `null` for unknown values and callers `.filter(Boolean)` — a dropped
  unknown preference degrades gracefully (user re-selects it) rather than
  crashing; log a `console.warn` in dev for visibility.
- **Risk:** large mechanical find/replace across 12 files introduces a typo
  or missed call site. **Mitigation:** `npm run typecheck` after every file
  (function-valued keys have distinct call signatures from `t()`, so most
  mistakes are compile errors, not silent runtime bugs).
- **Risk:** `composeIntakeMessage` output accidentally changes (e.g. extra
  whitespace from a template swap). **Mitigation:** keep the existing
  Python-side characterization test (`tests/test_intake_form_characterization.py`)
  as the ground truth — Phase 5 re-runs it against the new frontend logic
  conceptually via a frontend-side snapshot test of `composeIntakeMessage()`
  output for a fixed `IntakeFormState`, diffed against the pre-refactor
  string.
