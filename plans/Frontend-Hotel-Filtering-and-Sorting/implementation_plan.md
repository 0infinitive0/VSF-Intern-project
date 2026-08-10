# Implementation Plan: Frontend Hotel Filtering and Sorting

## Overview
Implement client-side filtering and sorting for the hotel recommendations returned by the backend. This will allow users to dynamically refine their hotel options in the UI (e.g., by setting a maximum price, minimum star rating, or changing the sort order to focus on price instead of match score) without needing to send a new message or wait for a backend response. 

## Architecture Decisions
- **Client-Side Filtering**: Since the backend already returns a highly curated top-N list of candidates, filtering will be done locally in React state (`stage-hotels.tsx`). This ensures instant visual feedback and zero network latency.
- **Dedicated Component**: To prevent `stage-hotels.tsx` from becoming cluttered, all filter UI elements (dropdowns, sliders, or pills) will be extracted into a new `hotel-filter-bar.tsx` component.
- **Non-Destructive Filtering**: We will compute a `filteredHotels` array via `useMemo`. The original `state.hotelOptions` array will remain intact so users can clear filters and restore the full AI recommendation list.

## UI & UX Specifications
- **Filter Type**: A "Preference Pills" filter (a horizontal scrollable row of toggleable pill buttons representing amenities/preferences).
- **Placement**: Located above the hotels list, just below the selected hotel header.
- **Component**: A brand new `hotel-filter-bar.tsx` component will be built using standard HTML elements styled to match the app's glassmorphism theme, without relying on existing UI component libraries.

## Task List

### Phase 1: Foundation (State & Logic)
- [ ] Task 1: Add filter state variables (e.g., `maxPrice`, `minStars`, `sortOrder`) to `stage-hotels.tsx`.
- [ ] Task 2: Implement the filtering and sorting logic using `useMemo` to derive a `filteredHotels` array from `state.hotelOptions`.
- [ ] Task 3: Pass `filteredHotels` to `HotelOptionCards` instead of the raw `hotels` array.

### Checkpoint: Foundation
- [ ] Logic correctly filters hardcoded mock data locally without errors.

### Phase 2: UI Implementation
- [ ] Task 4: Create `hotel-filter-bar.tsx` component with basic UI controls (select dropdowns or buttons) for the filter criteria.
- [ ] Task 5: Add translation keys for the filter labels in `src/i18n/` files (vi/en).
- [ ] Task 6: Integrate `HotelFilterBar` into `stage-hotels.tsx` above the `HotelOptionCards` list, passing down the state setter functions.

### Checkpoint: Complete
- [ ] The filter UI is visible and matches the application's glassmorphism design.
- [ ] Changing a filter instantly updates the rendered list.
- [ ] Clearing filters restores the exact order and list returned by the AI.

## Verification Plan
### Manual Verification
- Start a chat and reach the hotel selection stage.
- Open the filter bar and adjust "Max Price". Verify that hotels above the price disappear instantly.
- Change the sort order to "Price: Low to High". Verify the list re-orders correctly, overriding the default AI match score order.
- Clear the filters and verify the original list is restored perfectly.
