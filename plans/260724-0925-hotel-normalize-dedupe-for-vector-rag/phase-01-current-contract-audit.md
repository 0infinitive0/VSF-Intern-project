---
phase: 1
title: "Current contract audit"
status: done
priority: P1
effort: "0.5d"
dependencies: []
---

# Phase 1: Current Contract Audit

## Overview

Freeze the current hotel data contract before changing normalize or dedupe. The repo already has a working M1 loader in `hotel_pipeline.py`; this phase turns its implicit behavior into explicit field contracts and risk boundaries for vector/RAG.

## Requirements

- Functional: inventory every field produced by `normalize_hotel()` and `normalize_room()`.
- Functional: map each field to PostgreSQL columns, Qdrant payload needs, vector text needs, and AI grounding needs.
- Non-functional: preserve current M1 acceptance: 1 row remains 1 OTA listing in `hotels`; do not silently merge Agoda/Booking rows.
- Non-functional: document all semantic differences between sources, especially fields that look comparable but are not.

## Architecture

Current source of truth:

- `src/airflow/dags/data_pipeline/hotel_pipeline.py` has stages `extract -> validate -> normalize -> dedupe -> load -> quality_check`.
- `scripts/database_schema.sql` defines `hotels`, `rooms`, `room_prices`; `hotels` uniqueness is `(source_platform, source_hotel_id)`.
- `docs/data_dictionary.md` defines `hotels_vector` as vector text from name + description + amenities with payload filters.
- `docs/data_pipeline_flow.md` is aspirational where it says Agoda duplicate should update Booking instead of creating a hotel row; current implementation intentionally keeps both OTA listings.

Decision boundary:

- DB identity remains OTA-listing identity.
- RAG identity may add a canonical physical-hotel group so AI avoids showing duplicated hotel suggestions.
- Pricing, rooms, policy, source URL, scraped timestamp remain source-specific and must never be merged into one lossy record.

## Related Code Files

- Modify later: `src/airflow/dags/data_pipeline/hotel_pipeline.py`
- Modify later: `src/airflow/tests/test_hotel_pipeline.py`
- Modify later if schema accepted: `scripts/database_schema.sql`, `docs/data_dictionary.md`
- Read-only references: `docs/data_pipeline_flow.md`, `plans/260723-1015-v-ota-poc-master-roadmap/phase-02-semantic-search-foundation-with-qdrant.md`

## Implementation Steps

1. Generate a field inventory from `normalize_hotel()` and `normalize_room()` output keys.
2. For each field, mark one of: `display_only`, `canonical_db`, `filter_payload`, `vector_text`, `dedupe_signal`, `grounding_fact`, `audit_only`.
3. Compare field list against `_HOTEL_COLUMNS`, `_ROOM_COLUMNS`, `_PRICE_COLUMNS`.
4. Compare vector-relevant fields against `docs/data_dictionary.md` section 2.1.
5. Write a short report table under this plan's `reports/` folder before code changes start.

## Success Criteria

- [ ] Field inventory covers hotel, room, price, source metadata, review, image, location, amenity, and temporal fields.
- [ ] Every field has a declared RAG/vector treatment.
- [ ] Every source-semantic mismatch is recorded before implementation.
- [ ] No phase after this relies on a hidden merge of OTA listings.

## Risk Assessment

- Risk: over-normalizing source-specific values makes AI compare incompatible facts.
  Mitigation: keep raw display text beside canonical values; only canonicalize fields with stable semantics.
- Risk: plan chases a perfect master-data model.
  Mitigation: add canonical grouping for retrieval first; physical merge can remain future work.
