---
phase: 4
title: "Hotel cards and trip parameters"
status: completed
priority: P1
effort: "0.75d"
dependencies: [1, 3]
---

# Phase 4: Hotel cards and trip parameters

## Overview

Restyle `HotelOptionCard` to the Stitch list-row style and add a new `TripParameters`
component showing the fields the backend already returns
(`trip_formatter.py:291-297`: `destination`, `start_date`, `end_date`,
`number_of_adults`, `duration_days`). Renders above the hotel cards, inside the chat
panel's message thread, only once `tripPlan` (or enough of it) is available.

## Requirements

- Functional: hotel cards keep exactly the data `HotelOptionCard` already renders today
  (`hotel-option-card.jsx:8-63`: index badge, name, star rating, average/total price,
  matched rooms, pick button) — restyled into the Stitch list-row layout (thumbnail slot
  + name/rating/price/select-button on the right), **not** re-scoped to new fields.
- Functional: the Stitch mock shows a decimal aggregate rating + review count
  (`"4.8 (124 reviews)"`, `assets/03-parameters-hotel-selection.html`) — **do not
  adopt this**. The backend only sends an integer `star_rating` (1-5). Keep rendering it
  as filled/outline star glyphs, exactly as `hotel-option-card.jsx:9` already computes
  (`'★'.repeat(...) + '☆'.repeat(...)`), just restyled.
- Functional: the Stitch mock's thumbnail is a real stock photo `<img>` per card
  (`data-alt` text describing a fabricated hotel room/exterior) — replace with a fixed
  `w-16 h-16 rounded-lg bg-surface-container-high` slot containing a centered `hotel`
  Material Symbol. Same treatment for every card; no per-hotel fake images.
- Functional: clicking a card applies an **optimistic, real** selected state (ring +
  check badge) via local component state (`useState<number | null>`) set on click,
  before the request resolves — this is legitimate client-side interaction feedback,
  not fabricated data (the Stitch mock's persistent "Selected" state has no backing
  server concept once `hotel_options` clears on send, per
  `use-chat-session.js:63-66`, so it can only be transient/optimistic).
- Functional: new `TripParametersCard` shows **only**: a calendar icon + formatted
  `start_date`–`end_date` range (when both non-null), a `group` icon + `number_of_adults`
  (when non-null). **Omit** "Budget Style" and "Preferences" chips entirely (Stitch mock
  fields with zero backend support — not a disabled placeholder, a straight omission,
  since there's no natural "chrome-only" rendering of a specific preference set that
  isn't itself fabricated).
- Functional: `TripParametersCard` renders only when `tripPlan` has at least one of
  `start_date`/`end_date`/`number_of_adults` set — otherwise render nothing (no empty
  card shell).
- Non-functional: date formatting — `start_date`/`end_date` come from the `itineraries`
  table's `timestamp without time zone` columns (`supabase/seed.sql:388`), which
  serialize as ISO datetime strings (e.g. `"2026-10-12T00:00:00"`) over JSON. Write this
  as a shared `frontend/src/lib/format-trip-dates.ts` (not inline in this component) —
  Phase 5's itinerary panel header needs the identical formatter and imports it from
  here rather than duplicating it.

## Architecture

Reference markup (`assets/03-parameters-hotel-selection.html`), adapted per
Requirements (photo `<img>` → icon slot, decimal rating → star glyphs, Budget
Style/Preferences removed):

```html
<div class="bg-surface-background border border-outline-variant rounded-xl p-md mb-lg">
  <h3 class="text-sm font-medium text-text-primary mb-4 flex items-center gap-2">
    <span class="material-symbols-outlined text-primary text-sm">tune</span> Trip Parameters
  </h3>
  <div class="mb-4">
    <label class="text-xs text-text-secondary block mb-1">Dates</label>
    <div class="flex items-center gap-2 bg-surface-muted p-2 rounded-lg">
      <span class="material-symbols-outlined text-on-surface-variant text-sm">calendar_month</span>
      <span class="text-sm text-text-primary">Oct 12 - Oct 18</span>
    </div>
  </div>
  <div>
    <label class="text-xs text-text-secondary block mb-1">Guests</label>
    <div class="flex items-center gap-2 bg-surface-muted p-2 rounded-lg">
      <span class="material-symbols-outlined text-on-surface-variant text-sm">group</span>
      <span class="text-sm text-text-primary">2 Adults</span>
    </div>
  </div>
</div>

<!-- Hotel card -->
<div class="bg-surface-background border border-outline-variant rounded-xl p-3 mb-3 hover:shadow-md transition-all cursor-pointer group">
  <div class="flex gap-3">
    <div class="w-16 h-16 rounded-lg bg-surface-container-high shrink-0 flex items-center justify-center">
      <span class="material-symbols-outlined text-on-surface-variant">hotel</span>
    </div>
    <div class="flex-1">
      <h4 class="text-sm font-medium text-text-primary group-hover:text-primary">The Grand View Hanoi</h4>
      <div class="text-xs text-primary mt-1">★★★★☆</div>
      <div class="flex items-center justify-between mt-2">
        <span class="text-sm text-text-primary">120,000 VND/night</span>
        <button class="bg-surface-container-high text-on-surface px-3 py-1 rounded-md text-xs hover:bg-primary hover:text-on-primary">Select</button>
      </div>
    </div>
  </div>
</div>
<!-- Selected state: border-primary ring-1 ring-primary + absolute check_circle badge, per optimistic-state requirement above -->
```

## Related Code Files

- Create: `frontend/src/lib/format-trip-dates.ts` (shared by this phase and Phase 5)
- Create: `frontend/src/components/trip-parameters-card.tsx`
- Modify: `frontend/src/components/hotel-option-card.jsx` → `hotel-option-card.tsx`
- Modify: `frontend/src/components/message-list.tsx` (render `TripParametersCard` above
  `HotelOptionCards` when `stage === 'hotel_options'`, per existing conditional at
  `message-list.jsx:61-73`)
- Modify: `frontend/src/strings.ts` (add `tripParamsTitle`, `tripParamsDatesLabel`,
  `tripParamsGuestsLabel`, `tripParamsAdultsSuffix` — Vietnamese, matching the rest of
  the file's language)

## Implementation Steps

1. Create `format-trip-dates.ts`: a single exported function
   `formatTripDateRange(start: string | null, end: string | null): string | null`
   using `new Date(value)` + `Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric' })`,
   returning `null` (not a throw, not a placeholder string) when either date is missing
   or fails to parse — matching the Stitch mock's "Oct 12 - Oct 18" style.
2. Convert `hotel-option-card.tsx`: replace the `<button className="w-full...">` root
   layout with the Stitch row layout (icon-slot thumbnail + right content), keep every
   existing data field and the `onPick(String(hotel.index))` click contract unchanged.
   Add local `selectedIndex` state in the parent `HotelOptionCards` (or lift into
   `MessageList` if simpler) for the optimistic ring/badge; clear it if `hotelOptions`
   changes (new turn).
3. Create `TripParametersCard.tsx`: pure presentational component,
   `{ tripPlan: TripPlan | null }` prop, returns `null` per the Requirements' render
   condition, otherwise the two-row card, importing `formatTripDateRange` from Step 1.
4. Wire `TripParametersCard` into `message-list.tsx` directly above
   `HotelOptionCards`, gated the same way (`stage === 'hotel_options'` on the last AI
   turn).
5. Add the 4 new strings to `strings.ts`.
6. `npx tsc --noEmit`; manually drive a chat turn to `hotel_options` stage and confirm
   both the parameters card (if dates/guests present in that session's trip data) and
   restyled hotel cards with optimistic selection render correctly.

## Success Criteria

- [x] `hotel-option-card.tsx` renders the Stitch list-row layout with only real fields (no fake rating/review count, no fake photo).
- [x] `TripParametersCard` renders dates/guests when present, nothing when absent, never Budget Style/Preferences.
- [x] Clicking a hotel card shows an immediate optimistic selected state that doesn't persist incorrectly across turns.
- [x] `npx tsc --noEmit` clean.

## Risk Assessment

- **Risk:** a malformed/null `start_date`/`end_date` (e.g. only one of the pair set)
  produces `Invalid Date` in the formatter. **Mitigation:** wrap the formatter
  defensively — render nothing for that row if either date fails `new Date(...)`
  validity, never throw and blank the whole card.
- **Risk:** optimistic selected-state local `useState` could desync from server state
  if a turn fails (`SEND_ERROR`) after a card was clicked. **Mitigation:** clear
  `selectedIndex` in the same effect/branch that already resets `hotelOptions`/
  `suggestions` on a new turn (`use-chat-session.js:63-66`), so it never survives past
  the turn that set it.
