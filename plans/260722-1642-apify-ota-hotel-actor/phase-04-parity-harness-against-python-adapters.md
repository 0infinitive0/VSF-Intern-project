---
phase: 4
title: "Parity harness against Python adapters"
status: pending
priority: P1
dependencies: [2, 3]
effort: ""
---

# Phase 4: Parity harness against Python adapters

## Overview

The actor and `hotel_adapters.py` now both produce canonical candidates. This
phase makes their agreement a checkable fact rather than an assumption, and
answers the one question that decides whether the actor is adopted: does the
pipeline behave identically on actor output?

## Requirements

Functional:
- A script that runs `hotel_adapters.py` over the vendor exports in `data/raw/`
  and the actor over the same hotels, then diffs the two canonical outputs.
- A comparison report naming every field that differs, with counts.

Non-functional:
- Runs offline from saved actor output; no live crawl needed to re-check.

## Architecture

Exact equality is the wrong bar. The two paths read different renderings of the
same page at different times, so the harness classifies differences instead:

| Class | Example | Verdict |
|---|---|---|
| Identity | `source_id`, `destination_key`, `canonical_url` | must match exactly |
| Normalized scalars | `star_rating`, `check_in_time`, `coordinates` | must match exactly when both are non-null |
| Volatile | `price`, `available_rooms`, `scraped_at` | ignored |
| Set-like | `amenities`, `images` | compared by overlap ratio, floor configurable |
| Structural | room count, price count per room | reported, reviewed by hand |

Identity mismatches are the ones that matter: a different `destination_key` or
`source_id` for the same hotel means the two paths would create two rows.

The alias-map equality test from Phase 1 belongs here too, promoted to a
regression: dump `CITY_ALIASES` from both sides and assert equal.

## Related Code Files

- Create: `src/apify/apify-ota-hotels/test/parity/compare-canonical.mjs`
- Create: `src/airflow/tests/test_canonical_contract.py` — asserts the actor's
  key set equals the adapter's key set
- Reference: `data/raw/dataset_booking-*.json`, `data/raw/dataset_agoda-*.json`

## Implementation Steps

1. Pick 5 hotels per source that exist in both the vendor export and an actor
   run; store the actor output as a fixture.
2. Write the comparator with the classification table above.
3. Add `test_canonical_contract.py`: load one actor output record, assert its
   key set matches `booking_to_canonical`'s output key set exactly. This catches
   a renamed or dropped key immediately, and it runs in CI without network.
4. Run the whole DAG twice — once on the vendor export, once on the actor
   export — and compare `quality_check` reports side by side.
5. Record the outcome in `plans/reports/` with the field-level differences and a
   recommendation on adoption.

## Success Criteria

- [ ] Identity fields match for 100% of the compared hotels.
- [ ] Normalized scalars match wherever both sides are non-null; every exception
      is explained in the report, not waved through.
- [ ] `amenities` overlap above the agreed floor; discrepancies traced to a
      named cause (for example the language-group filter).
- [ ] `test_canonical_contract.py` passes and is part of the normal test run.
- [ ] Both DAG runs produce the same hotel count and the same destination set.
- [ ] Report written with an explicit adopt / do-not-adopt recommendation.

## Risk Assessment

**The harness rationalizes differences instead of surfacing them.** The
temptation is to widen tolerances until it passes. Keep the classification table
fixed and put every exception in the report; a difference that needs a new
tolerance is a finding.

**Vendor and actor runs are days apart.** Prices and availability will differ
legitimately. That is why they are in the volatile class — but room *counts* are
structural, and a large gap there means an extraction gap, not staleness.

**Parity might reveal the actor is worse.** That is a valid outcome. The report
should say so plainly, and the vendor exports plus adapters remain in place
until parity is met.
