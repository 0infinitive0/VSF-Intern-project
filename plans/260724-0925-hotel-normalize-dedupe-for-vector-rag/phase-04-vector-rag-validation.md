---
phase: 4
title: "Vector/RAG validation"
status: done
priority: P1
effort: "0.5d"
dependencies: [2, 3]
---

# Phase 4: Vector/RAG Validation

## Overview

Validate that the refined normalize/dedupe output actually improves vector search and AI behavior. This phase defines the mechanical gates before Phase 2 Qdrant indexing consumes the hotel corpus.

## Requirements

- Functional: produce vector-ready rows with `embedding_text`, payload, and grounding facts.
- Functional: validate duplicate-aware retrieval shape: one canonical hotel result, multiple OTA offers.
- Functional: support VI/EN and mixed-language queries from the roadmap.
- Non-functional: test without requiring live LLM generation; use deterministic fixtures and retrieval probes.

## Architecture

RAG result shape should be explicit:

```python
{
    "canonical_hotel_key": "...",
    "display_name": "...",
    "matched_listing_ids": ["..."],
    "best_source_listing_id": "...",
    "offers": [
        {
            "source_platform": "agoda",
            "hotel_id": "...",
            "min_price": 500000,
            "currency": "VND",
            "check_in_date": "2026-08-01",
            "source_url": "..."
        }
    ],
    "grounding_facts": {...},
    "score": 0.82
}
```

Validation levels:

| Level | Gate |
|---|---|
| Normalize gate | all vector rows have non-empty `embedding_text` and payload ids |
| Payload gate | payload size stays small; no large JSON blobs |
| Dedupe gate | duplicate physical hotels collapse in search output |
| Grounding gate | every displayed price/room/source fact maps to a DB row |
| Bilingual gate | VI, EN, and mixed queries hit expected hotels |

## Implementation Steps

1. Create a small golden corpus from current `data/agoda.json` + `data/booking.json` with known duplicate and non-duplicate pairs.
2. Add unit tests for `build_hotel_embedding_text()` snapshots.
3. Add tests for payload builder: required ids, filters, lat/lon, star, price tier; reject oversized payloads.
4. Add retrieval-shape tests without Qdrant: simulate grouped candidates and verify result renderer collapses canonical groups while preserving offers.
5. Build a probe set for later Qdrant work:
   - Vietnamese amenity query: "khách sạn có hồ bơi gần trung tâm"
   - English query against Vietnamese data: "family hotel with airport shuttle"
   - Mixed query: "khách sạn near Ben Thanh có breakfast"
   - duplicate query: exact hotel name appearing in both OTA sources
6. Update docs only where contracts changed: `docs/data_dictionary.md` and `docs/data_pipeline_flow.md`.

## Success Criteria

- [ ] Golden duplicate pairs produce expected canonical groups.
- [ ] Golden non-duplicate nearby hotels remain separate.
- [ ] `embedding_text` snapshots are stable and not polluted by volatile price/source fields.
- [ ] RAG output can cite exact source URL, price date, room, and `scraped_at`.
- [ ] Probe set is ready for Qdrant/embedding model evaluation in roadmap Phase 2.

## Risk Assessment

- Risk: tests validate only toy examples.
  Mitigation: sample at least dense-city, same-chain, same-name-different-location, and missing-coordinate cases.
- Risk: RAG grouping hides useful OTA price comparison.
  Mitigation: collapse hotel identity only; preserve all source offers under the group.
