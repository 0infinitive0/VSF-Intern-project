---
phase: 6
title: "Map panel chrome (deferred functionality)"
status: completed
priority: P2
effort: "0.5d"
dependencies: [1]
---

# Phase 6: Map panel chrome (deferred functionality)

## Overview

Restyle `MapPanel`'s chrome to match the Stitch right-column look — filter pills, a
search affordance, floating zoom/layer controls — while keeping it **exactly as
non-functional as it is today**. This is the direct continuation of the current
`MapPanel` docstring ("No map data source is wired up yet, so this stays a plain
illustrative panel rather than fake interactive controls") — same principle, new visual
skin.

**Do not integrate a map library, do not add tiles, do not add pins bound to real
coordinates in this phase.** That is future work explicitly out of scope (per `plan.md`
Decision 3, set by the user before this plan was written).

## Requirements

- Functional: filter pills (Attractions / Properties / Food / Shopping, per the Stitch
  mocks) render but are `disabled` — no filtering exists because there is nothing to
  filter (no map data). Same treatment as Explorer/Concierge (Phase 2) and Ideas
  (Phase 5) — consistent disabled-chrome language app-wide.
- Functional: the Stitch mock's map surface is a **real fake stock photo**
  pretending to be a stylized map (`assets/03-parameters-hotel-selection.html`, an
  `<img>` with `data-alt` describing "an overhead view of a clean, stylized digital map
  of Hanoi..."). **Do not use this or any similar photo/screenshot.** A photo dressed up
  as a map is the single worst kind of fake data for this component — it actively
  misrepresents functionality that doesn't exist. Keep the current dot-grid pattern
  background (`map-panel.jsx:11-18`), restyled with the new tokens, not replaced.
- Functional: floating tool buttons (`layers`, `my_location`, zoom `+`/`-`) render,
  `disabled`, matching `assets/03-parameters-hotel-selection.html`'s "Floating Map
  Tools" cluster.
- Functional: a top search input (`assets/03-parameters-hotel-selection.html`'s map
  overlay) renders `disabled` with a placeholder like "Search this area" — no live
  search exists.
- Functional: keep the existing centered placeholder message
  (`map-panel.jsx:19-25`, `S.mapPlaceholderTitle` / `S.mapPlaceholderBody`) — it is
  still accurate and already honest; restyle its container, don't remove it. Position it
  so it reads clearly above/behind the new disabled chrome (e.g. the chrome sits at the
  edges, the message stays centered, per the Stitch layout's own overlay pattern).
- Non-functional: no new npm dependencies (no map library) in this phase.

## Architecture

Reference markup (`assets/03-parameters-hotel-selection.html`), adapted per
Requirements (fake map photo removed, all controls `disabled`):

```html
<section class="flex-1 relative bg-surface-muted overflow-hidden">
  <!-- dot-grid background, unchanged from current MapPanel -->

  <!-- Top overlay: filter pills -->
  <div class="absolute top-4 left-4 flex gap-2">
    <button disabled class="bg-surface-background border border-outline-variant px-3 py-2 rounded-lg flex items-center gap-2 text-sm opacity-60 cursor-not-allowed">
      <span class="material-symbols-outlined text-sm text-primary">attractions</span> Attractions
    </button>
    <button disabled class="bg-surface-background border border-outline-variant px-3 py-2 rounded-lg flex items-center gap-2 text-sm opacity-60 cursor-not-allowed">
      <span class="material-symbols-outlined text-sm">hotel</span> Properties
    </button>
  </div>

  <!-- Floating tools -->
  <div class="absolute bottom-8 right-6 flex flex-col gap-2">
    <button disabled class="w-10 h-10 bg-surface-background rounded-lg border border-outline-variant flex items-center justify-center opacity-60 cursor-not-allowed">
      <span class="material-symbols-outlined text-sm">layers</span>
    </button>
    <button disabled class="w-10 h-10 bg-surface-background rounded-lg border border-outline-variant flex items-center justify-center opacity-60 cursor-not-allowed">
      <span class="material-symbols-outlined text-sm">my_location</span>
    </button>
    <div class="flex flex-col bg-surface-background rounded-lg border border-outline-variant overflow-hidden mt-2">
      <button disabled class="w-10 h-10 flex items-center justify-center opacity-60 cursor-not-allowed">+</button>
      <button disabled class="w-10 h-10 flex items-center justify-center opacity-60 cursor-not-allowed">-</button>
    </div>
  </div>

  <!-- Centered placeholder message, existing, restyled -->
  <div class="relative text-center text-text-secondary px-6 z-10">
    <span class="material-symbols-outlined text-4xl">map</span>
    <div class="font-medium text-text-primary mt-2">{S.mapPlaceholderTitle}</div>
    <div class="text-sm mt-1">{S.mapPlaceholderBody}</div>
  </div>
</section>
```

## Related Code Files

- Modify: `frontend/src/components/map-panel.jsx` → `map-panel.tsx`
- Modify: `frontend/src/strings.ts` (add `mapFilterAttractions`,
  `mapFilterProperties`, `mapFilterFood`, `mapFilterShopping`, `mapSearchPlaceholder` —
  these can carry an `aria-label` explaining the control is not yet available, e.g. a
  shared `mapControlDisabledHint` string used as `title=` on every disabled control)

## Implementation Steps

1. Convert `map-panel.jsx` → `.tsx` (no props today — confirm still true after Phase 5;
   if the itinerary panel ever needs to pass day/hotel data down for a future real map,
   that's out of scope here — keep the component prop-less).
2. Add the disabled filter-pill row, floating tool cluster, and disabled search input
   per Architecture, keeping the existing dot-grid background and centered message
   exactly as they are today, just retokened to `outline-variant`/`surface-container`.
3. Add new strings; run `npx tsc --noEmit`.
4. Manual check: confirm no control in this panel is clickable/interactive, no map
   library was added to `package.json`, and no photo/image asset was introduced.

## Success Criteria

- [x] `map-panel.tsx` has zero new npm dependencies and zero real interactivity — every added control is `disabled`.
- [x] No stock photo or "map screenshot" image anywhere in the component.
- [x] Existing placeholder message still renders, restyled, still legible.
- [x] `npx tsc --noEmit` clean.
- [x] `git diff frontend/package.json` shows no changes from this phase.

## Risk Assessment

- **Risk:** a reviewer or user could mistake the restyled chrome for a real, almost-working
  map and file a bug ("filters don't work"). **Mitigation:** every disabled control gets
  a `title`/`aria-label` hint (e.g. "Map integration coming soon") so the non-functional
  state is discoverable on hover/screen-reader, not just visually implied by opacity.
- **Risk:** scope creep toward "just add Leaflet/Mapbox since we're already touching
  this file" — explicitly rejected. **Mitigation:** this phase's Success Criteria
  hard-gates on zero new dependencies; flag any temptation to add one back to the user
  rather than doing it unasked (this was an explicit, deliberate user decision going
  into this plan).
