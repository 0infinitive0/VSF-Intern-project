---
phase: 1
title: "Frontend i18n Foundation"
status: pending
priority: P1
effort: "1d"
dependencies: []
---

# Phase 1: Frontend i18n Foundation

## Overview

Install and wire up `react-i18next`, scaffold `en`/`vi` locale resource files
mirroring the current `strings.ts` keys, and add the nav-bar language toggle.
This phase does NOT migrate any component off `S.*` yet — it only builds the
plumbing so Phase 2 can do a mechanical migration.

## Requirements

- Functional: `i18n.changeLanguage('en'|'vi')` immediately re-renders translated
  text; language choice persists across reload; default language is `vi` for
  a first-time visitor.
- Non-functional: no new heavy dependency beyond `i18next` +
  `react-i18next` (skip `i18next-browser-languagedetector` — manual toggle
  only, per confirmed scope, so auto-detection is unneeded complexity).

## Architecture

`main.tsx` initializes `i18next` before rendering `<App />` (i18next must be
configured before any component calls `useTranslation()`). Resources load
synchronously from local JSON imports (no HTTP backend needed — the whole
catalog is small).

```
frontend/src/
  i18n/
    index.ts            # i18next.init(), reads/writes localStorage
    locales/
      en.json
      vi.json
  components/
    language-toggle.tsx # new
```

`i18n/index.ts` sketch:

```ts
import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import en from './locales/en.json'
import vi from './locales/vi.json'

const STORAGE_KEY = 'vota-language'
const stored = localStorage.getItem(STORAGE_KEY)
const initialLanguage = stored === 'en' || stored === 'vi' ? stored : 'vi'

i18n.use(initReactI18next).init({
  resources: { en: { translation: en }, vi: { translation: vi } },
  lng: initialLanguage,
  fallbackLng: 'vi',
  interpolation: { escapeValue: false }, // React already escapes
})

i18n.on('languageChanged', (lng) => localStorage.setItem(STORAGE_KEY, lng))

export default i18n
export { STORAGE_KEY }
```

`locales/vi.json` values MUST be byte-identical to the current values in
`frontend/src/strings.ts` — this phase is pure scaffolding, not translation
review, and any drift would be a silent regression on the default language.
Function-valued entries in `strings.ts` (e.g. `dayLabel: (n) => \`Ngày ${n}\``)
become interpolated string templates:

```json
{
  "dayLabel": "Ngày {{n}}",
  "adjustmentsLabel": "Điều chỉnh",
  "statusLabel": "Trạng thái: {{s}}",
  "hotelAverageNightly": "{{price}} {{currency}}/đêm",
  "hotelTotalStay": "Tổng {{nights}} đêm: {{price}} {{currency}}",
  "intakeNotesCounter": "{{n}}/1000",
  "errorNetwork": "Lỗi kết nối: {{msg}}"
}
```

`hotelStars: (n) => '★'.repeat(n)` is NOT a translation — it's a rendering
utility with no language dependency. Move it to
`frontend/src/lib/format-stars.ts` as a plain exported function; it does not
belong in the locale JSON.

`en.json` gets real English translations for every key (this phase writes
them; Phase 2 wires components to use them). Preserve exact interpolation
placeholder names between `en.json` and `vi.json` so `t(key, {n: 3})` works
for either locale without per-call branching.

## Related Code Files

- Create: `frontend/src/i18n/index.ts`
- Create: `frontend/src/i18n/locales/en.json`
- Create: `frontend/src/i18n/locales/vi.json`
- Create: `frontend/src/lib/format-stars.ts`
- Create: `frontend/src/components/language-toggle.tsx`
- Modify: `frontend/src/main.tsx` (import `./i18n` before rendering)
- Modify: `frontend/package.json` (add `i18next`, `react-i18next`)

## Implementation Steps

1. `npm install i18next react-i18next` in `frontend/`.
2. Create `frontend/src/i18n/locales/vi.json` by transcribing every entry from
   `frontend/src/strings.ts` (`S` object), converting function-valued entries
   to `{{placeholder}}` templates as shown above. Keep the same key names so
   Phase 2's `S.foo` → `t('foo')` migration is a pure find/replace.
3. Create `frontend/src/i18n/locales/en.json` with an English translation for
   every key in `vi.json` (same key set, same placeholder names).
4. Create `frontend/src/lib/format-stars.ts` exporting `formatHotelStars(n: number): string`.
5. Create `frontend/src/i18n/index.ts` per the sketch above.
6. Add `import './i18n'` to the top of `frontend/src/main.tsx`, before the
   `App` import (i18next config must run before first render).
7. Build `LanguageToggle` (`frontend/src/components/language-toggle.tsx`): a
   small two-state control (EN | VI) using `useTranslation()`'s `i18n` object,
   calling `i18n.changeLanguage(next)` on click. Accessible: `role="group"`,
   each option a `<button aria-pressed={...}>`.
8. Mount `<LanguageToggle />` in `App.tsx`'s header, next to the existing nav
   items (`frontend/src/App.tsx:27-52` — the `<nav>`/right-side `<div>` block).
   Do not remove or restyle existing nav items in this phase.

## Success Criteria

- [ ] `npm run typecheck` and `npm run lint` pass with the new files.
- [ ] Rendering `<App />` in dev (`npm run dev`) shows the toggle in the nav;
      clicking it changes `localStorage['vota-language']` and
      `document`-visible `i18n.language`, but (expected, until Phase 2) no
      component text changes yet since components still read `S.*` directly.
- [ ] `vi.json` values are byte-identical to current `strings.ts` values
      (verified by a quick diff/spot-check, not just visual).

## Risk Assessment

- **Risk:** transcription typo between `strings.ts` and `vi.json` silently
  changes default-language text. **Mitigation:** Phase 2 keeps `strings.ts`
  in the repo (unused) until the migration is verified, so a diff against it
  is possible; delete `strings.ts` only at the end of Phase 2.
- **Risk:** `i18next.init()` running after first render leaves the first
  paint untranslated. **Mitigation:** the `init()` call in `i18n/index.ts`
  is synchronous (local JSON resources, no HTTP backend), and step 6 imports
  it before `App` renders — no async gap.
