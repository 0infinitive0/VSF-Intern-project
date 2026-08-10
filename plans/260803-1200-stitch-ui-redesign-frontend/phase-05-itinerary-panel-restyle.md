---
phase: 5
title: "Itinerary panel restyle"
status: completed
priority: P1
effort: "1d"
dependencies: [1, 4]
---

# Phase 5: Itinerary panel restyle

## Overview

Restyle `ItineraryPanel` and `DayCard` to the Stitch center-column look: a tab row
(Itinerary active, Ideas disabled), a trip header with real destination/dates, and
activity rows with a category icon/badge derived from real `item.kind` data. Convert
both files to `.tsx`.

## Requirements

- Functional: tab row shows **Itinerary** (active) and **Ideas** (`disabled`, per
  Decision 2 — no ideas/recommendations data source exists). Do not wire Ideas to
  anything.
- Functional: an `open_in_full` icon button is decorative-only chrome (no fullscreen
  mode exists) — render `disabled`.
- Functional: keep the existing day-nav pills (`itinerary-panel.jsx:54-67`) — this part
  already matches the Stitch "Day 1 / Day 2" pill row almost exactly, just restyle
  colors/spacing. The Stitch mock's trailing `+` "add day" pill has no backend action
  (no create-custom-day endpoint) — render `disabled`, consistent with the Ideas tab
  treatment, not omitted (it's the same category of gap as the nav tabs in Phase 2).
- Functional: panel header shows `tripPlan.destination` (fallback to
  `S.itineraryTitle` when `null`) as the `<h1>`, plus a date/guests summary row using
  `tripPlan.number_of_adults` and `formatTripDateRange(tripPlan.start_date, tripPlan.end_date)`
  imported from `frontend/src/lib/format-trip-dates.ts` (created in Phase 4 — do not
  duplicate the formatter here).
- Functional: header's `edit`/`share` icon buttons are decorative chrome (no edit-trip
  or share-link feature exists) — render `disabled`.
- Functional: activity rows (`DayCard`, `day-card.jsx:30-44`) gain a small category
  badge using `item.kind` (already in `DayItem` per `types.ts`). The authoritative
  vocabulary (verified during plan validation against
  `src/services/trip_edit_planner.py:31`: `ItemKind = Literal["breakfast", "attraction",
  "lunch", "rest", "coffee", "dinner", "evening"]`) is exactly 7 values — map each to a
  label + Material Symbol:
  `breakfast`→`egg_alt`/"Breakfast", `lunch`→`lunch_dining`/"Lunch",
  `dinner`→`dinner_dining`/"Dinner", `coffee`→`coffee`/"Coffee",
  `attraction`→`attractions`/"Sight", `rest`→`hotel`/"Rest", `evening`→`nightlife`/
  "Evening". Unknown/`null`/any value outside this set → no badge, not a fabricated
  default (the enum is a `Literal`, but the payload is untyped JSON over the wire, so a
  future backend change or a stale record could still send something else).
  <!-- Updated: Validation Session 1 - replaced guessed kind→label mapping with the
  verified ItemKind enum -->
- Functional: activity rows get a fixed `w-20 h-20 rounded-lg bg-surface-muted` icon
  slot (same category icon, larger) **instead of** the Stitch mock's real per-activity
  stock photo (`data-alt` fabricated descriptions) — no photos, per Decision 2.
- Functional: **do not build** the Stitch mock's "Finding dinner spots nearby..." /
  "Planning itinerary..." per-day skeleton loading states
  (`assets/04-detailed-itinerary-chat.html`, `animate-pulse`/`animate-spin` blocks).
  These imply day-by-day incremental generation; the actual contract delivers a
  complete `trip_plan.days[]` per turn (`use-chat-session.js:85`), never partial days —
  building this skeleton would fabricate a generation-progress signal the backend
  doesn't send. The existing whole-panel empty state (`itinerary-panel.jsx:17-35`) and
  `ElapsedSpinner` (Phase 3, shown in the chat panel while `pending`) are the real,
  honest equivalents and are unchanged by this phase.
- Functional: per-activity "View Map" link is **omitted** — no per-activity
  coordinates exist (only `hotel.coordinates`, and the map is deferred per Phase 6/
  Decision 3 anyway).
- Non-functional: day accent-color cycling (`day-card.jsx:5,11`) is unchanged —
  already a real, working detail; just adjust the 5 accent hex values if needed to sit
  well against the new `surface-container` tokens (visual judgment call during
  implementation, not a hard requirement).

## Architecture

Reference markup (`assets/02-unified-itinerary-view.html` for tabs/pills,
`assets/04-detailed-itinerary-chat.html` for header/activity row), adapted per
Requirements (photos → icon slots, skeleton states removed, View Map removed,
Ideas/+day/edit/share disabled):

```html
<!-- Tabs -->
<div class="flex items-center justify-between px-4 pt-3 border-b border-border-subtle">
  <div class="flex gap-6">
    <button class="text-sm font-semibold text-text-primary border-b-2 border-primary pb-2">Itinerary</button>
    <button class="text-sm text-text-secondary pb-2" disabled>Ideas</button>
  </div>
  <button class="p-1 text-text-secondary" disabled><span class="material-symbols-outlined text-[18px]">open_in_full</span></button>
</div>

<!-- Header -->
<h1 class="font-display text-2xl font-bold text-on-surface">{destination}</h1>
<div class="flex items-center gap-5 text-text-secondary text-sm bg-surface-muted p-3.5 rounded-lg border border-border-subtle/50">
  <span class="material-symbols-outlined text-[18px]">calendar_month</span> {dateRange}
  <span class="material-symbols-outlined text-[18px]">group</span> {numberOfAdults} Adults
</div>

<!-- Activity row -->
<div class="flex gap-4">
  <div class="w-20 h-20 rounded-lg bg-surface-muted shrink-0 flex items-center justify-center">
    <span class="material-symbols-outlined text-on-surface-variant">place</span>
  </div>
  <div class="flex-1">
    <span class="text-[11px] text-on-surface-variant uppercase font-semibold">{start_time} • {duration}</span>
    <h4 class="text-[16px] text-on-surface mt-1 font-medium">{activity}</h4>
    <span class="bg-surface-container-high text-on-surface-variant text-[11px] px-2.5 py-1 rounded-md">{kindLabel}</span>
  </div>
</div>
```

## Related Code Files

- Modify: `frontend/src/components/itinerary-panel.jsx` → `itinerary-panel.tsx`
- Modify: `frontend/src/components/day-card.jsx` → `day-card.tsx`
- Modify: `frontend/src/strings.ts` (add `ideasTabLabel`, `itineraryTabLabel`,
  `addDayLabel` for the disabled `+` pill's `aria-label`; kind-label strings
  `kindBreakfast`, `kindLunch`, `kindDinner`, `kindCoffee`, `kindAttraction`,
  `kindRest`, `kindEvening` — the 7 verified `ItemKind` values, see Requirements)

## Implementation Steps

1. Convert `day-card.tsx`: add the `kind`-based category badge + icon slot, using the
   verified 7-value `ItemKind` → label/icon map from Requirements directly (no further
   verification needed — already confirmed against `trip_edit_planner.py:31` during
   plan validation).
2. Convert `itinerary-panel.tsx`: rebuild the header (destination + date/guest summary
   via `formatTripDateRange` from `frontend/src/lib/format-trip-dates.ts`, disabled
   edit/share), tab row (Itinerary active, Ideas disabled), keep day-nav pills logic
   (`scrollToDay`, `dayRefs`) unchanged, add disabled `+` pill at the end of the pill row.
3. Add new strings; run `npx tsc --noEmit`; manually verify against a live `trip_plan`
   response (send a full chat flow through to itinerary generation) — confirm dates,
   destination, and per-item kind badges render correctly, and that nothing resembling
   a "Finding X nearby..." skeleton appears anywhere.

## Success Criteria

- [x] Itinerary panel header shows real destination + date/guest summary, no fabricated data.
- [x] Tabs show Itinerary (active) / Ideas (disabled); `+` day pill disabled; edit/share icons disabled.
- [x] Activity rows show a category icon slot (no fake photos) and a kind badge only when `kind` is present.
- [x] No per-day "generating"/"finding X nearby" skeleton states exist anywhere in the diff.
- [x] No "View Map" link anywhere in `day-card.tsx`.
- [x] `npx tsc --noEmit` clean.

## Risk Assessment

- **Risk:** a future backend change adds an 8th `kind` value, or a stale/malformed
  record sends something outside the verified enum. **Mitigation:** already designed
  for — unmapped values render with no badge (Requirements), never a guessed default.
- **Risk:** this phase depends on `frontend/src/lib/format-trip-dates.ts` existing from
  Phase 4. **Mitigation:** the phase dependency (`dependencies: [1, 4]` in this file's
  frontmatter) already encodes that ordering; if phases are ever cooked out of order,
  create the formatter here instead of duplicating Phase 4's spec.
