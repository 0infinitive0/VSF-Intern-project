# Implementation Plan: Scored Amenity Preference Matching

## Overview

Replace first-match amenity lookup with a deterministic score-based resolver
for Vietnamese and English user preferences. The resolver chooses a catalog ID
only when the best compatible candidate is strong and clearly better than the
runner-up. It expands a general amenity (for example `parking`) to its more
specific children only when querying hotels; it never silently converts a
specific user request into the general ID.

## Decisions

- Keep `match_keywords` as a `TEXT[]` column; no JSONB is required.
- Resolve user text in Python after loading the small approved catalog. This
  avoids a per-preference database fuzzy-search query and keeps scoring rules
  testable.
- A keyword may belong to multiple amenities. It contributes to scoring but is
  never by itself an automatic resolution when the top two candidates are too
  close.
- Add nullable `parent_id TEXT REFERENCES amenity_catalog(id)` for query
  expansion only. It represents "specific satisfies general":
  `free_parking`, `on_site_parking`, `paid_parking`, `nearby_parking`, and
  `valet_parking` have parent `parking`.
- Use a controlled catalog-review process for duplicate cleanup. Do not merge
  entries merely because they share a broad keyword such as `spa`, `parking`,
  or `cctv`.

## Matching contract

Normalize input by Unicode case-folding, removing Vietnamese diacritics for
comparison, and treating punctuation/hyphens as spaces. Preserve the original
text for audit output.

For every compatible catalog entry, compare the normalized user phrase against
its ID, Vietnamese label, English label, and keywords. The score is the best
applicable signal:

| Signal | Score |
| --- | ---: |
| Exact normalized ID, label, or keyword | 1.00 |
| Exact multi-word phrase contained in the request | 0.92 |
| All significant tokens of a catalog phrase appear in the request | 0.86 |
| Token-overlap similarity | 0.60–0.85 |
| Typo-tolerant fuzzy similarity | at most 0.80 |

Resolve automatically only when the top score is at least `0.85` and exceeds
the second-best score by at least `0.15`. Otherwise return an ambiguous result
containing the best candidates; the caller can ask the fast LLM to disambiguate
from that bounded list or leave the preference unresolved.

Examples:

- `khách sạn có đỗ xe` → `parking`.
- `có chỗ đỗ xe miễn phí` → `free_parking`.
- `có ATM` is ambiguous until catalog policy chooses whether general ATM means
  `atm_on_site` or asks a clarifying question; it must not select a row based
  on an arbitrary database order.

## Phase 1: Catalog relationship and audit migration

### Task 1: Add `parent_id` and catalog integrity checks

Add the nullable self-reference, index it, and add a check preventing an entry
from being its own parent. Seed only reviewed parent links, starting with the
parking family.

**Acceptance criteria:**

- [ ] `parent_id` references an existing catalog ID or is null.
- [ ] `parking` children are linked to `parking`.
- [ ] Existing catalog entries remain readable and no hotel/room IDs change.

**Verification:**

- [ ] Migration applies to Supabase.
- [ ] Query confirms every non-null parent exists and no row points to itself.

**Dependencies:** None.

### Task 2: Produce a duplicate-keyword audit report

Create a read-only CLI/report that groups keywords shared by multiple
compatible catalog rows and labels each group as exact duplicate candidate,
parent/child overlap, or ambiguous.

**Acceptance criteria:**

- [ ] The report includes keyword, IDs, labels, scopes, and reference counts.
- [ ] It never deletes or modifies catalog rows.
- [ ] It flags broad words such as `parking`, `spa`, and `cctv` as ambiguous.

**Verification:**

- [ ] Run against the current catalog and save the report outside version
  control.

**Dependencies:** Task 1.

## Phase 2: Deterministic resolver

### Task 3: Add scored matching result types and pure scoring function

Implement a pure resolver returning `resolved`, `ambiguous`, or `unresolved`,
including candidate IDs, scores, and matched evidence.

**Acceptance criteria:**

- [ ] Exact Vietnamese and English aliases resolve without an LLM call.
- [ ] `chỗ để xe` and `đỗ xe` resolve to `parking`.
- [ ] Generic shared keywords do not resolve on a tie or near-tie.
- [ ] Results preserve the source preference order.

**Verification:**

- [ ] Unit tests cover exact, token-overlap, typo, ambiguity, scope, and
  ordering cases.

**Dependencies:** Task 1.

### Task 4: Replace first-match binding with scored resolution

Use the resolver in `bind_amenities` and hotel-preference extraction. Keep the
LLM bounded: provide only unresolved/ambiguous raw values plus their top
catalog candidates, and require it to select an existing ID or return no
match. New catalog creation remains an explicit last resort.

**Acceptance criteria:**

- [ ] An existing matching catalog ID is reused instead of creating a synonym.
- [ ] Shared keywords alone cannot trigger a random first-row choice.
- [ ] Model output cannot invent an existing-ID mapping outside the supplied
  candidate IDs.

**Verification:**

- [ ] Focused catalog, hotel-selection, and backfill tests pass.
- [ ] Test confirms `internet service` selects existing `internet` when its
  aliases score sufficiently.

**Dependencies:** Task 3.

### Checkpoint: Resolver safety

- [ ] No duplicate creation occurs for known aliases or strong scored matches.
- [ ] Ambiguous examples have a visible, auditable result rather than an
  arbitrary binding.

## Phase 3: Filtering expansion

### Task 5: Expand general preferences to descendants during hotel filtering

When a resolved preference has children, query using the requested ID plus all
descendant IDs. A specific preference stays specific and does not expand to its
parent or siblings.

**Acceptance criteria:**

- [ ] A hotel with `free_parking` satisfies `parking`.
- [ ] A hotel with only `parking` does not satisfy `free_parking`.
- [ ] Expansion works for hotel and room scopes without cross-scope leakage.

**Verification:**

- [ ] Hotel-selection tests cover general and specific parking requests.

**Dependencies:** Tasks 1 and 4.

## Phase 4: Review and controlled cleanup

### Task 6: Review duplicate report and apply explicit merge map

Approve a small mapping of true synonyms, remap hotel/room arrays in one
transaction, merge aliases into the canonical row where appropriate, and delete
only reviewed redundant IDs.

**Acceptance criteria:**

- [ ] Every removed ID has a canonical replacement or zero references.
- [ ] No hotel/room row retains a removed ID.
- [ ] Ambiguous related facilities remain separate.

**Verification:**

- [ ] Post-migration query returns zero removed-ID references.
- [ ] Catalog count and merge audit are recorded.

**Dependencies:** Tasks 2 and 5.

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| A generic keyword matches several amenities | Require score margin; return ambiguity instead of choosing by query order. |
| A specific facility is merged into a general one | Use only explicit reviewed merge maps and preserve parent-child relations. |
| Fuzzy matching causes false positives | Cap fuzzy score below the automatic threshold unless reinforced by token evidence. |
| New backfill recreates synonyms | Score against approved catalog first; LLM may select existing candidates before proposing a new row. |

## Out of scope

- Frontend amenity display redesign.
- Semantic-vector search or embeddings; the catalog is small enough for local
  deterministic scoring.
- Automatically merging all current shared-keyword groups without review.
