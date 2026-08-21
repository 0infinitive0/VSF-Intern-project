# Implementation Plan: Hotel Preference Extraction, Catalog Query, and Matching

Supersedes the unfinished parts of `plans/amenity-catalog-scored-matching-plan.md`
(Phase 1 Task 1, Phase 3, and Phase 4 were never applied — `parent_id` does not
exist in the deployed schema, and the 27 duplicate-label groups it planned to
merge are still present). It keeps that plan's scoring contract and reverses
exactly one of its decisions, with evidence: "semantic-vector search or
embeddings" is no longer out of scope.

## Overview

Today a user's amenity request travels through four layers and loses information
at three of them. The request is extracted as free text, stored as free text,
re-matched against the catalog on every search turn, and finally compared as a
canonical ID set. Only that last step is correct.

This plan moves resolution to **write time**, gives preferences **polarity and
strength**, makes the catalog **hierarchical and coverage-aware**, and replaces
the all-or-nothing conjunctive filter with a **relaxation ladder**. It closes
with the evaluation harness that makes all of it verifiable, which is the piece
that does not exist today and the reason each past fix has been a guess.

## Measured baseline

Every number below is from the live Supabase project `V_OTA`, 2026-08-21.

| Fact | Value | Consequence |
| --- | ---: | --- |
| Hotels storing only canonical catalog IDs | 1104 / 1104 | The compare step is already correct. The keyword-substring fallback in `hotel_matches_amenity_tag` is dead code. |
| Approved catalog entries | 474 | Small enough to embed entirely in memory, and to show the extractor as a vocabulary. |
| Duplicate `label_vi` groups | 27 groups, 61 rows | An exact user match becomes *unresolvable*, because two rows tie. This is the `beauty_service` / `beauty_services` defect. |
| Keywords owned by more than one entry | 237 | The `spa` ambiguity class, 237 instances of it. |
| Catalog entries no hotel has | 30 | Binding to one guarantees a zero-result search. |
| Coverage of the `wifi` entry | **0 hotels** | `free_wi_fi_in_all_rooms` = 494, `public_wi_fi` = 476, `free_wi_fi` = 291. A user who says "wifi" gets the one binding that matches nothing. |
| `swimming_pool` ∧ `spa` ∧ `gym` ∧ `parking` ∧ `wifi` | **0 hotels** | Before destination, dates, price, or capacity are applied. The conjunctive model collapses at five amenities. |
| Average amenities per hotel | 65.5 (max 281) | Hotel-side data is rich; hierarchy expansion is safe and cheap. |

## The five structural faults

**F1 — Resolution happens at read time, not write time.**
`hotel_preferences.amenities` stores the user's raw words. Binding to catalog
IDs happens turns later inside `hotel_node`. So `remove` compares raw strings:
saying "bể bơi" and later "bỏ hồ bơi đi" cannot cancel, because the strings
differ. Unresolvable terms sit in an append-only slot forever and are re-reported
in every subsequent search reply. The same fuzzy match is recomputed every turn.

**F2 — The extractor is blind to the catalog.**
The prompt offers `amenities (list of strings)` with two examples, so the model
invents phrasings the catalog has never heard of — "wifi miễn phí", "bãi đỗ xe",
"free wifi". The generator does not know the matcher's vocabulary, and the
catalog is only 474 entries.

**F3 — The extractor/validator type contract is ambiguous, and failure is silent.**
`apply_patch` requires `append`/`remove` to carry a bare string and `set` to
carry a list. The prompt states only "list of strings". The model therefore emits
`{"operation": "append", "value": ["hồ bơi"]}`, which is rejected with
`expected a string, got list` — and the rejection is never logged or surfaced.
Reproduced 4 times out of 4 on first-mention single-amenity messages, the single
most common phrasing in the product.

**F4 — There is no representation for negative or soft preferences.**
Only "must have X" exists. "không cần hồ bơi" becomes a `remove` that fails when
nothing is set. "ưu tiên gần biển" can only be a hard filter or nothing. Combined
with F5 this is what produces dead-end searches.

**F5 — Catalog hygiene is unmanaged, and the scraper writes to the table chat reads.**
`discover_and_store_amenities` writes LLM-invented rows with `is_approved=true`
straight into the live catalog. That is the mechanism that produced 27 duplicate
groups and 237 over-shared keywords.

## Target pipeline

```
message
  │
  ├─[1] EXTRACT   mentions, not strings:
  │               {phrase, polarity: require|exclude|prefer, op: add|drop|clear}
  │               prompt carries a catalog vocabulary hint
  │
  ├─[2] BIND      lexical ∪ semantic candidates, coverage-aware rerank
  │               → resolved | ambiguous(top-k) | unresolved
  │               ambiguous → one bounded LLM choice, else a clarify chip
  │
  ├─[3] COMMIT    travel_state stores BOUND records:
  │               {id, label, polarity, source_phrase, confidence}
  │               drop/clear operate on IDs
  │
  ├─[4] PLAN      expand id → {id} ∪ descendants
  │               require/exclude → hard predicate; prefer → ranking boost
  │               relaxation ladder when the conjunction is empty
  │
  ├─[5] COMPARE   ID-set membership (already correct — simplify only)
  │
  └─[6] EXPLAIN   per-hotel matched/missing facets; "4 of 5, missing X"
```

## Decisions

- **Resolve once, at write time.** State stores bound records, never user words.
  This is the root fix for F1 and it is what makes `drop` reliable.
- **Reverse the prior plan's "no embeddings" call.** Deterministic scoring alone
  cannot reach "bãi đỗ xe" → `parking` (token overlap 2/3 scores 0.767, below the
  0.85 gate) or absorb qualifier drift like "wifi miễn phí". With 474 entries a
  vector index is ~3 MB and can live in process. Lexical scoring stays as the
  first and cheapest signal; embeddings are a *candidate generator*, never the
  sole decider.
- **Coverage is a first-class matching signal.** A candidate with zero hotels
  must never win against a positive-coverage candidate. A resolver able to return
  `wifi` (0 hotels) is broken by construction regardless of its similarity math.
- **Preferences carry polarity.** `require` / `exclude` / `prefer`. Only
  `require` and `exclude` are hard.
- **Hard filters degrade, they do not fail.** Returning "0 hotels" for a
  five-amenity request is a worse answer than "here are 4-of-5 matches, none has
  a spa". `NoHotelsMatchAmenities.tag_drop_counts` already computes what is
  needed to drive this; today it only phrases an apology.
- **Split the write paths.** Scraper discovery writes to staging with
  `is_approved=false`; only a reviewed promotion reaches the catalog chat reads.
- **Keep the deterministic regex rescues** (`_ground_sea_view`,
  `_ground_included_breakfast`). They are proven and cheap; retarget them to emit
  the new mention shape.

## Phase 0: Stop the silent losses

No schema change. Highest impact per unit of work; ship independently.

### Task 1: Make the amenity patch contract unambiguous

State the operation/type pairing explicitly in `prompts.py`, and normalize
defensively at the `extract_patch` boundary so a list-valued `append` becomes one
`append` per item rather than a dropped change.

**Acceptance criteria:**
- [ ] "Khách sạn có hồ bơi" commits `swimming_pool` to `travel_state` on turn 1.
- [ ] A list-valued `append`/`remove` is normalized, not rejected.
- [ ] The four multi-turn scenarios that lost turn 1 now retain it.

**Verification:**
- [ ] Replay the 22 single-turn and 7 multi-turn cases in this plan's corpus.

**Dependencies:** None.

### Task 2: Make patch rejection loud

`apply_patch` already returns `rejected`; nothing reads it. Log every rejected
change at WARNING with path, operation, and reason, and count them in the eval
metrics as `silent_drop_rate`.

**Acceptance criteria:**
- [ ] Every rejected change produces one structured log line.
- [ ] A rejected amenity change is visible in turn telemetry.

**Dependencies:** None.

### Task 3: Zero-coverage bind guard

Load a `{catalog_id: hotel_count}` map alongside the TTL-cached catalog. Demote
any candidate with zero coverage below every positive-coverage candidate.

**Acceptance criteria:**
- [ ] "wifi" no longer binds to the 0-hotel `wifi` entry.
- [ ] No user-reachable bind resolves to a zero-coverage ID.
- [ ] The map refreshes on the same TTL as `all_approved_amenities()`.

**Verification:**
- [ ] Assert every one of the 30 zero-coverage IDs is unreachable from a bind.

**Dependencies:** None.

### Checkpoint: Nothing is lost in silence

- [ ] No amenity a user states is dropped without either a bind, a surfaced
  "not supported" message, or a warning log.

## Phase 1: Catalog integrity

### Task 4: Add `parent_id` and seed the high-traffic families

The prior plan's Task 1, still unapplied. Nullable self-reference, indexed, with
a self-parent check. Seed the families the baseline shows are most broken:
parking, wi-fi/internet, pool.

**Acceptance criteria:**
- [ ] Every non-null `parent_id` references an existing ID; no self-parents.
- [ ] `free_parking`, `on_site_parking`, `paid_parking`, `nearby_parking`,
      `valet_parking` → `parking`.
- [ ] `free_wi_fi`, `free_wi_fi_in_all_rooms`, `public_wi_fi`,
      `wireless_internet_access` → a reviewed wi-fi parent.
- [ ] No hotel or room ID changes.

**Dependencies:** None.

### Task 5: Merge the 27 duplicate-label groups

Explicit reviewed merge map, remapping hotel and room arrays in one transaction.
Ambiguous *related* facilities stay separate; only true synonyms merge
(`beauty_service`/`beauty_services`, `wi_fi_in_public_areas`/`public_wi_fi`,
`parking_outside_the_property`/`parking_outside_the_premises`).

**Acceptance criteria:**
- [ ] Every removed ID has a canonical replacement or had zero references.
- [ ] Zero hotel/room rows retain a removed ID.
- [ ] A normalized-`label_vi`-per-scope uniqueness constraint prevents recurrence.

**Verification:**
- [ ] Post-migration query returns zero removed-ID references.
- [ ] Duplicate-label group count is 0.

**Dependencies:** Task 4.

### Task 6: Quarantine zero-coverage entries

Flag the 30 unused entries for review: genuine long-tail, or scraper artifacts to
retire.

**Dependencies:** Task 5.

## Phase 2: The binder

### Task 7: Candidate generation — lexical ∪ semantic

Keep the existing normalized scoring as signal one. Add an embedding of each
entry (`label_vi` + `label_en` + keywords) held in process, refreshed with the
catalog TTL. `pgvector` is already installed if the index should live in the
database instead.

**Acceptance criteria:**
- [ ] "bãi đỗ xe" → `parking`; "dịch vụ làm đẹp" → the merged beauty entry.
- [ ] "wifi miễn phí" and "free wifi" → a positive-coverage wi-fi entry.
- [ ] A genuinely ambiguous phrase ("wireless internet") still returns ambiguous
      rather than guessing.
- [ ] Cold-start cost is one embedding pass over 474 rows, cached thereafter.

**Dependencies:** Task 6.

### Task 8: Rerank and decide

Combine lexical score, semantic similarity, and coverage prior. Accept on
threshold-plus-margin as before, but **tune both against the labeled corpus**
rather than by intuition.

**Acceptance criteria:**
- [ ] Thresholds are derived from corpus sweep, and the chosen values are
      recorded with their precision/recall.
- [ ] Result is `resolved` | `ambiguous(top-k, with evidence)` | `unresolved`.

**Dependencies:** Tasks 7, 14.

### Task 9: Resolve ambiguity instead of dropping it

The prior plan specified this and it was never wired into the chat path
(`resolve_hotel_amenity_ids` deliberately never calls a model). On `ambiguous`,
make one bounded fast-LLM call constrained to the top-k IDs; if it abstains,
emit a user-facing clarify chip. Never invent a catalog row from the chat path.

**Acceptance criteria:**
- [ ] The model can only return one of the supplied IDs, or nothing.
- [ ] An abstention produces a clarify chip, not a silent drop.
- [ ] The chat path still never creates a catalog entry.

**Dependencies:** Task 8.

## Phase 3: State model

### Task 10: Store bound preference records

`hotel_preferences.amenities` becomes a list of
`{id, label, polarity, source_phrase, confidence}`. `drop` and `clear` operate on
IDs. Requires a `travel_state` schema version bump and a read-through upgrade for
live sessions — `test_travel_state_read_through.py` is the existing precedent.

**Acceptance criteria:**
- [ ] "Khách sạn có bể bơi" then "Không cần hồ bơi nữa" leaves the slot empty.
- [ ] An in-flight session written under the old shape upgrades on read.
- [ ] `active_preferences` becomes a projection of state, not a recomputation
      inside `hotel_node`.
- [ ] An unresolved phrase is reported on the turn it is said, then discarded.

**Dependencies:** Task 9.

### Task 11: Polarity through to the query

`exclude` and `prefer` reach the query planner.

**Acceptance criteria:**
- [ ] "không cần hồ bơi" records an `exclude`, or clears a prior `require`,
      and never errors on an empty slot.
- [ ] `prefer` never removes a hotel from the result set.

**Dependencies:** Task 10.

## Phase 4: Query planning

### Task 12: Descendant expansion

A `require` on an ID matches that ID or any descendant. A specific request never
expands to its parent or siblings.

**Acceptance criteria:**
- [ ] A hotel with `free_parking` satisfies `parking`.
- [ ] A hotel with only `parking` does not satisfy `free_parking`.
- [ ] "wifi" matches the ~700+ hotels that have some wi-fi entry, not zero.
- [ ] No cross-scope leakage between hotel and room scopes.

**Dependencies:** Tasks 4, 11.

### Task 13: Relaxation ladder

Run the full conjunction. If empty, drop the lowest-priority / least
discriminative `require` and retry, recording what was relaxed. Return labeled
partial matches instead of an empty set. Reuse the existing drop-count machinery.

**Acceptance criteria:**
- [ ] The five-amenity request returns ranked partial matches with an explicit
      "missing: spa" rather than "không tìm thấy khách sạn".
- [ ] The reply names exactly which preference was relaxed.
- [ ] A single-amenity request with genuine zero results still says so plainly.

**Dependencies:** Task 12.

### Task 14: Simplify the compare step

All 1104 hotels store canonical IDs, so remove the dead keyword-substring
fallback in `hotel_matches_amenity_tag`. Separately, decide one source of truth
for the two bypasses: 15 hotels carry the `sea_view` ID yet the code ignores it
in favour of a `rooms.view` lookup, and 228 carry `breakfast` while the code
reads `covered_meals`.

**Acceptance criteria:**
- [ ] The fallback path is deleted, with a guard test asserting no
      non-canonical values exist.
- [ ] `sea_view` and `breakfast` each have one documented source of truth.

**Dependencies:** Task 12.

## Phase 5: Governance and evaluation

### Task 15: Labeled corpus and metrics

Build this early — it gates Task 8. Roughly 200 `message → expected {id, polarity}`
pairs, seeded from the 29 cases already replayed in this plan, extended with real
user messages and per-family variants.

Metrics: bind precision/recall, `silent_drop_rate`, `unresolved_rate`,
`zero_result_rate`, and end-to-end "returned ≥1 hotel that truly holds every
required ID".

**Acceptance criteria:**
- [ ] The corpus runs offline against a catalog snapshot, no live LLM required
      for the matcher-only metrics.
- [ ] Thresholds in Task 8 cite corpus numbers.
- [ ] CI fails on a regression in bind precision or silent-drop rate.

**Dependencies:** None — start immediately, in parallel with Phase 0.

### Task 16: Separate discovery from the live catalog

Scraper discovery writes staging rows with `is_approved=false`; a reviewed
promotion step moves them into the catalog. Add the uniqueness constraint from
Task 5 as the structural backstop.

**Acceptance criteria:**
- [ ] No pipeline path writes `is_approved=true` without review.
- [ ] Re-running the scraper on known data creates zero new duplicates.

**Dependencies:** Task 5.

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Embeddings introduce confident wrong binds | They only *generate* candidates; the lexical score, coverage prior, and margin gate still decide. Corpus precision is the gate. |
| The state migration breaks live sessions | Version the schema and upgrade on read, following the existing read-through precedent; keep the old shape readable for one release. |
| Relaxation hides a real "no such hotel" answer | Always name what was relaxed; never relax a single-preference request. |
| Descendant expansion over-matches | Expansion is one-directional (specific satisfies general, never the reverse) and seeded only from reviewed parent links. |
| The merge migration loses a distinct facility | Merge only reviewed exact-synonym pairs; related-but-distinct rows stay separate. |
| Catalog embedding cost at cold start | 474 rows, one pass, cached on the existing TTL. |

## Out of scope

- Frontend amenity display redesign, beyond consuming the richer
  `active_preferences` projection.
- Room-scope preference extraction from chat (hotel scope only here).
- Replacing the hotel search RPC's semantic ranking.
- Automatically merging shared-keyword groups without review — unchanged from the
  prior plan, and the 237 collisions are evidence for why.
