---
phase: 2
title: "Semantic search foundation with Qdrant"
status: pending
priority: P1
dependencies: [1]
effort: ""
---

# Phase 2: Semantic search foundation with Qdrant

> **SUPERSEDED 2026-07-27** by `plans/260727-1113-qdrant-vector-store-correctness-and-hybrid-retrieval`.
> User decision. That plan delivers the collections, the indexing DAG task, the
> search service, and the bilingual probe set described below — but reverses
> three of this phase's decisions. The reversals are deliberate; recording them
> so nothing is lost silently:
>
> | This phase required | Superseding plan does | Status |
> |---|---|---|
> | SQL keyword-search fallback when Qdrant is down (`design_proposal.md` §4C, **BR-10**) | Not delivered | **Still owed.** BRD requirement — needs its own follow-up plan. |
> | Embedding model chosen on measured bilingual evidence ("this phase's most consequential decision") | Hardcodes `bge-m3` (already in the compose stack); model choice is an explicit non-goal | Accepted trade |
> | Qdrant joins `src/airflow/docker-compose.yaml` rather than the root compose | Hardens the root compose; joins both projects on a shared external network | Accepted trade |
>
> Do not implement this phase. Retrieval work belongs to the superseding plan.

## Overview

Stand up Qdrant, embed the hotel and attraction corpora, and expose a search service that answers natural-language queries in Vietnamese *or* English. This completes the BRD §13.2 L2 "chỉ mục vector" component and is the retrieval layer every later phase depends on.

## Requirements

- Functional: Qdrant running in `src/airflow/docker-compose.yaml` alongside Postgres.
- Functional: `hotels_vector` and `attractions_vector` collections, matching `data_dictionary.md` §2's existing specification.
- Functional: semantic search returns relevant results for a query in either language — **including a query in one language against corpus text in the other** (BR-10).
- Functional: SQL keyword-search fallback when Qdrant is unavailable (`design_proposal.md` §4C).
- Non-functional: embeddings computed once at index time, never per query, to respect the PoC API budget (BRD §10).

## Architecture

**Qdrant is the confirmed choice** (user decision, 2026-07-23), matching `design_proposal.md` and `data_dictionary.md` §2. It joins the existing Airflow compose stack rather than the orphan root `docker-compose.yml`.

**The embedding model is this phase's most consequential decision, and it is a bilingual one.** BR-10 requires that a Vietnamese query match English corpus text and vice versa — the two OTA sources supply descriptions in mixed languages. That demands a genuinely multilingual embedding model with a shared vector space, not an English-first model. Evaluate against the real corpus before committing; a model that scores well on English benchmarks may be weak on Vietnamese. Candidates worth measuring include multilingual-E5, and Gemini/OpenAI multilingual embedding endpoints. Record the comparison — this is exactly the kind of decision the M3 handover should be able to justify.

**Payload design matters for Phase 4.** Filters (price, star rating, amenities, area) can execute as Qdrant payload filters, as post-retrieval SQL, or as a hybrid. Decide here, because Phase 4's filter implementation depends on it. Given the schema work already invested in Postgres, prefer Qdrant for semantic ranking and Postgres for structured filtering, using vector search to produce candidate IDs.

## Related Code Files

- Modify: `src/airflow/docker-compose.yaml` (Qdrant service), `requirements.txt` (client + embeddings)
- Create: `src/services/vector_store.py`, `src/services/embeddings.py`, `src/services/search.py`
- Create: `src/airflow/dags/data_pipeline/embed_index_dag.py` (re-runnable indexing)
- Read only: `docs/data_dictionary.md` §2 (existing collection spec), `design_proposal.md` §4C (fallback spec)

## Implementation Steps

1. **Add Qdrant to the Airflow compose stack** with a named volume so the index survives restarts. Extend `docs/SETUP_GUIDE.md` — it is currently accurate and must stay that way.
2. **Evaluate embedding models on the real corpus.** Build a small bilingual probe set (~20 queries, VI and EN, including mixed-language) against known-correct hotels, and measure. Commit to a model on evidence, not reputation.
3. **Build the indexing DAG.** Compose each hotel's embedding text from name, description, amenities, and destination. Re-runnable and incremental — full re-embedding on every run wastes budget.
4. **Create both collections** per `data_dictionary.md` §2, carrying the payload fields Phase 4's filters will need.
5. **Implement `search.py`** with a clean interface (query text, language, filters, top-N) returning IDs plus scores. Phases 3 and 4 consume this; keep the surface small.
6. **Implement the SQL fallback** using Postgres full-text search, behind the same interface so callers need not know which path served the result. Log which path ran.
7. **Verify bilingual retrieval explicitly.** A Vietnamese query must find hotels described in English and vice versa. If this fails, the model choice in step 2 is wrong — return there rather than patching around it.

## Success Criteria

- [ ] Qdrant runs in the compose stack; `SETUP_GUIDE.md` updated and still accurate.
- [ ] Both collections populated from the Phase 1 corpus.
- [ ] Embedding model chosen with recorded bilingual evidence.
- [ ] Cross-language retrieval verified: VI query → EN-described hotel, and the reverse.
- [ ] Fallback path returns usable results with Qdrant stopped.
- [ ] Indexing DAG is re-runnable and incremental.

## Risk Assessment

- **Risk:** The chosen model handles Vietnamese poorly, quietly degrading every downstream phase.
  **Mitigation:** Step 2 measures before committing; step 7 gates on cross-language retrieval. This is the phase's real risk and the reason the probe set exists.
- **Risk:** Embedding cost overruns the PoC budget.
  **Mitigation:** Index-time-only embedding, incremental re-runs. ~1,100 hotels plus attractions is a small corpus; a self-hosted model removes the cost entirely if the API bill bites.
- **Risk:** Qdrant becomes a demo-day single point of failure.
  **Mitigation:** Step 6's fallback is a BRD-aligned mitigation already promised in `design_proposal.md` §4C — implement it now, not after it fails.
