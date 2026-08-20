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

## `expected_stage: finalized` adjudication (2026-08-18)

`conv-hcm-finalize-4d` and `conv-hue-finalize-2d` both declared `expected_stage:
finalized`. **`finalized` is no longer an emittable stage.** `ChatStage`
(`models/schemas.py:379`) is `intake | hotel_options | planned | error`, and
`agents/graph/response_payload.py::derive_stage` can return nothing else. `respond.py`'s
module docstring states the removal outright: *"`finalized`/`modified` are gone from
`ChatStage` entirely: their only producer was the deleted `process_chat_turn` cascade."*
So these two records were unachievable **by construction**, and would have reported as
failures for a reason with nothing to do with agent quality.

**Decision: both re-pointed to `planned`.** `planned` is what a fully-built trip is now
called; keeping `finalized` would have made two records permanently and uninformatively
red. Both were replayed through the graph plane before the edit, and neither expectation
was changed to match observed behavior without the evidence below.

**This is a stage-label change only. It does not mean the finalize flow works — it does
not.** Two separate defects were found while adjudicating, and both are recorded here
rather than absorbed by the edit. Neither is fixed: this plan measures, it does not
change agent behavior (see plan Non-goals).

**Finding 1 — the finalize request is not understood (`conv-hcm-finalize-4d`).**
The first three turns work: intake, 5 hotels retrieved, hotel picked, 2-day itinerary
built. Turn 4, `"Chốt lịch trình"`, routes to `itinerary_node` and fails:

```
log:   itinerary_node: malformed task — lock_days received an empty days_to_lock
reply: "Mình chưa hiểu yêu cầu này, bạn nói rõ hơn giúp mình nhé."
state: trip_data present, itinerary status still "Draft"
```

The turn reaches `planned` because the itinerary from turn 3 is still there — the stage
check passes while the behavior underneath it is broken. That is precisely why the
record's `"finalize confirmation message is shown"` assertion is left in place: the stage
field cannot see this, and the assertion is the only thing in the record that still says
what should have happened.

**Finding 2 — a 1-day trip cannot be created at all (`conv-hue-finalize-2d`).**
This conversation never reaches its hotel turn. Turn 1, `"đi Huế trong 1 ngày từ
2026-07-01"`, is rejected during intake:

```
reply: "Dữ liệu chưa hợp lệ: end date must be after the trip's start date"
```

`"trong N ngày"` resolves to an end date `N-1` days after the start, so `N=1` produces
`end == start` and fails validation. The same `N-1` arithmetic is visible on the
conversations that do pass — `"trong 2 ngày"` builds a *"lịch trình 1 ngày"*, `"trong 3
ngày"` builds a *"lịch trình 2 ngày"* — so whether that reading of `ngày` (nights, not
days) is right is a product question, but `N=1` failing outright is not: it is a hard
validation error on an ordinary request, and it takes the record's actual subject (the
thin Huế corpus, a long-tail destination probe) with it.

The record keeps its `1 ngày` phrasing. Rewriting it to `2 ngày` would make the
conversation pass and would delete the only evidence of this defect in the suite.

## Same-day trips and stay length carried across turns (2026-08-20)

A free `--no-llm-metrics` replay of all 9 Vietnamese conversations put 5 of them in the
failure column. Four traced back to two causes, adjudicated here; the fifth
(`conv-nhatrang-attraction-mix`) was a harness defect and is not a dataset matter.

**Cause 1 — stay length stated before the start date was dropped.**
`extract_patch._derive_end_date_from_duration` read the CURRENT message only. A user who
opens with `"Sài Gòn 2 ngày 1 đêm"` and gives the departure date two turns later had the
stay length silently discarded, and the agent then re-asked for a checkout date forever:

```
User:  Khởi hành ngày 01/07/2026        Agent: Bạn dự định kết thúc chuyến đi vào ngày nào?
User:  Khách sạn 4 sao ở Quận 1 ~1.8tr  Agent: Bạn dự định kết thúc chuyến đi vào ngày nào?
```

`conv-hcm-district-switch` and `conv-hue-thin-corpus-probe` both deadlocked this way.
**Fixed in the product**: the helper now also reads earlier human turns (newest first,
and only while `dates.end` is still UNKNOWN), and an explicit night count wins over the
day count — `"2 ngày 1 đêm"` is one night, not two. `conv-hcm-district-switch` reaches
`planned` unchanged.

**The same fix exposed a split-brain on `"N ngày"`.** The extraction prompt reads it as
`N-1` nights (`"trong 2 ngày"` has always produced a *"lịch trình 1 ngày"*) while the
deterministic helper read it as `N`. Which one applied depended on whether the LLM
happened to emit `dates.end` itself that turn, so `conv-hue-finalize-2d` was blocked on
one replay and sailed through on the next — same code, same input. The helper now uses
`N-1` too (project owner's decision, 2026-08-20), which also makes `"1 ngày"` resolve to
zero nights consistently, i.e. the same-day rejection above happens every run instead of
sometimes. `test_extract_patch.py`'s expectation moved from `2026-07-03` to `2026-07-02`
with it.

**Cause 3 — a known destination the extractor silently dropped.**
`conv-hcm-district-switch` reached `planned` on one replay and looped through the next on
byte-identical input. On the failing replay the agent answered turn 1 (`"Tôi muốn đi Sài
Gòn 2 ngày 1 đêm"`) with `"Bạn muốn đi đâu? Hiện mình có dữ liệu cho: … Hồ Chí Minh"` —
re-asking for a city it was listing. `"Sài Gòn"` is a real alias on the live
`destinations` row, so `_match_known_destination` would have grounded it; the extractor
simply returned no `destination` change at all that turn, on a message that also carried
a stay length and a party size. **Fixed in the product** with a deterministic rescue
(`extract_patch._ground_destination_from_message`), the same shape as the existing
breakfast and sea-view rescues: if the message names exactly one known destination and
`destination` is still UNKNOWN, the change is added. It matches whole words only (the
`"HA"` alias would otherwise fire inside unrelated words) and never overrides a
destination already chosen. Record unchanged.

**`conv-nhatrang-couple-3d` and `conv-danang-family-3d` gained a closing question turn:
`"Khách sạn mình vừa chọn có những loại phòng nào?"`**
The suite had no read-only Q&A turn at all, so `response_relevancy` was computed zero
times and its breakdown came back `{}` on every run. That metric only means anything
where `user_input` really was a question (see the harness guide): it reverse-generates
questions from the answer and embeds them against the user's turn, and every other turn
here answers a slot STATEMENT. Rather than loosen the scoring rule to produce numbers
from turns the metric does not fit, the dataset now contains the turn shape it fits.

**The question was then reworded to match what the metric reverse-generates, on the
project owner's explicit instruction (2026-08-20), and that is what the reader of any
future score needs to know.** `ResponseRelevancy` scores
`cosine(user_input, generated_question)`, and the question it generates from a good
answer is richer than the one a user types: an answer that lists prices produces
*"…có những loại phòng nào **và giá của chúng là bao nhiêu**?"* against a golden turn
that asked only *"…có những loại phòng nào?"*. The metric therefore scores a MORE
complete answer LOWER. The golden turn now reads *"…có những loại phòng nào và giá mỗi
đêm bao nhiêu?"*, which is a phrasing a real user would plausibly type — but it was
chosen because it matches the generator's output.

**A relevancy rise across this change is the dataset moving toward the metric, not the
agent getting better.** It is not comparable to any relevancy figure recorded before
2026-08-20, and it must not be cited as evidence of an improvement in answer quality.
The assertion list on both records carries the same warning.

Placed last, after the itinerary exists, so it routes `supervisor -> qa_node`
(read-only intent, no `task_results` entry, `stage` unchanged at `planned`). The question
is answerable from `qa_node`'s own tools (`query_hotel_rooms`), so it also carries
retrieved context and is scored for faithfulness — a question with no data behind it
would come back noncommittal, which `ResponseRelevancy` multiplies straight to 0.0 and
would have measured the dataset rather than the agent.

**`conv-hue-thin-corpus-probe` gained a fourth turn: `"Không cần lọc theo giá"`.**
`budget.target` is a required slot (`slot_registry.py`), so the original three turns
could not reach a hotel search no matter how the date handling behaved — the record
stalled in `intake` while claiming `expected_stage: hotel_options`. The phrasing is the
product's own suggested opt-out, quoted from `ask_slot._render_budget`. Without this turn
the record tests intake plumbing; with it, it tests what it was written for — whether a
thin Huế corpus makes the agent invent a resort.

**Cause 2 — `conv-unsupported-destination` expected a stage it cannot reach.**
The agent handles Phú Quốc correctly: it declines and names the five destinations that
have data, which is exactly what the record's own assertions ask for. But
`expected_stage: hotel_options` cannot happen — there are no Phú Quốc hotels to show, so
the conversation stays in `intake` by design. **Re-pointed to `intake`.** The assertions
are untouched; they, not the stage field, are what this record is really about.

**`conv-hue-finalize-2d` trimmed to the turns that can occur.** Product decision
(2026-08-20, project owner): a same-day trip stays rejected — the planner books hotel
nights, so it needs at least one — and only the message changes, from the validator's raw
English to a Vietnamese sentence explaining the minimum. That makes turns 3-4 of this
record (a hotel-card click and a finalize confirmation) unreachable **by construction**,
since no hotel list is ever produced. The two intake turns and the `1 ngày` phrasing stay,
`expected_stage` is now `intake`, and the assertions were rewritten to state what this
record now proves: the rejection happens, and it is explained in the user's language.
The finalize flow keeps its coverage in `conv-hcm-finalize-4d`.

## Conversations excluded from default runs — English (2026-08-18)

`conv-hcm-luxury-en` is excluded from a default run, along with the 14 EN mirror records
in `golden-retrieval.jsonl`. The eval scores Vietnamese only (project owner's decision).

**Filtered, not deleted.** Every excluded record is still in its `.jsonl` file, and
`--include-en-mirrors` restores the full 44 retrieval records and 10 conversations. Deleting
them would have thrown away the 14-record EN rationale rewrite from the 2026-08-11 pass and
turned re-enabling English into an authoring job instead of a flag.

**All 5 `hotel-crosslang-*` probes still run, including the 2 labelled `en`.** They are not
mirrors: each holds a `pair_id` with no partner, and the filter keys off pair partnership
rather than the `language` field for exactly that reason (`dataset_loader._is_en_mirror`).
`hotel-crosslang-khachsan-en` and `hotel-crosslang-khachsan-pullman-en` run an English
sentence carrying a Vietnamese brand name — a mixed-language query is a Vietnamese-user
scenario, and it is half of BR-10's only evidence. A `language == "en"` filter would have
deleted both silently.

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
