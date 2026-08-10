---
phase: 2
title: "Golden dataset construction"
status: pending
priority: P1
effort: "1.5-2d"
dependencies: [1]
---

# Phase 2: Golden dataset construction

## Overview

Author the two datasets everything downstream is scored against: a bilingual retrieval golden set
(query → expected place IDs) and a set of scripted conversations for end-to-end evaluation. This is
the phase that decides whether any later number means anything.

## The failure mode this phase exists to avoid

The tempting shortcut is to run the current retriever, eyeball the top results, and record them as
"expected". That produces a dataset the retriever scores ~1.0 on by construction, and which will
keep scoring ~1.0 no matter how the retriever changes. The roadmap already names this trap:

> "A self-graded metric with a self-chosen test set is worth little at go/no-go."
> — `phase-04-search-filter-and-booking-handoff.md`

So: **expectations are authored from the corpus and from BRD intent, before the retriever is run.**
When the retriever later disagrees with an expectation, that disagreement is the finding. It gets
adjudicated by hand and the reasoning gets written down — it does not get silently resolved in the
retriever's favour.

## Requirements

- Functional: ≥ 40 retrieval queries, each with expected place IDs and a stated rationale.
- Functional: VI and EN variants of the same intent, plus explicit cross-language cases
  (VI query whose target hotel is described in English, and the reverse) per BR-10.
- Functional: ≥ 10 scripted conversations that reach a hotel recommendation or a finished itinerary.
- Functional: negative cases — queries that *should* return little or nothing.
- Non-functional: JSONL, one record per line, hand-editable, stable IDs.
- Non-functional: every expectation carries a `rationale` field. No unexplained ground truth.

## Architecture

### Retrieval set — `eval/datasets/golden-retrieval.jsonl`

```json
{
  "id": "hotel-nhatrang-seaview-vi",
  "layer": "retrieval",
  "search": "hotels",
  "language": "vi",
  "pair_id": "hotel-nhatrang-seaview",
  "query": "khách sạn 4 sao view biển ở Nha Trang dưới 2 triệu",
  "filters": {"destination": "Nha Trang", "min_star_rating": 4, "max_price": 2000000},
  "expected_ids": ["2e707c55-...", "8b1a...", "c94f..."],
  "acceptable_ids": ["11de...", "77ab..."],
  "rationale": "Từ eval/fixtures/vector_bench/hotels.json: destination_id 6f860287 + star>=4; sea-view confirmed in hotel description.",
  "notes": "cross-language pair with hotel-nhatrang-seaview-en"
}
```

`expected_ids` are must-retrieve. `acceptable_ids` are defensible-but-not-required and are excluded
from the precision penalty — without this distinction precision is unfairly punished for returning
a genuinely good hotel that simply was not thought of during authoring.

`pair_id` links VI/EN variants so Phase 5 can report a cross-language delta rather than two
unrelated averages.

### Conversation set — `eval/datasets/golden-conversations.jsonl`

```json
{
  "id": "conv-danang-family-3d",
  "layer": "e2e",
  "language": "vi",
  "turns": [
    "Tôi muốn đi Đà Nẵng 3 ngày 2 đêm",
    "2 người lớn 1 trẻ em",
    "Ngân sách khoảng 1.5 triệu một đêm, thích khách sạn gần biển",
    "Chọn khách sạn đầu tiên"
  ],
  "expected_stage": "planned",
  "assertions": ["itinerary covers 3 days", "hotel is in Đà Nẵng", "no invented hotel names"]
}
```

`turns` are fixed strings replayed in order. `expected_stage` maps to `derive_stage`
(`backend/src/agents/session.py:89`) so a conversation that never reaches its stage is reported as
a *harness* failure, not scored as a bad answer — those are different problems and must not be
averaged together.

### Building expectations from the corpus

`eval/fixtures/vector_bench/hotels.json` (1,103 records: `hotel_id`, `name`, `destination_id`,
`star_rating`, `price_tier`) is the authoring aid. Write a throwaway filter helper to answer
"which hotels in destination X have star ≥ N", then read the candidates' descriptions in Supabase
to decide which genuinely match the query's semantic intent (sea view, family-friendly, near
centre). Structured attributes narrow the field; the semantic judgement is human.

## Related Code Files

- Create: `eval/datasets/golden-retrieval.jsonl`
- Create: `eval/datasets/golden-conversations.jsonl`
- Create: `eval/datasets/README.md` — schema, authoring rules, how to add a case
- Create: `eval/harness/dataset_loader.py` — parse + schema-validate both files
- Create: `eval/harness/corpus_helper.py` — filter `vector_bench/hotels.json` while authoring
- Read only: `eval/fixtures/vector_bench/hotels.json`, `eval/fixtures/vector_bench/attractions.json`
- Read only: `plans/260723-1015-v-ota-poc-master-roadmap/phase-04-search-filter-and-booking-handoff.md`
- Read only: `docs/brd/` — scenario intent

## Implementation Steps

1. Settle destination coverage. Default assumption (plan Open Question 1): Nha Trang, Đà Nẵng,
   Hồ Chí Minh, plus one long-tail destination to expose thin-corpus behaviour.
2. Write `corpus_helper.py` — load the fixture, filter by destination/star/price, print candidates.
3. Draft ~20 VI hotel queries spanning: destination-only, destination + star, destination + price
   ceiling, amenity-driven (pool, sea view), area-driven (near centre/beach), and 2 negatives
   (a destination absent from the corpus; an impossible constraint such as 5-star under 300k).
4. Mirror those into EN. Keep the intent identical; do not translate word-for-word where a native
   phrasing differs — the point is a realistic EN user, not a translation exercise.
5. Add 4-6 explicit cross-language cases: VI query targeting an English-described hotel and the
   reverse. These are BR-10's actual requirement and the ones most likely to fail.
6. Add ~10 attraction queries by the same method against `attractions.json`.
7. For each query, fill `expected_ids` from the corpus and write the `rationale`. **Do not run the
   retriever during this step.**
8. Write the 10+ conversation scripts, weighted toward BRD scenarios. Include one edit turn
   ("đổi khách sạn rẻ hơn") and one unsupported-destination case.
9. Write `dataset_loader.py` with strict schema validation — reject unknown fields, missing
   `rationale`, malformed UUIDs, and duplicate `id`s. A silently-skipped malformed row would
   quietly shrink the eval set.
10. Only now, run the retriever once over the set and produce a **disagreement list**: expected IDs
    that were missed, and high-ranked results absent from both expectation lists.
11. Adjudicate that list by hand. Each item resolves to either "expectation was wrong, here's why"
    or "retriever is wrong, this is a finding". Record both in `eval/datasets/README.md`. The
    second category is the first real output of this whole plan.

## Success Criteria

- [ ] ≥ 40 retrieval records validate against the loader; ≥ 10 conversation records.
- [ ] VI and EN both present, with ≥ 4 cross-language `pair_id` cases.
- [ ] ≥ 2 negative retrieval cases.
- [ ] Every record has a non-empty `rationale`.
- [ ] `dataset_loader.py` rejects a deliberately malformed record with a clear error.
- [ ] The step-11 disagreement list exists in `eval/datasets/README.md`, with each item marked
      `expectation-corrected` or `retriever-finding`, and reasoning for each.
- [ ] No expectation was changed to match retriever output without a written reason.

## Risk Assessment

- **Authoring bias toward what the retriever already does** — the central risk. Steps 7 and 11 are
  ordered specifically to prevent it, and the disagreement list is the audit trail proving it
  didn't happen.
- **Corpus fixture may be stale relative to live Supabase.** Check a sample of `hotel_id`s against
  the live DB before authoring at scale; if the fixture has drifted, regenerate it first.
- **40+ hand-authored cases is genuinely slow work.** Effort is the honest estimate, not padding.
  If it must be cut, cut destinations (keep 2) before cutting cross-language cases — those are a
  BRD requirement.
- **UUID typos silently produce zero recall.** The loader validates UUID format; step 11's
  disagreement list catches an ID that is well-formed but wrong.
- **Attraction ground truth is fuzzier than hotels** (no star rating to anchor on). Lean on
  `category` and destination, and accept wider `acceptable_ids` there.
