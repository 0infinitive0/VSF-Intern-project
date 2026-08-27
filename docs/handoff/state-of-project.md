# State of the Project

Plain-language snapshot for whoever picks this up next. **Draft** — the outgoing team
should correct the facts and own § 5 (priorities) and § 6 (recommendation).

_As of 2026-08-27._

---

## 1. What it is

A multi-turn AI trip-planning chat for Vietnamese travellers (VI/EN). The user
converses; the system collects requirements, does semantic search over a real hotel /
attraction catalog, builds a distance-and-time-optimized itinerary, supports real room
booking + VNPay payment + email confirmation, and can finalize a plan into a reusable
template.

Stack: React 19 + Vite 8 frontend, FastAPI backend with a 14-node LangGraph
orchestrator, Supabase (Postgres + pgvector + Auth + Storage), Qdrant for hotel/attraction
vectors, Airflow for the data pipeline, Cloudflare Workers AI for LLM + embeddings.
Deployed as Docker Compose on a single EC2 host behind Caddy.

## 2. What works (shipped, on `main`)

- **Chat planning end to end:** intake → hotel search/filter → hotel pick → full
  itinerary build → in-conversation edits → budget check → finalize.
- **Deterministic guarantees:** every hotel/venue is a real DB row; replies carrying
  numbers come from templates, not the LLM; grounding + node contracts enforced.
- **Booking:** room hold (15-min TTL) → VNPay payment (sandbox) → IPN confirmation →
  Brevo confirmation email → finalize gated on a confirmed booking.
- **Auth:** Supabase anonymous JWT for every visitor; per-user chat history; ownership
  checks (404-not-403) — behind `AUTH_REQUIRED=false` so it's shipped but not yet
  enforcing.
- **Admin console:** hotels/rooms/prices/destinations/amenities CRUD, orders, embedding
  coverage + re-embed, Airflow pipeline trigger, audit log. Separate SPA.
- **Data pipeline:** Agoda + Booking crawl → normalize → load (~1,100 hotels / ~6,400
  rooms as of the last verified run). Attraction data via Google Places (PoC).
- **Eval harness:** RAGAS-based, two layers (retrieval + e2e). As of 2026-08-20 the e2e
  suite passes 9/9 expected stages.
- **Streaming:** SSE chat with phase/delta/reasoning/final/suggestions frames.

## 3. What's partial or not done

- **CLI (`poc_trip_planner`) is broken** — imports deleted code. Web UI only.
  ([known-issues](../known-issues.md) #1)
- **Out-of-scope guardrail not built** — math/code/flight questions reach the LLM. (#10)
- **No cron to expire holds** — manual admin sweep only. (#11)
- **`AUTH_REQUIRED` still `false`** — flip once the frontend sends the header everywhere.
- **No monitoring/alerting**, no CONTRIBUTING.md, no `LICENSE` file, no KPI/go-no-go
  report, no test-coverage snapshot. ([known-issues](../known-issues.md) #13–15)
- **Migrations folder is not a complete history** — some were applied straight on
  Supabase. (#9)
- **`turn cancellation` (the "Dừng" button)** was descoped. (#16)
- **First parallel worker fan-out will lose data** without a state reducer — not a
  problem today (sequential), a landmine for the next contributor. (#4)

## 4. Where to look first

| To understand… | Read |
|---|---|
| The whole system | [`../../ARCHITECTURE.md`](../../ARCHITECTURE.md) |
| The agent turn-by-turn | [`../architecture/langgraph_orchestrator_vi.md`](../architecture/langgraph_orchestrator_vi.md) |
| What the bot actually does | [`../architecture/chatbot-capabilities-and-happy-path-vi.md`](../architecture/chatbot-capabilities-and-happy-path-vi.md) |
| Deploy / operate | [`../ops/deployment-runbook.md`](../ops/deployment-runbook.md) |
| Everything that's wrong | [`../known-issues.md`](../known-issues.md) |

Historical docs (safe to ignore for current behavior): `agent_workflow_and_semantic_search_stack*.md`
(the old terminal POC), `design_proposal.md` (pre-build), `slide/ANSWERS.md` (defense prep),
`archive/`.

## 5. Suggested next steps — _outgoing team to prioritize_

Candidates (order them, add owners, cut what's not wanted):

- Fill the infra/access inventory and rotate secrets (**blocks a clean handoff**).
- Decide the CLI's fate (port to `build_graph` or delete).
- Write the KPI / go-no-go report from eval numbers (BR-09).
- Add `LICENSE` + a CONTRIBUTING.md + a coverage snapshot.
- Flip `AUTH_REQUIRED=true` after verifying frontend header coverage.
- Add a hold-expiry cron and basic uptime/error monitoring.
- Add the state reducer before anyone builds parallel workers.
- Build the out-of-scope guardrail (or formally accept the gap).

## 6. Go / no-go recommendation — _outgoing team to write_

`⟨One paragraph: is the PoC a success against BO-01…BO-05? Recommend continue / pivot /
stop, with the two or three reasons that matter most.⟩`

## 7. People

See [`../ops/infrastructure-and-access.md`](../ops/infrastructure-and-access.md) § 7 —
`⟨fill in who built which part and who to ask⟩`.
