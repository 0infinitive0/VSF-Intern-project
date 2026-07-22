---
phase: 3
title: "Agoda crawler"
status: pending
priority: P1
dependencies: [1]
effort: ""
---

# Phase 3: Agoda crawler

## Overview

Crawl public Agoda property pages into the same canonical shape. Agoda renders
room and price content client-side, so this phase needs real browser waiting
rather than HTML parsing, and it is the harder of the two sources.

## Requirements

Functional:
- Given a property URL with stay dates, produce one canonical candidate.
- A sold-out room still becomes a room record, with an empty `prices` array.
- Amenity groups are read as groups, not as the flat amenity list.

Non-functional:
- Wait on the room list selector, never on a fixed sleep.
- Same blocking-abort behaviour as Phase 2.

## Architecture

Router labels: `AGODA_SEARCH` and `AGODA_DETAIL`.

| Canonical | Source on the page |
|---|---|
| `source_id` | property id from the URL or embedded state |
| `star_rating` | star widget, `0` → `null` |
| `city_raw` → `destination_key` | breadcrumb/address city, through `citySlug` |
| `coordinates` | `"lat,lng"` string in the map block, split then re-formatted |
| `amenities` | amenity groups, minus non-facility groups |
| `area_name` | published directly by Agoda |
| `check_in_time` / `check_out_time` | published as structured values |
| `rooms[].max_adults` | occupancy label, leading integer |
| `rooms[].prices[]` | one nightly price per room, omitted when sold out |

Agoda-specific rules, each learned from real data:

- **Skip the "Ngôn ngữ được sử dụng" amenity group.** It lists the languages
  reception speaks. Reading groups rather than the flat `amenities` array is
  what makes skipping possible at all — the flat array arrives pre-mixed with no
  labels, so "Tiếng Anh" ends up searchable as if it were a pool. Match the
  group name accent-folded, not by exact string.
- **Room-level amenity groups are all genuine facilities.** Verified across the
  existing export; no filter needed there. Do not blanket-apply the hotel-level
  filter to rooms.
- **Sold-out rooms are real inventory.** Keep the room, drop only the price.
- **One price per room.** Unlike Booking there is no option matrix, so
  `package_details` only needs the discount flag; still never emit an empty
  signature.
- **`max_children` is not published.** Emit `null` rather than guessing 0.

## Related Code Files

- Create: `src/apify/apify-ota-hotels/src/sources/agoda.ts`
- Create: `src/apify/apify-ota-hotels/test/fixtures/agoda-*.json`
- Modify: `src/apify/apify-ota-hotels/src/routes.ts`
- Reference only: `hotel_adapters.py` `agoda_to_canonical`, `_agoda_rooms`,
  `_agoda_amenities`

## Implementation Steps

1. Save fixtures for: a property with sold-out rooms, one with an unrated star
   value (`0`), and one with a full amenity-group set including the language
   group.
2. Implement the detail handler with an explicit wait on the room list, and a
   bounded timeout that marks the record `metadata` rather than failing the run.
3. Implement amenity-group reading with the non-facility group filter shared
   with `normalize.ts` so Python and TS use the same exclusion list.
4. Implement `AGODA_SEARCH` enqueueing, capped by `maxHotels`.
5. Reuse the Phase 2 block detector.
6. Live-run 5 properties in one city and diff against the vendor Agoda export
   in `data/raw/`.

## Success Criteria

- [ ] No amenity in the live run is a language name.
- [ ] Sold-out rooms appear with `prices: []` and are not dropped.
- [ ] `star_rating` is `null`, never `0`.
- [ ] `coordinates` parse to 6-decimal `"lat,lng"` inside Vietnam bounds.
- [ ] Coverage floors from `plan.md` pass.
- [ ] Client-render timeout downgrades one record to `metadata` instead of
      failing the whole run (tested by forcing a short timeout).

## Risk Assessment

**Client-side rendering is fragile and slow.** Room data arriving after an XHR
means a timeout yields a metadata-only record that looks successful.
Mitigation: count metadata-profile records in the coverage report and treat a
sudden rise as a failure signal, not as normal.

**Temptation to call Agoda's internal GraphQL endpoint.** It would be far more
reliable and it is explicitly out of bounds per `plan.md` and the existing OTA
DAG rules. Public rendered pages only.

**Agoda's anti-bot is stricter than Booking's.** If the coverage gate cannot be
met from the Apify IP pool, report that as the outcome of this phase rather than
escalating evasion.
