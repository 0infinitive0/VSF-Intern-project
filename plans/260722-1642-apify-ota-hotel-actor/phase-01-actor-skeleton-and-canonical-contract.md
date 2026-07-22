---
phase: 1
title: "Actor skeleton and canonical contract"
status: pending
priority: P1
dependencies: []
effort: ""
---

# Phase 1: Actor skeleton and canonical contract

## Overview

Stand up the actor project and port the normalization rules that both crawlers
depend on. Nothing is crawled in this phase; it ends with a typed canonical
record and a normalization module proven against fixtures.

## Requirements

Functional:
- Actor accepts an input schema with `source`, target cities or start URLs,
  stay dates, and a hotel cap.
- A `src/canonical.ts` module exports the `HotelCandidate` type and a builder
  that guarantees every canonical key is present, `null` rather than missing.
- A `src/normalize.ts` module ports every rule currently in `hotel_utils.py`.

Non-functional:
- Zero network access in this phase's tests; fixtures only.
- Normalization functions are pure so Phase 4 can diff them against Python.

## Architecture

```
apify-ota-hotels/
├── .actor/
│   ├── actor.json            # name, version, dockerfile ref
│   └── input_schema.json     # console form
├── src/
│   ├── main.ts               # Actor.init, input parsing, crawler wiring
│   ├── routes.ts             # createPlaywrightRouter, labelled handlers
│   ├── canonical.ts          # HotelCandidate type + builder
│   ├── normalize.ts          # port of hotel_utils.py
│   ├── sources/
│   │   ├── booking.ts        # Phase 2
│   │   └── agoda.ts          # Phase 3
│   └── coverage.ts           # field-coverage gate, used by Phases 2/3
├── test/
│   └── fixtures/             # saved HTML + expected canonical JSON
├── package.json
├── tsconfig.json
└── Dockerfile                # apify/actor-node-playwright-chrome base
```

Rules to port into `normalize.ts`, each with its reason (do not "improve" them
during the port — they encode real data defects):

| Function | Rule | Why |
|---|---|---|
| `citySlug` | `CITY_ALIASES` map, accent-folded | "Hue" and "Huế" must reach one destination |
| `normalizeCurrency` | `US`, `US$` → `USD`; unknown → `null` | Unknown codes reject the offer instead of guessing |
| `normalizeStarRating` | `0` and `null` → `null`, clamp 1-5 | Agoda encodes "unrated" as 0; the DB CHECK allows 1-5 |
| `parseCoordinates` | drop values outside Vietnam bounds | Bad coordinates poison the 80 m dedupe radius |
| `formatCoordinates` | `"lat,lng"` at 6 decimals | Stored as text in `hotels.coordinates` |
| `parseTimeOfDay` | free text → `HH:MM` | Booking publishes prose, Agoda publishes structure |
| `packageSignature` | sorted, `\|`-joined, never empty → `"standard"` | Part of the `room_prices` unique key; NULL defeats upsert |
| `cleanList` | trim, drop blanks, dedupe keeping order | Amenity arrays arrive dirty from both sites |
| `looksLikeRoomSize` | drop `35 m²`-style facility entries | Area is not a facility |

Canonical record — the contract every crawler must satisfy:

```typescript
interface HotelCandidate {
  source: 'booking' | 'agoda';
  source_id: string;
  source_url: string;
  canonical_url: string;        // query string stripped
  name: string;
  description: string | null;
  accommodation_type: string | null;
  star_rating: number | null;
  city_raw: string | null;
  destination_key: string;      // required; unmapped city means reject
  address: string | null;
  latitude: number | null;
  longitude: number | null;
  coordinates: string | null;
  amenities: string[];
  images: string[];
  rating: number | null;
  review_count: number | null;
  check_in_time: string | null;
  check_out_time: string | null;
  area_name: string | null;
  crawl_profile: 'price' | 'metadata';
  scraped_at: string;           // ISO 8601
  rooms: Room[];
}

interface Room {
  source_room_id: string;
  synthetic_room_id: boolean;
  name: string;
  max_adults: number | null;
  max_children: number | null;
  number_of_beds: number | null;
  bed_type: string | null;
  facilities: string[];
  images: string[];
  prices: Price[];
}

interface Price {
  price: number;
  currency: string;
  check_in_date: string;        // YYYY-MM-DD
  check_out_date: string;
  source_url: string;
  package_details: string;      // never empty
  available_rooms: number | null;
  crawled_at: string;
}
```

Two contract points that are easy to get wrong and expensive later:

- `package_details` must separate every distinct offer of one room. Cancellation
  policy plus Genius flag is **not** enough — one room sells the same refundable
  Genius rate at several prices for different meal plans. Include the site's own
  offer/block identifier. Colliding signatures silently drop the cheaper rate at
  load time because `room_prices` is unique on it.
- `synthetic_room_id` is `true` whenever the room id had to be invented
  (`h{hotelId}-r{index}`). Those ids are not stable between crawls, and the
  quality report counts them.

## Related Code Files

- Create: `src/apify/apify-ota-hotels/` (whole tree above)
- Read for rules, do not modify: `src/airflow/dags/data_pipeline/hotel_utils.py`
- Read for the target shape: `src/airflow/dags/data_pipeline/hotel_adapters.py`

## Implementation Steps

1. `npx apify-cli create apify-ota-hotels --template ts-crawlee-playwright-chrome`,
   move it under `src/apify/`.
2. Write `input_schema.json`: `source` enum, `startUrls` array, `cities` string
   array, `checkIn`/`checkOut` dates, `maxHotels` integer, `maxConcurrency`
   integer defaulting to 1, `proxyConfiguration` object.
3. Port `hotel_utils.py` into `normalize.ts` function by function, carrying each
   docstring's reasoning into a comment. Copy `CITY_ALIASES` and
   `DESTINATION_META` verbatim — a divergent city map silently splits a
   destination in two.
4. Define the types above in `canonical.ts` plus `buildCandidate()` which fills
   every absent key with `null`/`[]` so downstream code never sees `undefined`.
5. Write `coverage.ts`: takes candidates, returns per-field coverage percentages,
   throws when a configured floor is breached.
6. Unit-test `normalize.ts` against the same inputs the Python tests use, so
   Phase 4 has a baseline.
7. `main.ts`: `Actor.init()`, read and validate input, build
   `ProxyConfiguration`, instantiate `PlaywrightCrawler` with the router,
   `Actor.exit()` with a summary.

## Success Criteria

- [ ] `npm run build` and `npm test` pass with no network access.
- [ ] Every function in `hotel_utils.py` has a TS counterpart, or a comment in
      `normalize.ts` explaining why it is Python-side only.
- [ ] `CITY_ALIASES` in TS and Python produce identical slugs for every key in
      the Python map (asserted in a test, not by eye).
- [ ] `buildCandidate({})` returns an object with every canonical key present.
- [ ] Actor runs locally via `apify run` against an empty input and exits clean.

## Risk Assessment

**Silent divergence between the two normalization copies.** The whole design
rests on them agreeing. Mitigation: step 6 plus the Phase 4 harness; the alias
map is compared programmatically, not reviewed by hand.

**Input schema churn.** Cities-vs-URLs is still an open question in `plan.md`.
Mitigation: support `startUrls` first since it needs no search-page crawling,
and treat `cities` as additive.
