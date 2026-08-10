---
title: "Hotel Normalize + Dedupe for Vector/RAG"
description: "Refine hotel normalize and dedupe so PostgreSQL stays source-faithful while vector search and AI responses use clean canonical text, filters, and duplicate-aware retrieval."
status: done
priority: P1
effort: "3d"
issue: null
branch: "main"
tags: [data-pipeline, rag, vector, dedupe, hotels]
blockedBy: [260723-1015-v-ota-poc-master-roadmap]
blocks: [260727-1113-qdrant-vector-store-correctness-and-hybrid-retrieval]
created: 2026-07-24
---

# Hotel Normalize + Dedupe for Vector/RAG

## Overview

This plan reworks steps 3 and 4 of the hotel loader: `normalize` and `dedupe`. The goal is not just cleaner PostgreSQL rows. The output must be optimal for Qdrant vectors, RAG retrieval, AI grounding, filtering, and rerunnable ETL.

The important constraint: keep the current DB contract where one `hotels` row is one OTA listing. Add canonical identity/grouping for retrieval and AI presentation without losing source-specific price, room, policy, and source URL facts.

## Cross-Plan Dependencies

| Relationship | Plan | Status | Reason |
|---|---|---|---|
| Blocked by | `260723-1015-v-ota-poc-master-roadmap` | in-progress | This is a detail plan for roadmap Phase 2 vector/RAG readiness. |

## Goals

| # | Goal | Priority |
|---|---|---|
| 1 | Define exact per-field normalize behavior for DB, vector text, Qdrant payload, RAG grounding, and AI display. | P1 |
| 2 | Add effective dedupe that handles reruns, same-source duplicates, room/price duplicates, and cross-OTA physical-hotel grouping. | P1 |
| 3 | Prevent duplicate hotel suggestions in AI while preserving OTA-specific rooms/prices. | P1 |
| 4 | Add quality metrics and tests so normalize/dedupe regressions are visible. | P1 |

## Phases

| # | Phase | Status |
|---|---|---|
| 1 | [Current contract audit](./phase-01-current-contract-audit.md) | Done |
| 2 | [Field normalize contract](./phase-02-field-normalize-contract.md) | Done |
| 3 | [Dedupe canonical identity](./phase-03-dedupe-canonical-identity.md) | Done |
| 4 | [Vector/RAG validation](./phase-04-vector-rag-validation.md) | Done |

## Design Summary

Normalize must produce three layers:

| Layer | Purpose | Example fields |
|---|---|---|
| Raw/display | Exact source facts shown or cited by AI | `name`, `address`, `review_text`, `source_url`, room `bed_description` |
| Canonical/filter | Stable values for SQL/Qdrant filtering | `destination_id`, normalized city, ISO country, price tier, star rating, coordinate lat/lon |
| Retrieval text | Clean text optimized for embedding | canonical name, destination, accommodation type, short description, amenities, highlights, area |

Dedupe must produce two different outcomes:

| Scope | Action |
|---|---|
| Same `(source_platform, source_hotel_id)` | Keep newest by `scraped_at`; idempotent rerun behavior. |
| Same room/price natural key | Keep newest crawled price; preserve latest room data. |
| Cross-OTA same physical hotel | Do not merge DB rows. Assign a `canonical_hotel_key` or mapping group for vector/RAG. |
| AI result rendering | Collapse duplicate group into one hotel card with multiple source offers. |

## Acceptance Criteria

- [x] Step 3 normalize has an explicit field-by-field contract. (`reports/phase-01-field-inventory.md`, `phase-02-field-normalize-contract.md`)
- [x] Step 4 dedupe has thresholds, blocking strategy, tie-breakers, manual-review bucket, and metrics. (`group_physical_hotels()`, `quality_check_hotels()`)
- [x] Vector text excludes noisy fields and includes enough multilingual context for VI/EN queries. (`build_hotel_embedding_text()`; bilingual probe set recorded in `reports/phase-04-vector-rag-validation.md` for the future embedding-model evaluation)
- [x] Qdrant payload includes only stable filterable metadata, not large/raw JSON blobs. (`build_hotel_payload()`, tested)
- [x] RAG context can cite exact source listing, room, price, and crawl timestamp. (`build_grounding_facts()`)
- [x] Cross-OTA duplicates do not appear as repeated AI recommendations. (`hotel_retrieval.render_hotel_search_results()`)
- [x] Tests cover normalize parsing, duplicate grouping, non-merge behavior, and RAG output shape. (146 tests passing across `test_hotel_pipeline.py`, `test_hotel_retrieval.py`)

## Risks

| Risk | Severity | Mitigation |
|---|---|---|
| False-positive cross-OTA dedupe in dense city blocks | High | Use name-first blocking; coordinates are a secondary gate, never standalone. Send uncertain pairs to review. |
| Losing price/source truth by merging listings | High | Preserve DB rows and group only at retrieval/presentation layer. |
| Vector text too noisy | Medium | Use a deterministic `embedding_text` builder and snapshot tests. |
| Extra schema slows M2 | Medium | Prefer additive columns/table; keep old loader behavior valid until new grouping is proven. |

## Open Questions (Resolved)

1. Canonical grouping storage: **new `hotel_identity_groups` + `hotel_identity_members` tables** (decided 2026-07-24).
2. Uncertain duplicate groups (score `0.72-0.86`): **require manual review** before being used in AI/vector grouping; auto-group only `>= 0.86` (decided 2026-07-24).
