---
phase: 6
title: "M2 gate — end-to-end integration"
status: pending
priority: P1
dependencies: [3, 4, 5]
effort: ""
---

# Phase 6: M2 gate — end-to-end integration

## Overview

Integrate the parallel tracks, execute the test scenarios, and produce the evidence M2 is accepted against (BRD §12: "Đánh giá KPI giữa kỳ"). This is a gate, not a build phase — if it discovers gaps, they are fixed in the owning phase.

> **Grounding evidence comes from the RAGAS harness.** The adversarial grounding test below is measured by `plans/260807-1400-ragas-rag-evaluation-harness/` (retrieval precision/recall + answer faithfulness), which writes to `eval/results/`. Run that harness rather than building a second measurement path here.

## Requirements

- Functional: full journey works end-to-end — query → results → refine → handoff — in Vietnamese and in English.
- Functional: ≥70% of Phase 4's scenario set reaches handoff (BO-04).
- Functional: adversarial grounding test passes (BR-07; BRD §11 requires this *before* any demo).
- Non-functional: mid-term KPI evidence in a form the mentor can accept.

## Architecture

**Three test dimensions, all required:**

1. **Journey completion (BO-04)** — execute Phase 4's scenario set, count how many reach handoff with context intact. The 70% threshold is a BRD number.
2. **Bilingual coverage (BR-10)** — every scenario in Vietnamese *and* English, plus explicit mixed-language cases. Mixed queries are the case most likely to break and the one the BRD names directly.
3. **Grounding adversarially (BR-07)** — deliberately provoke hallucination: ask for hotels in a city with no data, request amenities nothing has, ask about prices for unavailable dates. The correct behaviour is an honest "no data", never an invented answer. BRD §11 mandates "kiểm thử đối kháng trước demo".

The repo has `pytest` configured with `tests/test_agents/` and `tests/test_api/`, and a `Makefile` `test` target — extend those rather than introducing a second harness. `eval/` exists for evaluation evidence (Demo Day deliverable #10) and is currently near-empty.

**Report honestly.** BRD §11 explicitly requires the go/no-go report be truthful "kể cả khi kết quả tiêu cực". A gate that always passes tells the mentor nothing.

## Related Code Files

- Create: `tests/test_e2e/` — scenario-driven journey tests
- Create: `tests/test_agents/test_grounding.py` — adversarial cases
- Create: `eval/scenarios/` — scenario definitions (VI, EN, mixed)
- Create: `eval/results/m2-report.md`
- Modify: `Makefile` (e2e target), `.github/workflows/` if CI should run the subset

## Implementation Steps

1. **Integrate the tracks.** First real run of Phase 5's UI against Phases 3–4's live API. Expect contract drift despite the freeze; fix in the owning phase.
2. **Encode Phase 4's scenarios** as executable fixtures in `eval/scenarios/`, each with its language variant.
3. **Build the journey harness** driving conversations through to handoff and recording completion, turn count, and failure point.
4. **Run bilingual coverage** — every scenario both languages, plus mixed-language cases. Record per-language pass rates separately; an aggregate hides a language-specific failure.
5. **Run the adversarial grounding suite.** Any invented hotel, price, or amenity is a Phase 3 defect, not an acceptable result.
6. **Measure the BO-03 claim** — the BRD estimates under 5 minutes of conversation versus tens of minutes manual. Time the demo scenarios; report the real number.
7. **Write `eval/results/m2-report.md`**: completion rate against the 70% threshold, per-language rates, grounding results, timing, and known gaps.
8. **Fix or explicitly descope** whatever fails. Per the roadmap's descope order, filters go before grounding.

## Success Criteria

- [ ] Full journey works end-to-end through the real UI in both languages.
- [ ] ≥70% scenario completion, measured and recorded (BO-04).
- [ ] Per-language pass rates reported separately.
- [ ] Adversarial grounding suite passes with zero invented facts.
- [ ] Conversation duration measured against BO-03's under-5-minute claim.
- [ ] `eval/results/m2-report.md` exists and states failures plainly.
- [ ] Every gap either fixed or explicitly listed as descoped.

## Risk Assessment

- **Risk:** Integration surfaces contract mismatches late, consuming the sprint's remaining time.
  **Mitigation:** Phase 5 step 1's frozen contract, and step 1 here running as early as a thin path allows rather than waiting for both tracks to finish.
- **Risk:** The gate becomes a formality that passes everything.
  **Mitigation:** Adversarial tests are designed to fail a weak implementation; scenarios were written in Phase 4 before tuning. Report negative results — the BRD requires it.
- **Risk:** English-path failures hide behind an aggregate pass rate.
  **Mitigation:** Step 4 reports per-language rates separately.
- **Risk:** Fixing gate failures reopens Phases 3–5 with no time left.
  **Mitigation:** Step 8's descope order is decided in advance, so the cut is a known trade rather than a panic.
