---
phase: 8
title: "M3 — evaluation, handover, go/no-go"
status: pending
priority: P1
dependencies: [7]
effort: ""
---

# Phase 8: M3 — evaluation, handover, go/no-go

## Overview

Close the programme: full KPI evaluation, test report, handover package, and an honest go/no-go recommendation (BR-08, BR-09, BO-01, BO-05). **Documentation work starts in parallel with Phase 7**, not after it — only the final evaluation needs the finished product.

> **RAG quality numbers come from the RAGAS harness.** `plans/260807-1400-ragas-rag-evaluation-harness/` builds it and produces `eval/results/baseline.json` plus a report. Its Phase 5 proposes threshold candidates derived from the observed baseline — accepting or rejecting them is this phase's call, and Open Question 4 (KPI thresholds unset) is resolved here, not there.

## Requirements

- Functional: KPI evaluation against thresholds agreed at kick-off (BR-09).
- Functional: test report with known limitations (BRD §9).
- Functional: handover package sufficient for another team to take over (BR-08, BO-05).
- Functional: go/no-go recommendation with a next-phase roadmap (BO-01).
- Functional: the written legal/feasibility assessment BR-02 requires — implemented in code, never written up.
- Non-functional: all 10 Demo Day deliverables point at real content.

## Architecture

**This phase absorbs three known documentation debts:**

1. **`docs/legal_risk_assessment.md` does not exist** but is cited at `data_pipeline_flow.md:87` and required by BR-02. The *constraints are implemented* — `allow_ota_web_scraping` gating, `ScrapeBlockedError`, public-pages-only, no review text — and documented in `src/airflow/dags/data_pipeline/README.md`. The assessment writes up what was actually done and why, which is the BR-02 deliverable and materially informs go/no-go, since commercial scraping is the PoC's largest legal constraint.
2. **`plans/260723-0910-docs-consolidation-audit`** covers BR-08's doc accuracy. Run it before assembling handover — shipping the AI20K template README as deliverable #2 would be a poor final impression.
3. **`JOURNAL.md` and `WORKLOG.md`** are empty templates and are deliverables #8 and #9.

**KPI thresholds are unset** — BRD §3 and §9 defer them to kick-off. Roadmap Open Question 4. Resolve before evaluation, or report against the BRD's proposed thresholds (≥1,000 records, ≥70% handoff completion, under-5-minute conversations) and state that they were assumed.

**Honesty is a stated requirement**, not a stylistic preference: BRD §11 requires the report be truthful "kể cả khi kết quả tiêu cực". A recommendation that ignores what did not work is worth nothing to the investment decision it exists to inform.

## Related Code Files

- Create: `docs/legal_risk_assessment.md` (BR-02), `eval/results/m3-final-report.md`, `docs/known_limitations.md`, `docs/handover.md`, `docs/go-no-go-recommendation.md`
- Modify: `JOURNAL.md`, `WORKLOG.md` (deliverables #8, #9), `README.md`, `presentation/`
- Depends on: `plans/260723-0910-docs-consolidation-audit` completing first

## Implementation Steps

1. **Run the docs-consolidation plan to completion** if it has not already. Everything else here assembles documents that plan is correcting.
2. **Write `docs/legal_risk_assessment.md`** (BR-02): sources assessed, ToS/robots.txt position, implemented safeguards with code references, what was deliberately not collected (review text), and the production recommendation — official API or affiliate partnership, as `data_pipeline_flow.md` already states.
3. **Confirm KPI thresholds** with the mentor, or document the assumed ones.
4. **Run the full evaluation:** re-run Phase 6's suite against the finished product, add itinerary quality assessment, and measure every KPI.
5. **Write the test report** — coverage, pass rates per language, adversarial grounding results, performance.
6. **Write `docs/known_limitations.md`** honestly: no cross-OTA hotel dedup, desktop-only UI, no real booking engine, PoC-scale corpus, scraping not viable commercially, plus whatever Phase 6 descoped.
7. **Assemble the handover package** (BR-08, BO-05): setup instructions verified from a clean checkout, architecture docs, data-pipeline runbook, schema, credentials-handling notes.
8. **Backfill `JOURNAL.md` and `WORKLOG.md`**, marked as reconstructed where they are.
9. **Write the go/no-go recommendation** (BR-09, BO-01): what the PoC proved, what it did not, the cost and legal profile of productionising, and a clear recommendation with next-phase roadmap.
10. **Prepare demo materials** — the final demo must show all three capabilities per BRD §9: search, booking handoff, itinerary.
11. **Verify all 10 Demo Day deliverables** resolve to real content.

## Success Criteria

- [ ] `docs/legal_risk_assessment.md` exists, closing BR-02's documentation gap.
- [ ] Every KPI measured and reported against a stated threshold.
- [ ] Test report covers both languages and adversarial grounding.
- [ ] Known limitations documented without euphemism.
- [ ] Handover package verified by a clean-checkout setup run.
- [ ] `JOURNAL.md` and `WORKLOG.md` contain real content.
- [ ] Go/no-go recommendation is explicit and evidence-backed.
- [ ] Demo shows search, handoff, and itinerary.
- [ ] All 10 deliverables verified.

## Risk Assessment

- **Risk:** Documentation is deferred to the final days and rushed.
  **Mitigation:** Steps 1–2 and 6–8 do not depend on Phase 7 and should run in parallel with it. BR-08 makes documentation a per-sprint DoD constraint, not a final-week task.
- **Risk:** Thresholds were never set, so evaluation has no reference.
  **Mitigation:** Step 3, resolved early. Assumed thresholds are acceptable if labelled.
- **Risk:** Pressure to present a favourable result.
  **Mitigation:** BRD §11 requires honesty explicitly. A PoC that surfaces a real blocker — such as scraping being commercially non-viable — is a *successful* PoC; that is what "low-cost investment decision" means.
- **Risk:** Handover is written by people who no longer notice their own assumptions.
  **Mitigation:** Step 7 verifies setup from a clean checkout rather than a working machine. `SETUP_GUIDE.md` is currently accurate — keep it that way.
