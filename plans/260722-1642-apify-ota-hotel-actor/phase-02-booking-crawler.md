---
phase: 2
title: "Booking crawler"
status: pending
priority: P1
dependencies: [1]
effort: ""
---

# Phase 2: Booking crawler

## Overview

Crawl public Booking.com hotel pages and emit canonical candidates. Booking
serves its room table in server-rendered HTML, so this is the simpler of the two
sources and goes first to prove the contract end to end.

## Requirements

Functional:
- Given a hotel URL with `checkin`/`checkout` query parameters, produce one
  canonical candidate with rooms and prices.
- Given a city, enqueue hotel URLs from public search result pages up to
  `maxHotels`.
- A hotel page that shows no bookable rooms still produces a candidate with
  `crawl_profile: "metadata"`.

Non-functional:
- One request at a time per source, randomized delay between requests.
- Abort the whole run after N consecutive blocked responses; report the reason.

## Architecture

Router labels: `BOOKING_SEARCH` → enqueue detail URLs and the next page;
`BOOKING_DETAIL` → extract and `pushData`.

Field mapping, taken from what the current adapter consumes so the canonical
output stays comparable:

| Canonical | Source on the page |
|---|---|
| `source_id` | hotel id in the page's embedded JSON / `data-hotel-id` |
| `canonical_url` | URL with query string stripped |
| `star_rating` | star class count, `0` → `null` |
| `city_raw` → `destination_key` | address block city, through `citySlug` |
| `latitude` / `longitude` | map widget coordinates |
| `amenities` | facility groups, flattened, deduped |
| `check_in_time` | free-text policy line, through `parseTimeOfDay` |
| `area_name` | not published on Booking → `null` |
| `rooms[].name` | room type cell |
| `rooms[].bed_type` | bed configuration cell |
| `rooms[].prices[]` | one per bookable option row |

Booking-specific rules carried over from the existing adapter, each learned from
real data:

- **Bed counts are alternatives, not a set.** "1 giường đôi" and "1 giường đôi
  lớn" on one room mean the guest picks one. Take the maximum, never the sum, or
  the pipeline invents beds. Drop stray punctuation-only entries such as `")"`.
- **Room size is not a facility.** Entries like `35 m²` are filtered by
  `looksLikeRoomSize`.
- **Room ids repeat by name.** A name-based fallback id collides inside one
  hotel; use positional `h{hotelId}-r{index}` and set `synthetic_room_id`.
- **Every option needs its own package signature.** Include the option/block id
  along with cancellation policy, Genius flag and occupancy. Two options that
  produce the same signature collapse into one row at load time and the cheaper
  rate is lost — this has already happened once with the vendor export.
- **Room images are hotel-level.** They are grouped by associated room ids, not
  nested inside the room; map them back by id, and leave images empty for rooms
  with synthetic ids.

## Related Code Files

- Create: `src/apify/apify-ota-hotels/src/sources/booking.ts`
- Create: `src/apify/apify-ota-hotels/test/fixtures/booking-*.html` and their
  expected canonical JSON
- Modify: `src/apify/apify-ota-hotels/src/routes.ts`
- Reference only: `hotel_adapters.py` `booking_to_canonical` and helpers

## Implementation Steps

1. Save 3 fixture pages covering: a hotel with many options per room, a hotel
   with no availability for the dates, and a hotel with a synthetic room id.
2. Write pure extractor functions taking a Playwright `Page`, or better a parsed
   DOM string, so fixtures can drive them without a browser.
3. Implement `BOOKING_DETAIL`: extract, build the candidate, `pushData`.
4. Implement `BOOKING_SEARCH`: enqueue detail links and the next results page,
   respecting `maxHotels`.
5. Add the block detector: recognise the challenge/interstitial response and
   stop the crawler with a clear message instead of retrying.
6. Wire `coverage.ts` at the end of the run; fail the actor when a floor is
   breached.
7. Run against 5 real hotels in one city and compare the output field by field
   with the equivalent vendor export already in `data/raw/`.

## Success Criteria

- [ ] Fixture tests produce the expected canonical JSON exactly.
- [ ] No two prices of one room share a `package_details` value in the 5-hotel
      live run.
- [ ] Coverage on the live run: `name`, `source_id`, `source_url`,
      `destination_key` 100%; coordinates and images above 95%.
- [ ] A no-availability hotel yields `crawl_profile: "metadata"` with amenities
      and images intact, not a dropped record.
- [ ] The run stops with a stated reason when a challenge page appears.
- [ ] No request touches `/book`, `/checkout`, or any review-text endpoint.

## Risk Assessment

**Booking blocks headless Chrome.** Likeliest failure of this phase.
Mitigation: Apify residential proxies, one concurrent request, human-like
delays, and accepting a low ceiling. If it still blocks, that is a finding to
report, not something to defeat with harder evasion — the legal boundary in
`plan.md` forbids that route.

**Prices are per stay window.** The dates in the input define what gets stored;
a run without dates yields metadata only. Make that explicit in the input schema
description so nobody expects prices from a date-less run.

**Selector drift empties fields silently.** Mitigated by the coverage gate, but
fixtures also age. Re-save fixtures whenever the gate trips.
