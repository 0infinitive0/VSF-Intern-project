# Handoff Package

For the team taking over **VSF Trip Planner** after the internship (BRD **BR-08**).
Work top-to-bottom; each row links to the doc or names what's still needed.

---

## 1. Orientation

| Need | Where | Status |
|---|---|---|
| What the product is / quick start | [`../../README.md`](../../README.md) | ✅ |
| System architecture | [`../../ARCHITECTURE.md`](../../ARCHITECTURE.md) | ✅ |
| Local setup from a clean machine | [`../setup/SETUP_GUIDE.md`](../setup/SETUP_GUIDE.md) | ✅ |
| Documentation index | [`../README.md`](../README.md) | ✅ |
| Glossary | [`../glossary.md`](../glossary.md) | ✅ |
| State-of-project memo | [`state-of-project.md`](state-of-project.md) | ⚠️ draft — needs owner review + next-steps priority |

## 2. Build & run

| Need | Where | Status |
|---|---|---|
| Env-var reference (names/purpose/where to get — no values) | [`../setup/environment-variables.md`](../setup/environment-variables.md) | ✅ |
| The graph / agent | [`../architecture/langgraph_orchestrator_vi.md`](../architecture/langgraph_orchestrator_vi.md) (+ `_detail_vi.md`) | ✅ |
| API contract | [`../chat_api_contract.md`](../chat_api_contract.md) | ✅ |
| Auth model | [`../architecture/authentication.md`](../architecture/authentication.md) | ✅ |
| Admin API & console | [`../architecture/admin-api.md`](../architecture/admin-api.md) | ✅ |
| Booking + payment + email | [`../architecture/booking_and_payment_workflow_vi.md`](../architecture/booking_and_payment_workflow_vi.md) | ✅ |
| Data model | [`../architecture/database_erd.md`](../architecture/database_erd.md) · [`../architecture/data_dictionary.md`](../architecture/data_dictionary.md) | ✅ |
| Data pipeline | [`../architecture/data_pipeline_flow.md`](../architecture/data_pipeline_flow.md) | ✅ |
| Coding standards / branch + PR workflow | — | ❌ no CONTRIBUTING.md (README has a short "Đóng góp" note) |

## 3. Operate

| Need | Where | Status |
|---|---|---|
| Deployment + rollback + CI/CD + runbook | [`../ops/deployment-runbook.md`](../ops/deployment-runbook.md) | ⚠️ written; `⟨…⟩` host/domain fields need filling |
| Infrastructure & access inventory | [`../ops/infrastructure-and-access.md`](../ops/infrastructure-and-access.md) | ⚠️ template — needs account owners, project ids |
| Secrets register (names/locations only) | same file, § 2 | ⚠️ needs "who rotates / last rotated" |
| Backup & restore (Supabase PITR?) | runbook § 6 | ❌ needs answers |
| Monitoring & logging | runbook § 8 | ✅ documents current state (there is none beyond `/health`) |
| Scheduled jobs (Airflow DAGs) | runbook § 7 | ⚠️ needs the DAG inventory |

## 4. Quality

| Need | Where | Status |
|---|---|---|
| Eval / test strategy | [`../guide/eval-harness-testing-guide.md`](../guide/eval-harness-testing-guide.md) | ✅ |
| QA reports (persona runs) | [`../test-report/`](../test-report/) | ✅ |
| Known issues & tech debt | [`../known-issues.md`](../known-issues.md) | ✅ |
| Test coverage snapshot (pass rate, %) | — | ❌ run `cd backend && make test` + coverage and record |
| KPI / go-no-go report (BR-09) | — | ❌ not written; eval harness has the numbers |

## 5. Product & requirements

| Need | Where | Status |
|---|---|---|
| BRD (source) | [`../brd/BRD_V-OTA_AI-Chat_VSF2026_2.pdf`](../brd/BRD_V-OTA_AI-Chat_VSF2026_2.pdf) | ✅ |
| Requirements + fulfillment status | [`../design/brd-requirements-and-wireframe-prompts.md`](../design/brd-requirements-and-wireframe-prompts.md) | ✅ (status column added, confirm) |
| What the bot can/can't do + happy path | [`../architecture/chatbot-capabilities-and-happy-path-vi.md`](../architecture/chatbot-capabilities-and-happy-path-vi.md) | ✅ |
| Design proposal (original) | [`../design/design_proposal.md`](../design/design_proposal.md) | ✅ (banner notes divergence) |
| Wireframes | [`../design/`](../design/) | ✅ (source Figma access: `⟨fill in⟩`) |

## 6. Legal & data

| Need | Where | Status |
|---|---|---|
| `LICENSE` file | repo root | ❌ missing — needs copyright holder + year |
| Data-sourcing legal notes (OTA ToS, OSM/Places) | [`../architecture/data_pipeline_flow.md`](../architecture/data_pipeline_flow.md) § Legal + BRD BR-02 | ⚠️ constraints noted; no formal risk assessment |
| Third-party / OSS license inventory | — | ❌ run `pip-licenses` / `license-checker` |
| PII / data-retention note | — | ❌ (guest email/phone in `payments`; chat history in `sessions`/`chat_messages`) |

## 7. Transfer actions (at handoff)

- [ ] Fill every `⟨…⟩` in `ops/infrastructure-and-access.md` and `ops/deployment-runbook.md`.
- [ ] Transfer / add owners on every account in the inventory; rotate every secret; re-issue the EC2 SSH key.
- [ ] Add the new team as GitHub maintainers; hand over Actions secrets.
- [ ] Record a 20-30 min walkthrough (app demo + repo tour + one deploy).
- [ ] Confirm the requirement-status and BO tables with a stakeholder.
- [ ] Agree a post-handoff support window and who fields questions.
