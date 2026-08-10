# Phase 4 — Vector/RAG Validation Report

## Golden corpus

`src/airflow/tests/fixtures/hotel_golden_corpus.json` — real, trimmed records sampled from `data/agoda.json`/`data/booking.json` (2026-07-24):

| Pair | Distance | Real score | Outcome |
|---|---:|---:|---|
| Lucky Home Huế (agoda 37331206) ↔ Lucky Home Huế (booking 16183651) | 3.5m | 0.813 | `auto_approved` via exact-name+≤80m override |
| Son Ca Motel Huế (agoda 47003936) ↔ Son Ca Motel Huế (booking 10804879) | 0.6m | 0.916 | `auto_approved` |
| Grandma Lu's Saigon Japan Town ↔ Khách sạn PureJoy Saigon - Premium | 24m | 0.561 | not grouped (below 0.72 floor, despite sharing "Saigon" as a blocking token) |

Also sampled but **not** included in the fixture (documented here for traceability): "Muong Thanh Grand Nha Trang Hotel" appears on both OTAs with the exact same name but coordinates ~794m apart (likely a geocoding discrepancy in the source data) — real score **0.656**, below even the review floor. This is an intentional false negative under the plan's stated risk preference ("false positives are worse than false negatives for DB writes") — accepted, not a bug.

## Gates (phase-04 architecture)

| Gate | Result |
|---|---|
| Normalize gate: non-empty `embedding_text` + payload ids | ✅ `EmbeddingTextGoldenSnapshotTests` — all golden hotels |
| Payload gate: payload stays small, no raw JSON blobs | ✅ `PayloadSizeGateTests` (<2000 bytes) + `BuildHotelPayloadTests.test_payload_excludes_large_raw_json_fields` |
| Dedupe gate: duplicate physical hotels collapse in search output | ✅ `RetrievalShapeTests.test_auto_grouped_hotels_collapse_into_one_result_with_multiple_offers` |
| Grounding gate: every displayed fact maps to a DB row | ✅ `grounding_facts` sourced directly from normalized hotel fields (`build_grounding_facts`), covered by `BuildGroundingFactsTests` |
| Bilingual gate | Not runnable without a live embedding model/Qdrant (out of this plan's scope — see roadmap Phase 2). Probe set below is ready for that phase. |

`pending_review` groups are explicitly verified to **not** collapse in `render_hotel_search_results()` (`RetrievalShapeTests.test_pending_review_group_renders_separately_not_merged`) — a group awaiting manual approval must never look merged to the AI/user.

## Bilingual probe set (for roadmap Phase 2 Qdrant/embedding-model evaluation)

Per phase-04 step 5 — not executable today (no embedding model/Qdrant in repo yet), recorded here for that future work:

1. Vietnamese amenity query: `"khách sạn có hồ bơi gần trung tâm"`
2. English query against Vietnamese-described data: `"family hotel with airport shuttle"`
3. Mixed query: `"khách sạn near Ben Thanh có breakfast"`
4. Duplicate query: exact hotel name appearing in both OTA sources — e.g. `"Son Ca Motel Huế"` (see golden corpus above; correct behavior is one collapsed result with 2 offers, not 2 separate hits)
5. Non-duplicate near-miss query: `"Grandma Lu's Saigon Japan Town"` should not surface `"PureJoy Hotel Saigon"` as the same result despite proximity

## Docs updated

- `docs/data_dictionary.md` §2.1 (`hotels_vector`) — replaced the aspirational payload/vector description with the actual implemented `embedding_text`/payload shape.
- `docs/data_dictionary.md` — added §1.4a/1.4b for `hotel_identity_groups`/`hotel_identity_members`.
- `docs/data_pipeline_flow.md` — corrected the Agoda-dedup step description (previously claimed price-only upsert-merge; actual M1 behavior keeps both OTA rows, matching `docs/data_pipeline_flow.md`'s own pre-existing flag from Phase 1's audit).

## Unresolved questions

None — Phase 4 acceptance criteria are met to the extent testable without a live Qdrant/embedding-model integration, which is explicitly out of this plan's scope (roadmap Phase 2 dependency).
