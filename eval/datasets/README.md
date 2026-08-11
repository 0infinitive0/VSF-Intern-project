# Golden datasets

Two hand-authored datasets everything downstream is scored against. See
`plans/260807-1400-ragas-rag-evaluation-harness/phase-02-golden-dataset-construction.md`
for the design and the failure mode this authoring process exists to avoid: expectations
were written **from the corpus, before the retriever ran** — never eyeballed off retriever
output. Section 3 below is the audit trail proving that.

## Schema — `golden-retrieval.jsonl`

One JSON object per line. Enforced by `eval/harness/dataset_loader.py` (rejects unknown
fields, missing/empty `rationale`, malformed UUIDs, duplicate `id`s).

| Field | Required | Notes |
|---|---|---|
| `id` | yes | unique, kebab-case, descriptive |
| `layer` | yes | always `"retrieval"` |
| `search` | yes | `"hotels"` or `"attractions"` |
| `language` | yes | `"vi"` or `"en"` |
| `query` | yes | the literal user query text |
| `expected_ids` | yes | must-retrieve place IDs; **can be empty** for negative/broad-unconstrained cases |
| `rationale` | yes | non-empty; why these IDs, sourced from the corpus |
| `pair_id` | no | links VI/EN mirrors (or a standalone cross-language probe) for delta reporting |
| `filters` | no | the query's intended structured filter, for diagnostics only |
| `acceptable_ids` | no | defensible-but-not-required IDs, excluded from the precision penalty |
| `notes` | no | free text |

`golden-conversations.jsonl` fields: `id`, `layer` (`"e2e"`), `language`, `turns` (ordered
list of literal strings replayed one per turn), `expected_stage` (one of `intake` /
`hotel_options` / `planned` / `modified` / `finalized` / `error` — see
`backend/src/agents/session.py:derive_stage`), `assertions` (free-text list, checked by a
human/LLM reading the Phase 4 transcript, not machine-parsed).

**A turn-scripting fact learned the hard way (2026-08-11):** `TripIntakeState.is_complete`
requires a `start_date` before intake completes at all — a conversation script that never gives
one gets stuck re-asking for it forever (`reached_stage` stays `intake`). Give a **concrete**
date (`"Khởi hành ngày 20/08/2026"`); a relative phrase like `"tuần sau"` (next week) was
verified live to extract as `start_date: None` and does not unblock the flow. See
`eval/results/ragas-<ts>.md`'s finding #1 for what happens *after* intake completes.

## Destination coverage (Open Question 1)

Live `destinations` table (verified 2026-08-10) has exactly 5 rows: Nha Trang, Hà Nội, Đà
Nẵng, Huế, Hồ Chí Minh. Per-destination hotel/attraction counts are roughly even (~200
each, HCM ~300/210) — there is no naturally "thin" destination by row count. Coverage
picked: **Nha Trang, Đà Nẵng, Hồ Chí Minh** (the plan's default, BRD-mentioned trio) **+
Huế** as the 4th/long-tail slot — an arbitrary but reasonable tie-break over Hà Nội, chosen
for cultural/geographic distinctness (imperial-era heritage city, no dominant
international hotel chain) rather than corpus thinness, which doesn't actually exist here.

## How the candidates were found

`eval/harness/corpus_helper.py` filters the offline `eval/fixtures/vector_bench/*.json`
fixture by structured attributes only (destination, star rating) — no semantic fields
live there. Semantic judgment (sea view, family-friendly, near-center, category) required
reading the live Supabase `hotels`/`attractions` rows (`description`, `area_name`,
`location_highlight`, `amenities`, `lowest_price`, `category`, `rating`) — pulled via a
throwaway authoring script (not committed; equivalent to hand-browsing Supabase) on
2026-08-10, cross-checked against the fixture for ID consistency (903 of 904 pulled IDs
matched the fixture exactly; 1 Nha Trang hotel exists live but not in the fixture — minor,
expected corpus drift, not chased further).

## Cross-language cases (BR-10)

5 standalone probes (not VI/EN mirror pairs — each is a single-direction test and its
`pair_id` has no partner, unlike the destination-query pairs): `hotel-crosslang-hyatt`,
`hotel-crosslang-novotel` (VI sentence, EN hotel name), `hotel-crosslang-khachsan`,
`hotel-crosslang-khachsan-pullman` (EN sentence, VI hotel name), plus
`hotel-crosslang-libertycentral` (VI sentence, EN hotel name). All target a hotel whose
brand name appears verbatim in the query, in the query's non-native language.

## Negative / broad-unconstrained cases

- `hotel-negative-destination-absent-vi`, `attraction-negative-absent-vi` — "Phú Quốc" is
  absent from the live `destinations` table entirely (verified 2026-08-10).
- `hotel-negative-impossible-price-vi` — 5★ under 100,000 VND/night; verified zero matches
  across all 4 pulled destinations (cheapest 5★-labelled listing found was 120,985 VND — a
  mislabelled hostel, itself a data-quality observation, see below).
- `hotel-hue-thin-vi` — a thin-corpus probe (not a hard negative): Huế has essentially no
  dedicated honeymoon/secluded-resort product near the city.

## Corpus data-quality observations (found while authoring, not retriever bugs)

- **Star-rating labels are noisy.** Several very cheap hostels (e.g. "The Backpacker
  hostel và Spa" in Đà Nẵng, 120,985 VND) are tagged `star_rating=5.0` in the source data.
  The "impossible constraint" negative case had to be re-verified against live data rather
  than assumed, because a naive "5★ = expensive" assumption is false in this corpus.
- **`price_tier` in the offline fixture is always `null`** (0/1103 hotels have a value) —
  dead field, not usable for price filtering. Live `hotels.lowest_price` was used instead.
- **The kids-play attraction category has severe generic-name duplication.** Dozens of
  distinct physical locations across all 4 destinations share the near-identical name
  pattern "Khu vui chơi trẻ em" (children's play area). No single instance is a principled
  must-retrieve answer for a query in this category — see the adjudication log below.

## 3. Disagreement list & adjudication (step 11)

The retriever was run **once**, after every expectation above was authored, via
`search_hotels_with_rooms` / `search_attractions` with `use_llm_filter=True` (production
config) over all 44 retrieval records (2026-08-10). All 44 executed without an unhandled
exception. 29/44 had at least one missed `expected_id`; every one was adjudicated by hand
below. **No expectation was changed to match retriever output without the reasoning
written here.**

### Category A — `expectation-corrected` (the author's error, not the retriever's)

| Records | What was wrong |
|---|---|
| `hotel-nhatrang-city-{vi,en}`, `hotel-nhatrang-center-vi`, `hotel-danang-city-{vi,en}`, `hotel-hue-city-{vi,en}` | Required a single "flagship" hotel to rank top-10 for a broad, unconstrained destination-only query. No principled basis: embedding similarity encodes semantic content, not brand prominence. Flagship IDs moved to `acceptable_ids`; `expected_ids` now empty for these 7 records. |
| `hotel-nhatrang-4star-price-{vi,en}` (Golden Rain 2 half) | Claimed "view biển" (sea view) for a hotel whose live amenities have no sea-view/beach tag (only generic beach-proximity in free text). Downgraded to `acceptable_ids`; kept genuinely-verified Quinter Central Nha Trang (confirmed "Bãi biển riêng" amenity) as the sole `expected_id`. |
| `hotel-hcm-luxury-{vi,en}` | "Sang trọng" (luxury) has no structured filter to anchor a single answer; retriever surfaced other legitimate 5★ heritage hotels (Majestic, Rex, Windsor Plaza). Broadened `acceptable_ids` rather than treating as a miss. **2026-08-11 follow-up:** the same reasoning applies to the two IDs the original author had left in `expected_ids` (Rex, Windsor Plaza) — no principled basis to require exactly those two over the other verified-luxury alternates already in `acceptable_ids`. Moved them in too; `expected_ids` now empty like the other broad-unconstrained records above. This was the one genuine authoring inconsistency found while auditing all 12 zero-recall retrieval records on 2026-08-11 (see "Context Recall audit" below) — the other 11 are Category B retriever-findings, already listed above, left unchanged. |
| `hotel-hcm-hostel-vi` | "9 Hostel and Suites" correctly surfaced; "9 Hostel and Bar" is a tied-price near-duplicate with no principled reason to outrank alternates. Downgraded, broadened `acceptable_ids`. |
| `hotel-danang-budget-{vi,en}` | Starfish Alley correctly surfaced; Brown Bean is a tied-price duplicate. Same treatment. |
| `attraction-hcm-history-{vi,en}` | Dinh Độc Lập correctly surfaced; Bến Nhà Rồng did not (soft finding, kept). Added the War Remnants Museum as a verified acceptable alternate. |
| `attraction-nhatrang-kids-{vi,en}`, `attraction-hcm-kids-{vi,en}`, `attraction-danang-kids-vi` | Kids-play category duplicate-naming problem (see above) — no single instance is a principled must-retrieve answer. `expected_ids` emptied or reduced to the one instance that did surface; broadened `acceptable_ids`. |

### Category B — genuine `retriever-finding` (kept, `expected_ids` unchanged)

| Record | Finding |
|---|---|
| `hotel-crosslang-libertycentral-vi` | **Most severe finding of this run.** Query is `"Liberty Central Saigon Centre giá bao nhiêu"` — the hotel's full name appears verbatim — yet it does not rank in the top 10. |
| `hotel-crosslang-novotel-vi` | Query contains `"Novotel Premier"` near-verbatim; the hotel does not rank in the top 10. |
| `attraction-hue-citadel-{vi,en}` | **Root-caused, not just observed.** The original query returned zero results; simplifying to natural phrasing ("Đại Nội Huế" / "Hue Imperial City") *still* returns zero. Direct debugging isolated the cause: `extract_search_filters` strips the destination name out of the embedding query, leaving the bare 2-word `"Đại Nội"`; at the production `match_threshold=0.4` that phrase has zero attractions above threshold in Huế — not even "Ngọ Môn" (the Citadel's own Meridian Gate), which only appears once the threshold is manually dropped to 0.2. A real embedding-alignment gap between a landmark's colloquial name and its formal database name, compounded by aggressive `clean_query` stripping. |
| `hotel-nhatrang-4star-price-{vi,en}` (Quinter Central half) | Genuinely satisfies star + price + a verified "Bãi biển riêng" amenity, yet does not rank top-10. |
| `hotel-danang-pool-vi` | Both expected hotels verified to genuinely have pool amenities (`Hồ bơi ngoài trời` / `lối vào hồ bơi`); neither ranks top-10. Two 5★ resort alternates the retriever did surface were added to `acceptable_ids` (pool plausible given resort category, not individually re-verified). |
| `hotel-hcm-district1-{vi,en}` | Diagnostic: the live run returned only 4 total candidates for this star+price+destination filter combination — a thin-result-set finding, not an expectation error. |
| `hotel-hcm-family-vi` | Eastin Grand Hotel Saigon's live amenities verified to include `Phòng gia đình` / `Thích hợp cho gia đình/trẻ em`; does not rank top-10. |

None of these are fixed here — this plan measures, it does not tune retrieval (see
plan Non-goals). They are exactly the evidence Phase 3/5's reports are built on.

## Conversations removed from the e2e suite (2026-08-11)

Two of the original 12 scripted conversations were dropped at the project owner's direction,
after the price-hallucination bug (see `eval/README.md`'s Deviations section) was fixed but these
two still failed for unrelated reasons:

- `conv-danang-edit-cheaper` — the post-planning "đổi khách sạn rẻ hơn" edit request still
  doesn't reliably route to `execute_trip_edit_request` (a pre-existing routing gap, not
  price-related).
- `conv-crosslang-hyatt-danang` — a short (3-turn) brand-name hotel search that occasionally still
  fails to retrieve any hotel via a residual tool-calling issue distinct from the fixed bug.

Removed, not disproven: both are real, legitimate gaps worth a case again once addressed
separately - this just narrows what the current suite measures.

## Context Recall audit (2026-08-11)

12 of the 44 retrieval records score `non_llm_recall=0.0`. Audited each one individually
against Section 3's disagreement list rather than assuming they're all the same class of
problem:

- **11/12 are genuine, already-adjudicated Category B retriever-findings** from the original
  2026-08-10 pass (`hotel-crosslang-libertycentral-vi`, `hotel-crosslang-novotel-vi`,
  `attraction-hue-citadel-{vi,en}`, `hotel-nhatrang-4star-price-{vi,en}` (Quinter Central
  half), `hotel-danang-pool-vi`, `hotel-hcm-district1-{vi,en}`, `hotel-hcm-family-vi`) — real
  gaps the retriever has, not dataset errors. Left unchanged; loosening `expected_ids` here to
  raise the recall number would misrepresent what was actually verified against the corpus.
- **1/12 was a genuine authoring inconsistency**: `hotel-hcm-luxury-{vi,en}` (see the updated
  Category A row above) — fixed by moving its last two `expected_ids` into `acceptable_ids`,
  consistent with the same "no principled single answer for an unconstrained luxury query"
  reasoning already applied to its sibling records the day before.

Net effect of the one fix on the aggregate numbers (`non_llm_recall_by_language`):
VI 0.5278→0.5588, EN 0.5833→0.6364 — small and expected, since only one record's denominator
changed. This plan measures, it does not tune retrieval (Non-goals) — the 11 real gaps stand
as findings for future retrieval work, not something this dataset should paper over.

## Context Precision LLM gap: root cause and fix (2026-08-11)

The VI/EN gap on `llm_precision` (`LLMContextPrecisionWithReference`) was large and suspicious
(VI 0.368 vs EN 0.035) — investigated before assuming it reflected a real retrieval/embedding
quality difference between languages. `LLMContextPrecisionWithReference` uses each record's
`rationale` field as `reference` — its only ground truth for judging whether a retrieved
context is relevant.

14 EN records' `rationale` was literally just `"EN mirror of X-vi, same intent."` — no
hotel/attraction names, prices, or facts for the judge to check retrieved contexts against.
Proved this was the cause with an isolated test (identical contexts and query, only the
reference text swapped): thin reference scored `0.0`, the same context scored with a rich
reference scored `0.9999999999`.

**Fix:** rewrote the core `rationale` for all 14 affected EN records (`hotel-nhatrang-city-en`,
`hotel-nhatrang-4star-price-en`, `hotel-nhatrang-budget-en`, `hotel-danang-city-en`,
`hotel-danang-center-price-en`, `hotel-danang-budget-en`, `hotel-hcm-district1-en`,
`hotel-hue-city-en`, `attraction-hcm-history-en`, `attraction-danang-nature-en`,
`attraction-nhatrang-kids-en`, `attraction-hue-citadel-en`, `attraction-hcm-kids-en`,
`hotel-crosslang-khachsan-pullman-en`) to carry the same substantive facts as their VI
counterpart, restated in English — hotel/attraction names, prices, star ratings, the specific
verified detail (e.g. "Bãi biển riêng" amenity, "1,3 km từ trung tâm"). Any existing
`ADJUDICATED`/`DIAGNOSTIC`/`RETRIEVER FINDING` note was preserved, appended after the new core
text, not deleted — the finding itself didn't change, only the thin boilerplate around it.

Result: `llm_precision_by_language` VI 0.3676→0.4033, EN 0.035→0.4742. The gap is gone — EN and
VI now land in the same range. This confirms the original gap was a dataset-authoring artifact
(thin EN reference text), not a real VI/EN retrieval quality difference.

## Adding a new case

1. Filter the offline fixture with `corpus_helper.py` for structured candidates.
2. Read the live Supabase row(s) to verify the semantic claim in your `rationale` — do not
   assert an amenity/description match without checking it (see the Golden Rain 2 correction
   above for what happens when you skip this).
3. Write the record with a real `rationale` citing what you checked.
4. **Do not run the retriever to pick `expected_ids`.** Run it only after authoring, to
   build the next disagreement list.
5. Validate: `eval/.venv-eval/bin/python eval/harness/dataset_loader.py`.
