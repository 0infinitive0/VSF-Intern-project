# Phase 1 — Current Contract Audit: Field Inventory

Source: `normalize_hotel()` / `normalize_room()` in `src/airflow/dags/data_pipeline/hotel_pipeline.py` (as of 2026-07-24, pre-Phase-2).

Legend: `canonical_db` = persisted as-is to Postgres | `display_only` = shown to user, not filtered/embedded | `filter_payload` = candidate Qdrant payload filter | `vector_text` = candidate embedding input | `dedupe_signal` = used by same-source or cross-OTA dedupe | `grounding_fact` = must be citable by AI with exact source/date | `audit_only` = kept for debugging/report, not user-facing.

**Vector text, payload, and dedupe-scoring fields do not exist in code yet** — this table is the target treatment for Phase 2/3 to implement, not current behavior. Only `canonical_db` reflects current code state 1:1.

## Hotel fields

| Field | Treatment | Notes |
|---|---|---|
| `source_platform` | canonical_db, filter_payload, dedupe_signal, grounding_fact | hard key (same-source dedupe) |
| `source_hotel_id` | canonical_db, filter_payload, dedupe_signal, grounding_fact | hard key |
| `source_url` | canonical_db, grounding_fact | booking handoff link |
| `name` | canonical_db, display_only, vector_text | needs derived `name_key` for blocking (Phase 3) |
| `accommodation_type` | canonical_db, filter_payload, vector_text(weak) | source-mapped enum |
| `description` | canonical_db, display_only, vector_text | **Agoda only**; Booking null |
| `star_rating` | canonical_db, filter_payload, grounding_fact | DB CHECK 0-5 |
| `address` | canonical_db, display_only, grounding_fact | |
| `city` | canonical_db, audit_only | raw source text; `destination_id` FK is canonical query path |
| `area_name` | canonical_db, display_only, dedupe_signal(secondary) | |
| `country` | canonical_db, filter_payload(weak) | ISO-mapped |
| `location_highlight` | canonical_db, display_only | **Agoda only** |
| `coordinates` | canonical_db | **raw `"lat,lon"` string, not parsed** — blocks coordinate-distance dedupe until Phase 2/3 add `parse_coordinates` |
| `amenities` | canonical_db, vector_text, filter_payload | needs derived `amenity_keys` |
| `amenity_groups` | canonical_db, audit_only | structure differs per source |
| `highlights` | canonical_db, display_only, vector_text(weak) | **Agoda only** |
| `awards` | canonical_db, display_only | **Agoda only** |
| `warnings` | canonical_db, grounding_fact | cite exactly, never paraphrase |
| `review_score` | canonical_db, filter_payload, grounding_fact | |
| `review_count` | canonical_db, filter_payload, grounding_fact | |
| `review_text` (hotel) | canonical_db, display_only | **Agoda only**, VARCHAR(100) |
| `category_scores` | canonical_db, audit_only | criteria names differ per source |
| `score_distribution` | canonical_db, audit_only | **Agoda only** |
| `check_in_time`/`check_in_until`/`check_out_time` | canonical_db, grounding_fact | |
| `reception_open_until` | canonical_db, grounding_fact | **Agoda only** |
| `image_url` | canonical_db, display_only | thumbnail |
| `images` | canonical_db, display_only | gallery |
| `image_count` | canonical_db, audit_only | |
| `nearby_attractions`/`nearby_essentials` | canonical_db, grounding_fact | **shape differs**: Agoda `list[str]`, Booking `list[object]` |
| `lowest_price` | canonical_db, audit_only | **stale cache** from last crawl; source of truth is `room_prices` — do not cite as current price |
| `currency` | canonical_db, grounding_fact | |
| `price_check_in_date`/`price_check_out_date` | canonical_db, dedupe_signal (price key), grounding_fact | |
| `rooms_available` | canonical_db, audit_only | **semantic mismatch**: Agoda real bool; Booking int room-count coerced to `>0` bool (count lost) |
| `offer_count` | canonical_db, audit_only | |
| `scraped_at` | canonical_db, dedupe_signal (newest tie-break), grounding_fact | |
| `destination_name` | canonical_db (drives `destination_id` FK), filter_payload, dedupe_signal (blocking scope) | |

## Room fields

| Field | Treatment | Notes |
|---|---|---|
| `source_room_id` | canonical_db, dedupe_signal (room key) | |
| `name` | canonical_db, grounding_fact | |
| `bed_description` | canonical_db, grounding_fact | intentionally raw/unparsed (source text too free-form) |
| `room_size_sqm` | canonical_db, grounding_fact | |
| `max_occupancy_raw` | canonical_db, audit_only | kept for context |
| `max_guests` | canonical_db, grounding_fact | **semantic mismatch**: Agoda adults-only, Booking total guests — not cross-source comparable |
| `view` | canonical_db, display_only | |
| `room_facilities` | canonical_db, display_only | |
| `amenity_groups` (room) | canonical_db, audit_only | **Agoda only** |
| `images`/`image_count` (room) | canonical_db, display_only/audit_only | |

## Price fields

| Field | Treatment | Notes |
|---|---|---|
| `price` | canonical_db, grounding_fact | exact source price, excluded from vector text (volatile) |
| `currency` | canonical_db, grounding_fact | |
| `check_in_date`/`check_out_date` | canonical_db, dedupe_signal (natural key), grounding_fact | |
| `sold_out` | canonical_db, grounding_fact | |
| `crossed_out` | canonical_db, grounding_fact | **Agoda only** |
| `review_score`/`review_text` (price-level) | canonical_db, grounding_fact | **Agoda only** |
| `source_url` (price) | canonical_db, dedupe_signal (natural key/tie-break), grounding_fact | fallback to `hotels.source_url` |
| `package_details` | canonical_db, dedupe_signal (natural key) | **neither source currently populates this** — natural key `COALESCE('')` collapses all same-date prices to one slot until a source sends it |
| `crawled_at` | canonical_db, dedupe_signal (newest tie-break), grounding_fact | |

## `_HOTEL_COLUMNS` / `_ROOM_COLUMNS` / `_PRICE_COLUMNS` cross-check

All three column lists (`hotel_pipeline.py:470-500`) match `normalize_hotel()`/`normalize_room()`/price-dict output 1:1 — no orphan fields, no silently-dropped normalize output. `destination_name` and `rooms` are the only normalize-output keys absent from `_HOTEL_COLUMNS`, both by design (resolved to `destination_id` FK / persisted via child tables separately).

## `docs/data_dictionary.md` §2.1 (`hotels_vector`) gap vs current code

`data_dictionary.md` describes a payload with `price_tier` and an embedding text of "name + description + amenities" — **none of this exists in code yet**. No `embedding_text` builder, no `price_tier` computation, no `name_key`, no parsed `lat`/`lon`, no Qdrant payload builder. §2.1 is aspirational; Phase 2 implements it for real.

## Semantic mismatches to preserve (do not silently unify)

1. `description` — Agoda only, Booking null.
2. `max_guests` — Agoda adults-only vs Booking total-guests; not cross-source comparable.
3. `rooms_available` — Agoda real bool vs Booking int-count coerced to bool; count precision lost for Booking.
4. `category_scores`/`score_distribution` — different criteria names/availability per source.
5. `nearby_attractions`/`nearby_essentials` — Agoda `list[str]` vs Booking `list[object]`.
6. `coordinates` — unparsed raw string; no numeric lat/lon yet.
7. Agoda-only fields (`highlights`, `awards`, `location_highlight`, `reception_open_until`, hotel `review_text`, room `amenity_groups`) — will be `NULL` for all Booking rows; downstream code must tolerate absence, not treat as data-quality defect.
8. `lowest_price` on `hotels` is a stale crawl-time cache; `room_prices` is the source of truth for current price.
9. `package_details` — schema slot exists, unused by both sources today.

## Decision boundary (confirmed, unchanged from plan)

- DB identity stays OTA-listing identity: `(source_platform, source_hotel_id)`. No phase after this merges Agoda/Booking rows in Postgres.
- Cross-OTA canonical grouping (Phase 3) is stored in new `hotel_identity_groups`/`hotel_identity_members` tables (decided 2026-07-24), never by collapsing `hotels` rows.
- Score band `0.72-0.86` goes to manual review before use in AI/vector grouping; auto-group only `>= 0.86` (decided 2026-07-24).

## Success criteria check

- [x] Field inventory covers hotel, room, price, source metadata, review, image, location, amenity, and temporal fields.
- [x] Every field has a declared RAG/vector treatment (target, not yet implemented for vector_text/filter_payload/dedupe_signal beyond what code does today).
- [x] Every source-semantic mismatch is recorded before implementation (see above).
- [x] No phase after this relies on a hidden merge of OTA listings (confirmed via decision boundary).
