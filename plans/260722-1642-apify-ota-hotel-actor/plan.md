---
title: "Apify actor: unified Booking + Agoda hotel crawler"
description: "One TypeScript Crawlee actor that crawls Booking.com and Agoda public hotel pages and emits a single canonical record shape, replacing the two third-party scraper exports currently feeding data/raw."
status: pending
priority: P2
branch: "main"
tags: [apify, crawlee, typescript, hotels, ota]
blockedBy: []
blocks: []
created: "2026-07-22T09:44:12.285Z"
createdBy: "ck:plan"
source: skill
---

# Apify actor: unified Booking + Agoda hotel crawler

## Overview

`booking_agoda_hotels_pipeline` currently ingests exports from two unrelated
marketplace actors (`booking-scraper`, `agoda-hotel-room`). Their shapes share
no field names, so `hotel_adapters.py` exists purely to reconcile them, and a
new OTA means a new adapter.

This plan replaces both exports with one owned actor that crawls the public
hotel pages itself and writes the canonical candidate shape directly. The
pipeline then reads one dataset format instead of two vendor formats.

**Runtime:** TypeScript + Crawlee `PlaywrightCrawler` on the Apify platform.
**Operating model:** run manually from the Apify console, download the dataset
into `data/raw/`, trigger the DAG. No Airflow-to-Apify API call in this plan.

### What this buys, and what it costs

Gains: one shape instead of two, control over which fields get extracted, no
dependency on a third party's schema changing under the pipeline.

Costs, stated up front so they are not discovered mid-implementation:

- **Two implementations of the same normalization rules.** `hotel_utils.py`
  holds city aliasing, currency tokens, star-rating nulling, coordinate bounds
  and package signatures. The actor needs all of them in TypeScript. Phase 4
  exists specifically to stop the two copies drifting.
- **Anti-bot maintenance becomes ours.** The marketplace actors absorb that
  today. Both sites fingerprint headless browsers; Agoda renders room data
  client-side.
- **DOM breakage is now our on-call.** Selector drift silently empties fields
  rather than raising, which is why Phase 2 and 3 gate on field-coverage
  thresholds rather than on "the run finished".

### Legal boundary (inherited, non-negotiable)

`docs/data_pipeline_flow.md` and the existing OTA DAGs already fix these rules
and the actor inherits them without exception:

- public pages only; never `/book`, `/checkout`, or any authenticated flow;
- no login, no private GraphQL endpoints, no CAPTCHA bypass;
- stop on repeated blocking responses rather than retrying harder;
- aggregate ratings only, never review text;
- delays between requests, one stream per source.

PoC scale only (hundreds of hotels). Production needs an affiliate API, not a
bigger crawler.

## Phases

| Phase | Name | Status |
|-------|------|--------|
| 1 | [Actor skeleton and canonical contract](./phase-01-actor-skeleton-and-canonical-contract.md) | Pending |
| 2 | [Booking crawler](./phase-02-booking-crawler.md) | Pending |
| 3 | [Agoda crawler](./phase-03-agoda-crawler.md) | Pending |
| 4 | [Parity harness against Python adapters](./phase-04-parity-harness-against-python-adapters.md) | Pending |
| 5 | [Deploy and Airflow ingest](./phase-05-deploy-and-airflow-ingest.md) | Pending |

Phases 2 and 3 are independent of each other and both depend on Phase 1.
Phase 4 needs both crawlers. Phase 5 is last.

## Acceptance criteria

- [ ] One actor, one input schema, `source: "booking" | "agoda" | "both"`.
- [ ] Dataset items carry exactly the canonical candidate keys that
      `hotel_adapters.py` produces today, with the same value semantics.
- [ ] A canonical export loads through the existing DAG with no adapter code
      involved and produces sane hotel/room/price counts.
- [ ] Coverage gates pass: `name`, `source_id`, `source_url`,
      `destination_key` at 100%; coordinates and images above 95%;
      `star_rating` above 80%.
- [ ] The actor stops with a stated reason when blocked, and never retries into
      a block.
- [ ] No review text and no authenticated endpoint appears in the code or the
      output.

## Dependencies

No cross-plan dependencies; this is the first plan in `plans/`.

Touches `src/airflow/dags/data_pipeline/hotel_pipeline.py` in Phase 5 only. The
adapters stay in place until a canonical export has loaded successfully at
least once.

## Open questions

1. Which cities, and how many hotels per run? Decides whether crawling search
   result pages is in scope at all, or whether the actor takes a URL list.
2. One stay window per run (as the current exports do), or several date ranges
   in one run?
3. Is a paid Apify residential proxy plan available? Without it the realistic
   ceiling is low and the Phase 2/3 coverage gates may be unreachable.
