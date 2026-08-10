---
phase: 2
title: "Field normalize contract"
status: done
priority: P1
effort: "1d"
dependencies: [1]
---

# Phase 2: Field Normalize Contract

## Overview

Define exactly how each hotel, room, and price field is normalized for structured storage, Qdrant payloads, embedding text, RAG context, and AI display. This phase should produce deterministic helper functions rather than ad hoc mapping inside `normalize_hotel()`.

## Requirements

- Functional: create normalized output fields that separately serve DB persistence, filtering, embedding, and grounding.
- Functional: preserve raw source values whenever canonicalization loses meaning.
- Functional: produce an `embedding_text` or builder input that is stable across reruns.
- Non-functional: avoid API/LLM calls during normalize; all behavior deterministic and unit-testable.
- Non-functional: all normalization must tolerate missing fields without crashing the Airflow batch.

## Architecture

Recommended output shape:

```python
{
    "db": {...existing hotel/room/price fields...},
    "canonical": {
        "name_key": "...",
        "destination_key": "...",
        "country_code": "VN",
        "lat": 10.77,
        "lon": 106.70,
        "price_tier": "mid_range",
        "amenity_keys": ["wifi", "pool"]
    },
    "retrieval": {
        "embedding_text": "...",
        "payload": {...small stable filters...},
        "grounding_facts": {...exact cited fields...}
    }
}
```

Implementation can keep one dict for compatibility, but helpers should make these roles explicit.

## Field Treatment Matrix

| Field | Normalize for DB | Vector text | Qdrant payload/filter | RAG/AI grounding | Dedupe use |
|---|---|---|---|---|---|
| `source_platform` | lowercase enum `agoda|booking` | exclude | include | cite source | hard key |
| `source_hotel_id` | int/string natural key | exclude | include | cite source listing | hard key |
| `source_url` | canonical URL if possible; preserve raw | exclude | include as payload ref only if small | cite booking handoff URL | same-source tie-break |
| `name` | NFC, trim, collapse whitespace; preserve casing | include first, highest weight | include | display exact name | primary fuzzy signal via `name_key` |
| `name_key` new | NFKD ascii fold, remove hotel stopwords/suffix punctuation | exclude | optional | no display | primary blocking key |
| `description` | trim, strip boilerplate, cap oversized text | include summarized/raw-cleaned | exclude or store short hash | cite only if source-supported | completeness score |
| `accommodation_type` | source map to enum; preserve unknown raw separately if needed | include | include | optional display | weak signal |
| `city` / `destination_name` | normalize alias to canonical destination | include | include `destination_id`/name | display destination | blocking scope |
| `area_name` | trim/canonical area text | include | include if stable | display location detail | secondary signal |
| `country` | ISO code `VN`; preserve raw only if needed | exclude | include | no display unless asked | blocking sanity |
| `address` | trim/NFC; do not over-parse | include short | optional | cite exact address | secondary signal |
| `coordinates` | parse to `lat`, `lon`; reject invalid; keep raw string if schema unchanged | exclude from text | include lat/lon | used for distance explanation | secondary gate, never standalone |
| `star_rating` | decimal 0-5 | include as phrase only if present | include numeric | cite exact star | weak tie-break |
| `review_score` | decimal; validate range if known | include only if meaningful | include numeric | cite with source | completeness score |
| `review_count` | int >=0 | exclude | include numeric | cite with score | confidence/completeness |
| `review_text` | trim; preserve language | include only short labels like "Excellent" | exclude | display/cite source sentiment | no |
| `amenities` | dedupe list, trim, source-order stable | include normalized labels | include top-level `amenity_keys` | display source labels | weak similarity |
| `amenity_groups` | JSONB raw-ish, normalized keys optional | do not dump whole JSON | exclude; too large | context only when needed | no |
| `highlights` | dedupe clean text | include | optional boolean flags later | display if useful | weak signal |
| `awards` / `warnings` | preserve list; dedupe | exclude unless important | exclude | cite warnings exactly | no |
| `category_scores` / `score_distribution` | preserve JSONB | exclude | exclude | cite only on explicit rating question | no |
| `check_in_time` / `check_out_time` | parse if easy; preserve raw | exclude | optional | cite exact policy | no |
| `image_url` / `images` | validate http(s), dedupe, cap count | exclude | include thumbnail URL only if needed | display image/gallery | completeness |
| `nearby_attractions` / `nearby_essentials` | preserve JSONB; extract clean names later | include selected nearby names only | exclude raw JSON | cite as source-provided nearby | weak location signal |
| `lowest_price` / `currency` | decimal + ISO currency | include price tier, not exact price | include `min_price`, `currency`, `price_tier` | cite exact current price with date | no physical dedupe |
| `price_check_in_date` / `price_check_out_date` | ISO date | exclude | include when filtering availability | cite price validity | price key |
| `rooms_available` / `offer_count` | bool/int; preserve source semantics note | exclude | include for availability filters | cite cautiously | no |
| `scraped_at` | timezone-aware datetime | exclude | include/index freshness | cite freshness | newest tie-break |
| room `name` | trim/NFC | include only in offer detail, not hotel embedding by default | exclude | cite room selected | room key |
| room `bed_description` | preserve raw | exclude from hotel vector; include room-vector later | exclude | cite exact bed text | no |
| room `room_size_sqm` | parse numeric sqm | exclude | optional range filter | cite exact size | no |
| room `max_guests` | parse with source-specific semantics flag | exclude | optional filter only with caveat | cite with source semantics | no |
| price fields | numeric/date/flags | exclude exact price; include tier only | include current min price/tier | cite exact source price/date | price key |

## Implementation Steps

1. Extract pure helper functions: `normalize_name_key`, `parse_coordinates`, `normalize_text_list`, `normalize_url_list`, `build_hotel_embedding_text`, `build_hotel_payload`, `build_grounding_facts`.
2. Update `normalize_hotel()` to compute canonical helper fields without changing existing DB columns prematurely.
3. Build `embedding_text` from stable user-facing fields:

```text
Hotel: {name}
Destination: {destination_name}, {area_name}
Type: {accommodation_type}; Stars: {star_rating}
Description: {description_clean}
Amenities: {top amenities}
Highlights: {top highlights}
Nearby: {selected nearby names}
```

4. Exclude volatile fields from vector text: exact prices, source URL, scraped timestamp, room IDs, large raw JSON, warnings unless safety-relevant.
5. Add tests for Unicode NFC/NFKD behavior, Vietnamese aliases, coordinate parsing, amenity dedupe, price tier, and embedding text snapshots.
6. Add quality metrics: missing coordinates, empty embedding text, payload size, field coverage by source.

## Success Criteria

- [ ] Every field in the matrix is implemented or explicitly deferred.
- [ ] `embedding_text` is deterministic, compact, and multilingual-friendly.
- [ ] Payload contains stable filters: ids, destination, star, price tier/min price, amenity keys, lat/lon, source metadata.
- [ ] Grounding facts retain exact source URL, price date, room, and crawled timestamp.
- [ ] Unit tests cover all parsing helpers and source semantic differences.

## Risk Assessment

- Risk: vector text includes too much noisy structured data.
  Mitigation: snapshot `embedding_text` and cap/curate list fields.
- Risk: canonical values replace useful source display text.
  Mitigation: keep raw display fields and canonical/filter keys separately.
