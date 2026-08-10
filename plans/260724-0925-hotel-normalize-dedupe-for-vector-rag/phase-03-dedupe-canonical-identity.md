---
phase: 3
title: "Dedupe canonical identity"
status: done
priority: P1
effort: "1d"
dependencies: [2]
---

# Phase 3: Dedupe Canonical Identity

## Overview

Implement dedupe as two separate mechanisms: hard idempotency dedupe for ETL reruns, and physical-hotel canonical grouping for vector/RAG. Do not collapse source-specific hotel rows in PostgreSQL unless a later schema decision explicitly accepts that change.

## Requirements

- Functional: keep current same-source dedupe by `(source_platform, source_hotel_id)` and newest `scraped_at`.
- Functional: keep room/price natural-key dedupe and newest `crawled_at`.
- Functional: add cross-OTA duplicate grouping for same physical hotel.
- Functional: expose dedupe metrics and uncertain-review cases in quality report.
- Non-functional: false positives are worse than false negatives for DB writes; AI presentation can be stricter than storage.

## Architecture

Recommended dedupe pipeline:

```text
normalized hotels
  -> hard same-source dedupe
  -> room/price dedupe
  -> blocking candidates by destination + name token signature
  -> pairwise score
  -> group connected high-confidence matches
  -> assign canonical_hotel_key/group_id
  -> keep all source listings
```

Recommended storage options:

| Option | Use when | Pros | Cons |
|---|---|---|---|
| `canonical_hotel_key` column on `hotels` | fastest implementation | additive, simple payload | limited group metadata |
| `hotel_identity_groups` + `hotel_identity_members` | best long-term | audit trail, review status, confidence | more schema/test work |

Recommended for this project: use new identity tables if there is time before Phase 2 Qdrant; otherwise add nullable `canonical_hotel_key`, `canonical_confidence`, `canonical_review_status`.

## Dedupe Scoring

Blocking rules:

- Same normalized destination/city required unless coordinates are extremely close and city missing.
- Candidate names must share at least one strong token after removing stopwords: `hotel`, `resort`, `apartment`, `khach`, `san`, `the`, `a`, `an`, `and`, city names.
- Coordinate-only candidates are not duplicates.

Pair score:

| Signal | Weight | Rule |
|---|---:|---|
| name similarity | 0.45 | max of SequenceMatcher ratio, token Jaccard, token subset |
| coordinate proximity | 0.25 | 1.0 at <=30m, taper to 0 at >250m |
| address/area similarity | 0.12 | normalized token overlap |
| star/accommodation compatibility | 0.08 | exact or near match |
| amenities/highlights overlap | 0.05 | weak support only |
| review/image/source completeness | 0.05 | tie-break, never decisive |

Decision bands:

| Score | Action |
|---:|---|
| `>= 0.86` | auto group |
| `0.72 - 0.86` | review bucket; do not auto group unless exact name and <=80m |
| `< 0.72` | not duplicate |

Tie-breakers:

- Canonical display name: choose more complete record, then higher review count, then newer `scraped_at`; preserve all member names as aliases.
- Canonical coordinates: choose member with valid coordinates and better address/completeness; do not average by default.
- Canonical embedding text: build from best description plus union of stable amenities/highlights across members, capped and source-tracked.
- Offers: keep each OTA listing as a separate offer under the group.

## Implementation Steps

1. Keep existing `dedupe_hotels()` behavior for same-source keys; add tests to lock it.
2. Create physical-match helpers: `hotel_name_key`, `hotel_stopword_strip`, `coordinate_distance_m`, `score_physical_hotel_pair`, `group_physical_hotels`.
3. Add candidate blocking to avoid O(n^2): group by destination plus first strong name tokens; only compare likely candidates.
4. Add canonical group assignment in normalized output.
5. Extend quality report:
   - same-source duplicates removed
   - room duplicates removed
   - price duplicates removed
   - cross-OTA groups created
   - uncertain duplicate pairs
   - repeated AI-visible groups avoided
6. If schema change is accepted, add migration/docs for canonical identity storage.
7. Add tests:
   - exact same source keeps newest
   - same physical Agoda/Booking groups but both rows remain
   - dense-city nearby different hotels do not group
   - same hotel with small name variation groups
   - uncertain score goes to review

## Success Criteria

- [x] Rerunning the loader remains idempotent (`test_grouping_is_idempotent_across_identical_reruns`).
- [x] Same physical hotel across Agoda/Booking gets a canonical group without losing either source listing.
- [x] Coordinate proximity alone cannot create a duplicate (blocking requires a shared non-destination name token).
- [x] Quality report states duplicate/group counts honestly (`quality_check_hotels()` "Cross-OTA physical-hotel grouping" section).
- [x] AI/search layer can request one result per canonical group (`hotel_retrieval.render_hotel_search_results()`).

## Risk Assessment

- Risk: false-positive grouping hides valid hotel choices.
  Mitigation: conservative high threshold, review band, no coordinate-only grouping.
- Risk: schema change interrupts M2.
  Mitigation: compute group keys in pipeline first; persist only after tests prove value. **Status: groups are computed in-memory only** (`hotel_pipeline.assign_physical_hotel_groups`); `hotel_identity_groups`/`hotel_identity_members` exist in `scripts/database_schema.sql` but nothing writes to them yet.
- **New (found in code review 2026-07-24):** `hotel_identity_groups.confidence` is `DECIMAL NOT NULL`, but auto-approved groups (score `>= 0.86` via the primary rule) currently compute `confidence=None` in-memory — only `pending_review` groups carry a score. Whoever wires the persist path must compute the group's max pair score for auto-approved groups too, or relax the column to nullable.
