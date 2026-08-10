---
phase: 1
title: "Design tokens, TypeScript setup, and shared types"
status: completed
priority: P1
effort: "0.5d"
dependencies: []
---

# Phase 1: Design tokens, TypeScript setup, and shared types

## Overview

Foundation phase: add the TypeScript toolchain (currently absent — no `tsconfig.json`,
no `typescript` package), define shared type interfaces for the chat/trip-plan contract,
and extend `frontend/src/styles.css` with the new Stitch color tokens. Every later phase
depends on this one.

## Requirements

- Functional: `npx tsc --noEmit` runs and type-checks the project (even before other
  phases convert their files, so the baseline is clean from the start).
- Functional: Vite dev server still boots and renders the existing app unchanged after
  this phase (pure setup + token addition, zero visual/behavioral change yet).
- Functional: a single `frontend/src/types.ts` module exports every interface phases 2-6
  need, so no phase invents ad-hoc duplicate shapes.
- Non-functional: new tokens are additive — do not remove or repoint any existing
  `--color-*` token still read by unconverted components mid-migration.

## Architecture

Tailwind v4 here is CSS-first (`@import "tailwindcss"` + `@theme` block in
`styles.css:6-33`), **not** the JS `tailwind.config` the Stitch exports use. Translate
only the tokens actually needed by later phases (not the full Material-3 palette Stitch
generates) as CSS custom properties.

## Related Code Files

- Create: `frontend/tsconfig.json`
- Create: `frontend/src/vite-env.d.ts` (Vite's ambient `ImportMetaEnv` types)
- Create: `frontend/src/types.ts`
- Modify: `frontend/package.json` (add `typescript` devDependency, add `"typecheck": "tsc --noEmit"` script)
- Modify: `frontend/vite.config.js` → rename to `frontend/vite.config.ts`
- Modify: `frontend/src/strings.js` → rename to `frontend/src/strings.ts`
- Modify: `frontend/src/styles.css` (extend `@theme` block)

`index.html`'s script tag (`src="/src/main.jsx"`) and `App.jsx`/`main.jsx` themselves are
renamed in Phase 2, not here — this phase only prepares tooling and converts the two
files with no JSX (`strings.js`, `vite.config.js`) plus the new pure-TS files.

## Implementation Steps

1. `cd frontend && npm install --save-dev typescript`. Confirm `@types/react` /
   `@types/react-dom` in `package.json` devDependencies are version-compatible with the
   installed `react`/`react-dom` (`^19.2.8`).
2. Create `frontend/tsconfig.json`:
   ```jsonc
   {
     "compilerOptions": {
       "target": "ES2022",
       "lib": ["ES2022", "DOM", "DOM.Iterable"],
       "module": "ESNext",
       "moduleResolution": "bundler",
       "jsx": "react-jsx",
       "strict": true,
       "noUnusedLocals": true,
       "noUnusedParameters": true,
       "noFallthroughCasesInSwitch": true,
       "skipLibCheck": true,
       "allowJs": true,
       "esModuleInterop": true,
       "isolatedModules": true,
       "noEmit": true
     },
     "include": ["src"]
   }
   ```
   `allowJs: true` is load-bearing: phases land incrementally, so `.jsx`/`.js` files not
   yet converted by a given phase must keep compiling alongside new `.tsx`/`.ts` ones.
3. Create `frontend/src/vite-env.d.ts` with `/// <reference types="vite/client" />`.
4. Rename `frontend/vite.config.js` → `frontend/vite.config.ts` (content unchanged;
   Vite's TS config support needs no code changes for this project's minimal config).
5. Add `"typecheck": "tsc --noEmit"` to `package.json` `scripts`.
6. Create `frontend/src/types.ts` with the shapes verified against
   `src/services/trip_formatter.py:238-345` (Python → payload field names, not guessed):
   ```typescript
   export interface Suggestion {
     label: string
     value: string
   }

   export interface HotelOption {
     index: number
     id?: string
     name: string
     star_rating?: number
     description?: string
     matched_rooms?: string[]
     average_nightly_price?: number
     total_stay_price?: number
     stay_night_count?: number
     currency?: string
   }

   export interface DayItem {
     order_index: number
     start_time: string | null
     end_time: string | null
     activity: string
     kind?: string | null
     reference_type?: string | null
     reference_id?: string | null
   }

   export interface Day {
     day_number: number
     theme: string
     items: DayItem[]
   }

   export interface Hotel {
     id?: string
     name: string
     star_rating?: number
     description?: string
     matched_rooms?: string[]
     // WKT/string form from the backend (src/models/schemas.py:110), not {lat,lng} — do
     // not restructure it; the map phase is deferred and does not consume this field.
     coordinates?: string | null
   }

   export type TripStatus = string // backend sends free-text status, e.g. "Draft"

   export interface TripPlan {
     status: TripStatus
     destination: string | null
     duration_days: number
     start_date: string | null
     end_date: string | null
     number_of_adults: number | null
     hotel: Hotel | null
     days: Day[]
     adjustments: string[]
   }

   export type MessageRole = 'user' | 'ai'
   export type Stage = 'hotel_options' | 'error' | string | null

   export interface ChatMessage {
     id: string
     role: MessageRole
     text: string
     stage: Stage
     isError?: boolean
   }

   export interface ChatState {
     sessionId: string | null
     messages: ChatMessage[]
     suggestions: Suggestion[]
     hotelOptions: HotelOption[]
     tripPlan: TripPlan | null
     pending: boolean
     elapsedMs: number
     error: string | null
   }
   ```
7. Extend the `@theme` block in `frontend/src/styles.css` (append, do not remove or
   change existing tokens). **Verified by cross-checking the `tailwind-config` block in
   all 4 `assets/*.html` files, not just one** — `primary`/`primary-container` agree
   with the current tokens in 3 of 4 screens (`01`, `02`, `03`); only `04` is a
   divergent generation outlier (`primary: #2c61fe`) and is intentionally **not**
   adopted, so `styles.css:12` (`--color-primary: #0047dd`) and `:14`
   (`--color-primary-container: #2c61fe`) stay untouched:
   ```css
   /* New Stitch tokens — consistent across all 4 assets/*.html exports */
   --color-secondary: #585e6d;
   --color-secondary-container: #dadff0;
   --color-on-secondary-container: #5d6371;
   --color-outline: #737687;
   --color-outline-variant: #c3c5d8;
   --color-surface-container-low: #f1f3ff;
   --color-surface-container-high: #e2e8fc;
   --color-surface-container-highest: #dde2f6;
   ```
   `styles.css:21` already has `--color-surface-container: #e9edff`, which matches the
   Stitch base step exactly — do not duplicate it, only add the `-low`/`-high`/
   `-highest` steps shown above.
8. Rename `strings.js` → `strings.ts`. It's a flat exported object of strings and small
   functions (`strings.js:7-54`) — no structural change needed, TypeScript infers the
   shape; do not add an explicit interface for it (unnecessary ceremony for a literal
   object that's only ever imported as `S`).
9. Run `npx tsc --noEmit` from `frontend/` — must pass (`types.ts`, `vite-env.d.ts`,
   `strings.ts`, `vite.config.ts` are TS at this point; every component is still
   `.jsx`/`.js` under `allowJs` until phases 2-6 convert them).
10. Run `npm run dev` and confirm the app renders identically to before this phase —
    pure no-op visually, since no component styling changed and `primary`/
    `primary-container` are unchanged (see Step 7).

## Success Criteria

- [x] `frontend/tsconfig.json`, `vite-env.d.ts`, and `types.ts` exist.
- [x] `strings.ts` exists, `strings.js` removed.
- [x] `npx tsc --noEmit` passes clean from `frontend/`.
- [x] `npm run dev` boots without error; existing `.jsx` components still work under `allowJs`.
- [x] `styles.css` has the new tokens appended, no existing token removed or changed in value.
- [x] `git diff --stat frontend/` shows no component file (`components/`, `hooks/`, `api/`, `App.jsx`, `main.jsx`) changed in this phase — only config, styles, `strings`, and new `.ts` files.

## Risk Assessment

- **Risk:** `strict: true` in `tsconfig.json` surfaces type errors in later phases that
  were invisible in plain JS (e.g. implicit `any`, null-safety on optional backend
  fields). **Mitigation:** intentional — catching these is why TypeScript was requested;
  budget time in phases 2-6 for fixing, not disabling strict mode.
