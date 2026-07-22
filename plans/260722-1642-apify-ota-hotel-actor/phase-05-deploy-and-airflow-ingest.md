---
phase: 5
title: "Deploy and Airflow ingest"
status: pending
priority: P2
dependencies: [4]
effort: ""
---

# Phase 5: Deploy and Airflow ingest

## Overview

Publish the actor to the Apify account and teach the pipeline to read canonical
exports. Runs stay manual: trigger in the console, download the dataset into
`data/raw/`, trigger the DAG.

## Requirements

Functional:
- Actor builds and runs on the Apify platform from the console form.
- The DAG accepts a canonical export alongside the existing vendor exports.
- Vendor exports keep working; nothing is deleted in this phase.

Non-functional:
- No Apify token stored in the repo or in Airflow.

## Architecture

The integration point is smaller than it looks, but it is not free. Today
`discover_dataset_files` routes by **file name**: a name containing "booking"
goes to the Booking adapter, "agoda" to the Agoda adapter, and anything else is
skipped with a log line. A canonical export breaks that in two ways — it can
contain both sources in one file, and it needs no adapter at all.

Change: keep the existing name-based routing, add a third recognised format.

```
detect_source(file_name):
  "canonical" in name  → "canonical"    # new
  "booking"   in name  → "booking"
  "agoda"     in name  → "agoda"
  otherwise            → None (skipped, logged)

extract_hotel_candidates(files):
  entry["source"] == "canonical" → records pass through untouched,
                                    each record's own "source" field is trusted
  otherwise                      → to_canonical(record, entry["source"])
```

Why name-based and not content sniffing: the current behaviour is explicit
on purpose — a glob wide enough to catch every dataset also feeds Agoda records
into the Booking adapter, which fails in confusing ways. Adding a third name
prefix keeps that property. The download step names the file
`dataset_canonical-<timestamp>.json`.

Validation must not be relaxed for canonical files. `validate_clean` still
applies: missing required fields still reject the hotel, bad prices still reject
only the offer. An actor bug must not bypass the gate that the vendor path
passes through.

## Related Code Files

- Modify: `src/airflow/dags/data_pipeline/hotel_adapters.py` — `detect_source`
- Modify: `src/airflow/dags/data_pipeline/hotel_pipeline.py` —
  `extract_hotel_candidates` passthrough branch
- Modify: `src/airflow/tests/test_hotel_pipeline.py` — canonical passthrough test
- Modify: `src/airflow/dags/data_pipeline/README.md` — document the third format
- Create: `docs/guide/apify-actor-usage.md` — how to run and download

## Implementation Steps

1. `apify push` from `src/apify/apify-ota-hotels/`; verify the console form
   renders every input field with sane defaults.
2. Run for one city, both sources, with a small `maxHotels`; export the dataset
   as JSON.
3. Save it as `data/raw/dataset_canonical-<timestamp>.json`.
4. Implement the `detect_source` third format and the passthrough branch.
5. Add tests: a canonical file routes to passthrough; a canonical record with a
   missing `destination_key` is still rejected by `validate_clean`; a mixed-source
   canonical file produces both sources' records.
6. Trigger the DAG and confirm hotels, rooms and prices load, and that
   `quality_check` reports both sources.
7. Write the usage doc: input fields, expected run time, cost per run, download
   steps, file naming, and the blocked-run failure mode.

## Success Criteria

- [ ] Actor builds on the platform and runs from the console form.
- [ ] A canonical export loads through the DAG with no adapter invoked.
- [ ] Vendor exports still load unchanged in the same run.
- [ ] `validate_clean` rejects a deliberately broken canonical record.
- [ ] `quality_check` shows both sources with expected coverage.
- [ ] README and usage doc updated; no token committed anywhere.

## Risk Assessment

**A canonical file that lies about its own `source`.** The passthrough trusts
the record's `source` field. A malformed value would flow into `source_ids` and
the dedupe source-priority logic. Mitigation: validate `source` against the
supported set during passthrough and reject records that fail, as a hotel-level
rejection with a clear reason.

**Two ingest paths to maintain.** Acceptable while parity is being proven, not
acceptable forever. Once a canonical export has loaded cleanly several times,
open a follow-up to retire the adapters — do not do it in this phase.

**Manual download drift.** A mistyped file name silently skips the file (logged,
not raised). The usage doc must state the exact required prefix, and step 6
should confirm the record count matches the actor run.
