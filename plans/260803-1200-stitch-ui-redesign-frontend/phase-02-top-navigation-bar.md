---
phase: 2
title: "Top navigation bar"
status: completed
priority: P1
effort: "0.5d"
dependencies: [1]
---

# Phase 2: Top navigation bar

## Overview

Replace `App.jsx`'s simple header (`App.jsx:21-49`: logo + title/subtitle + one reset
button) with the Stitch top nav: branding, a tab row (only **Trips** functional), and a
right-side action cluster. Convert `App.jsx` → `App.tsx` in the same phase since the
header lives inside it.

## Requirements

- Functional: "V-OTA AI" wordmark uses `font-display` (Hanken Grotesk), matching the
  Stitch markup's `font-headline-md font-bold text-primary`.
- Functional: three nav links — Explorer / Trips / Concierge. Only **Trips** is a real
  active state (`text-primary border-b-2 border-primary font-semibold`, per Decision 1
  in `plan.md` — this app *is* the trip flow). Explorer and Concierge render as
  `<button disabled>` (not `<a href="#">` — Stitch's mock uses dead links; a real disabled
  button is the honest equivalent, per Decision 2's "static chrome, never fake
  interactivity").
- Functional: right cluster keeps the existing reset action (`App.jsx:39-47`,
  `handleReset` → `S.newChatBtn` / `S.newChatConfirm`), restyled as the Stitch
  "Generate Itinerary"-style primary pill button but keeping its real label and behavior
  — do not rename it to "Generate Itinerary" (that implies a different action the app
  doesn't have; relabeling a working reset button to imply new functionality would be
  its own kind of fake affordance).
- Functional: notification bell and help/settings icons render as Material Symbols,
  `disabled`/inert (no notification system, no help center exists) — visible chrome
  only, per Decision 2.
- Functional: the Stitch mock's avatar is a **real stock photo URL**
  (`lh3.googleusercontent.com/aida-public/...`) — do **not** use it or any placeholder
  photo. There is no auth/profile system. Render a generic
  `<span class="material-symbols-outlined">account_circle</span>` instead.
- Non-functional: nav tabs collapse behind existing responsive breakpoints — reuse the
  Stitch markup's `hidden md:flex` pattern so mobile (360px) keeps working per the
  plan's existing non-functional requirement.

## Architecture

Reference markup (`assets/04-detailed-itinerary-chat.html`, extracted verbatim, for
class-name fidelity — adapt tag semantics per Requirements above, do not copy the fake
avatar `<img>` or the dead `<a href="#">` links):

```html
<div class="flex items-center gap-2">
  <span class="font-headline-md text-headline-md font-bold text-primary tracking-tight">V-OTA AI</span>
</div>
<div class="hidden md:flex items-center gap-8 h-full">
  <a class="text-on-surface-variant hover:text-primary h-full flex items-center px-2 transition-all font-body-lg" href="#">Explorer</a>
  <a class="text-primary border-b-2 border-primary font-semibold h-full flex items-center px-2 transition-all font-body-lg" href="#">Trips</a>
  <a class="text-on-surface-variant hover:text-primary h-full flex items-center px-2 transition-all font-body-lg" href="#">Concierge</a>
</div>
<div class="flex items-center gap-4">
  <button class="hidden md:flex items-center gap-2 bg-primary text-on-primary px-5 py-2.5 rounded-lg font-label-md hover:bg-opacity-90 transition-colors shadow-sm">
    <span class="material-symbols-outlined text-[18px]">add</span>
    Generate Itinerary
  </button>
  <div class="flex items-center gap-2">
    <span class="material-symbols-outlined ..." data-icon="notifications">notifications</span>
    <span class="material-symbols-outlined ..." data-icon="help">help</span>
  </div>
  <img ... /> <!-- DO NOT COPY: fake stock photo, see Requirements -->
</div>
```

`font-headline-md`/`font-body-lg`/`font-label-md` are Stitch-generated utility classes
that do not exist in this project's Tailwind config — reuse the project's existing
`font-display`/`font-sans` + explicit `text-lg`/`text-sm` sizing instead (do not import
Stitch's custom font-size utility layer just for this one component).

## Related Code Files

- Modify: `frontend/src/App.jsx` → rename to `frontend/src/App.tsx`
- Modify: `frontend/src/strings.ts` (converted in Phase 1 — add new nav-tab strings here)
- Modify: `frontend/src/main.jsx` → rename to `frontend/src/main.tsx`
- Modify: `frontend/index.html` (`src="/src/main.jsx"` → `src="/src/main.tsx"`)

## Implementation Steps

1. Rename `App.jsx` → `App.tsx`. Type the component `export default function App(): JSX.Element`.
   `useChatSession()` already returns `{ state, send, reset }` — once
   `use-chat-session.js` is typed in Phase 3, `state` types itself as `ChatState` from
   `types.ts` (Phase 1); until then this file compiles under `allowJs` inference.
2. Rename `main.jsx` → `main.tsx`; update `index.html`'s script `src`.
3. Add to `strings.ts`: `navExplorer: 'Explorer'`, `navTrips: 'Trips'`,
   `navConcierge: 'Concierge'` (English is fine here — these are inert labels, not part
   of the Vietnamese user-facing conversation flow the rest of `strings.js` covers; note
   this as an intentional exception in a one-line comment above the three keys).
4. Rewrite the `<header>` block (`App.jsx:21-49`) into three sections — branding, nav
   tabs, action cluster — per Requirements. Keep `handleReset`/`S.newChatBtn` wired
   exactly as today; only the visual container changes.
5. Style nav tabs with the new `secondary`/`outline` tokens from Phase 1 where the
   Stitch markup calls for `on-surface-variant` (map to existing
   `--color-text-secondary`/`--color-on-surface-variant`, already in `styles.css`).
6. Verify `npx tsc --noEmit` and `npm run dev` — header renders, reset still works,
   Explorer/Concierge tabs and bell/help icons are visibly present but inert.

## Success Criteria

- [x] `App.tsx`, `main.tsx` exist; `App.jsx`, `main.jsx` removed; `index.html` points at `main.tsx`.
- [x] Top nav shows V-OTA AI branding, 3 tabs (only Trips active-styled), reset button, 2 inert icons, and a generic account icon (no fake photo).
- [x] Reset flow (`handleReset` → confirm → `reset()`) behaves identically to before this phase.
- [x] `npx tsc --noEmit` clean.
- [x] No `<img>` pointing at any `googleusercontent.com`/stock-photo URL anywhere in the diff.

## Risk Assessment

- **Risk:** disabled Explorer/Concierge tabs could read as broken/unfinished UI to an
  end user unfamiliar with the design intent. **Mitigation:** use `disabled` + reduced
  opacity + `cursor-not-allowed`, consistent with how `MapPanel`'s existing "under
  development" framing already communicates non-functional-by-design areas — same
  visual language, no surprise.
- **Risk:** renaming `App.jsx`/`main.jsx` mid-migration could break other in-flight work
  on `dev` if someone else has uncommitted changes to those files. **Mitigation:** check
  `git status` immediately before this phase's edits (already project policy); this is a
  rename+edit, not a delete — `git mv` preserves history.
