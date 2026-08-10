---
phase: 1
title: "M1 hotel loader and dataset acceptance"
status: completed
priority: P1
dependencies: []
effort: ""
---

# Phase 1: M1 hotel loader and dataset acceptance

## Overview

Build the JSON→PostgreSQL loader that makes 1,103 OTA hotel records queryable, closing BO-02 before M1 (~3 Aug). This is the roadmap's most urgent phase: it is a hard milestone criterion *and* Sprint 2's search corpus.

> **Delivery path changed 2026-07-23.** `plans/260723-1010-agoda-booking-database-schema` (the 12-table `hotel_listings`/`hotel_nearby_places` design this phase was written against) is cancelled. This phase's loader is now delivered by porting a working, tested loader from `github.com/NhatLam71388/data_pipeline_hotel` — see `plans/260723-1057-merge-data-pipeline-hotel-loader`. Target schema is a flat `hotels` table (one row per `(source_platform, source_hotel_id)`), not the 12-table split below — the Requirements/Architecture/Related-Code-Files sections below describing `hotel_listings`/`hotel_nearby_places`/`hotel_utils.py` are superseded by that plan's phases; treat this file as historical intent, not the current implementation spec.

**Completed by `plans/260723-1057-merge-data-pipeline-hotel-loader` on 2026-07-23.** That plan's Phase 4 end-to-end validation loaded and verified 1,103 OTA hotel records across Agoda and Booking, so this roadmap phase is complete.

## Requirements

- Functional: load `data/agoda.json` (503) and `data/booking.json` (600) into `hotels`, `hotel_listings`, `rooms`, `room_prices`, `hotel_nearby_places`.
- Functional: idempotent — re-running must not duplicate rows (BO-02 says "pipeline tái chạy được").
- Functional: every record carries source and collection timestamp (BRD §13.3 BR-01: "mọi bản ghi thu thập đều mang nguồn và thời điểm thu thập").
- Non-functional: reuse the existing pipeline's conventions — this repo already has a 7-stage pattern in `src/airflow/dags/data_pipeline/pipeline_stages.py`; do not invent a second idiom.
- Constraint: no cross-OTA hotel dedup in this phase (see Architecture).

## Architecture

**Dedup is deliberately deferred**, per the schema plan's validated finding: exact normalized-name matches between the two files (14 of 503/600) are all genuine duplicates with coordinates agreeing within ~10m, but naive coordinate-proximity matching within 60m yields 205 false positives in dense city blocks. The schema already accommodates this — `hotel_listings.hotel_id` is repointable once real matching exists, so loading each OTA listing as its own `hotels` row now is forward-compatible, not a dead end.

The repo's existing precedent is `attraction_utils.py`'s `_are_duplicates()` — name similarity first (`SequenceMatcher` ≥ 0.84 or token overlap ≥ 0.7), coordinates only as a secondary gate, never standalone. A hotel equivalent should follow that shape when it is eventually built. **State the duplicate count honestly in the M1 report** rather than implying 1,103 distinct properties.

**Airflow DAG vs standalone script:** prefer a DAG consistent with the existing four, so the loader is re-runnable and observable like the rest of the pipeline. A one-off script is acceptable only if M1 timing demands it — record the shortcut if taken.

## Related Code Files

- Create: `src/airflow/dags/data_pipeline/hotel_loader_pipeline.py`, `hotel_loader_dag.py`
- Create: `src/airflow/dags/data_pipeline/hotel_utils.py` (normalization; dedup helpers stubbed for later)
- Read only (pattern reference): `pipeline_stages.py`, `dag_common.py`, `attraction_utils.py`, `ota_pipeline.py`
- Read only (target schema): `scripts/database_schema.sql` — **post-schema-plan version**
- Input: `data/agoda.json`, `data/booking.json`

## Implementation Steps

1. **Confirm the schema plan has landed.** Verify `hotel_listings` and `hotel_nearby_places` exist and `rooms.listing_id` is in place. Loading against the old 10-table shape wastes the work.
2. **Map every source field to a column.** The schema plan's acceptance criteria require full coverage or an explicit dropped-with-reason note; the loader is where that mapping becomes real. Produce the field-map as a table in the phase report.
3. **Write normalization helpers** in `hotel_utils.py`: VND price parsing, star-rating coercion, amenity list flattening, coordinate validation, image/URL filtering. Mirror `attraction_utils.py` conventions.
4. **Implement the load stages** following the existing pipeline shape: extract → validate/clean → normalize → load → quality check. Reject malformed records rather than crashing the run — `design_proposal.md` §4B already specifies this behaviour.
5. **Make it idempotent** via `ON CONFLICT` upserts keyed on (source, source listing id), matching the existing `INSERT ... ON CONFLICT` usage in the attractions loader.
6. **Add a quality-check stage** publishing counts through XCom, consistent with the existing `quality_check` task: rows per table, per source, rejects, coordinate/description/image coverage.
7. **Produce the M1 dataset evidence.** Row counts per table and per source, the reproducible run command, and the honest distinct-property estimate. This is the artifact the mentor accepts against BO-02.

## Success Criteria

- [x] ≥1,000 hotel records from both sources loaded and queryable in `vsf_database`.
- [x] Loader is idempotent — reruns use `ON CONFLICT` upserts keyed by source natural keys.
- [x] Every field in both JSON files maps to a column or is documented as intentionally dropped.
- [x] Every loaded row carries source and collection timestamp (BR-01).
- [x] Quality-check output records counts, rejects, and coverage.
- [x] M1 evidence written up, stating the duplicate-listing caveat plainly.

## Completion Evidence

- DAG entrypoint: `booking_agoda_hotel_loader_pipeline` in `src/airflow/dags/data_pipeline/hotel_dag.py`.
- Validation command: `airflow dags test booking_agoda_hotel_loader_pipeline 2026-07-23 -f /opt/airflow/dags/data_pipeline/hotel_dag.py`.
- Loaded counts: 1,103 hotels (`agoda=503`, `booking=600`), 6,375 rooms, 6,375 room_prices.
- Quality report: `src/airflow/logs/reports/hotel_quality_report_20260723_045800.md`; rejects: 0; sanity issues: none.

## Risk Assessment

- **Risk:** Schema plan slips, compressing this phase against a hard M1 date.
  **Mitigation:** These are the two most urgent plans in the repo — run the schema plan immediately. If it slips past ~28 Jul, load against the current 10-table schema and migrate after; a met milestone with a follow-up migration beats a missed one.
- **Risk:** Duplicate listings inflate the count and BO-02 looks met when it isn't.
  **Mitigation:** Step 7 requires stating this explicitly. 1,103 listings is comfortably above 1,000 even with ~14 known exact duplicates removed, so the criterion holds honestly either way.
- **Risk:** Real-world JSON is messier than sampled records suggest.
  **Mitigation:** Step 4's reject-don't-crash rule plus step 6's reject counts surface this rather than hiding it.
