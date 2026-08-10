---
phase: 4
title: "Verify and document"
status: pending
priority: P2
effort: "0.5d"
dependencies: [3]
---

# Phase 4: Verify and document

## Overview

Measure whether the supervisor is actually better than the regex layer it sits
in front of, confirm the hotel-pick gate survives D1, and update the
architecture doc. This phase can conclude that the supervisor should stay off —
that is a legitimate outcome, not a failure.

## Requirements

**Functional**
- Routing accuracy measured against a labelled scenario set.
- Added latency per turn measured.
- Hotel-pick gate verified to hold under the supervisor (R1).
- `docs/architecture/agent_workflow_and_semantic_search_stack.md` updated.

**Non-functional**
- Measurements run against live Ollama on the developer's own hardware, with the
  model and machine recorded alongside the numbers.

## Architecture

**Scenario set.** Build a labelled fixture of Vietnamese messages paired with
the expected route, seeded from cases the codebase already documents as having
been bugs — these are the regressions that matter most:

| Message | Expected | Source of the case |
|---|---|---|
| `"đi Đà Nẵng 3 ngày 2 người"` | `new_trip` | `session.py:303` — must not read as "day 2" edit scope |
| `"đổi khách sạn ngày 2"` | `edit_draft` | `session.py:303` day-scope guard |
| `"3"` (list pending) | `select_hotel` | `session.py:355` bare number is always a pick |
| `"chốt lịch trình"` (list pending) | `finalize` | `session.py:470-477` escape from the trap |
| `"thêm quán cà phê ngày 2"` (list pending) | `edit_draft` | same trap |
| `"sau 20h tôi không muốn đi đâu nữa"` | `edit_draft` | `session.py:316-325` names no place |
| `"tôi muốn đi Hội An"` (unknown city) | `new_trip` | `_unsupported_destination_reply` |

Record, per scenario: regex label, supervisor label, expected label.

**Three outcomes are possible, and the phase must state which one occurred:**
1. Supervisor beats regex → keep the flag on by default.
2. Supervisor matches regex → keep it on only if latency is acceptable;
   otherwise the added call buys nothing and the honest result is to default it
   off and record why.
3. Supervisor is worse → default the flag off and report to the user before
   any prompt-tuning loop. Do not iterate silently on the prompt until the
   numbers look good.

**Latency budget.** Open question #2 in `plan.md` — the acceptable added
milliseconds per turn must come from the user. Measure first, then compare
against their number. Do not invent a threshold.

## Related Code Files

- Create: `tests/test_agents/test_supervisor_routing_accuracy.py`
- Create: `plans/reports/verification-260731-supervisor-router.md`
- Modify: `docs/architecture/agent_workflow_and_semantic_search_stack.md`
- Read only: `src/agents/supervisor.py`, `src/agents/routing_decision.py`

## Implementation Steps

1. Write the labelled scenario fixture from the table above; extend it with any
   additional cases found in the harness.
2. Run the set against the regex layer (flag off) and the supervisor (flag on);
   record both label sets.
3. Measure per-turn latency with the flag on and off, same hardware, same model.
   Record model name, machine, and sample count.
4. **R1 gate:** with a hotel list pending, verify the itinerary cannot be
   produced without a `select_hotel` resolution — attempt to route directly to
   `edit_draft`/`finalize` and confirm the plan is not generated. This is the
   guarantee `graph.py:30-38` protects by withholding `generate_full_itinerary`;
   D1 removed its deterministic pre-gate, so it must be proven empirically here.
5. Write the report: per-scenario table, latency numbers, R1 result, and an
   explicit recommendation on the default flag value.
6. Update the architecture doc:
   - Replace the "Intent routing" section (`## Agent workflow` → `### 2.`), which
     currently states the terminal loop calls the planner directly.
   - Update the "LangGraph tool orchestration vs. a fully bespoke loop"
     comparison table — its "Decision" row says the ReAct agent is used only for
     "chat and fallback paths", which this plan changes.
   - Note that the supervisor is the first delivered piece of the proposed
     5-agent architecture's "Agent 1: Gateway/Supervisor", and that the other
     four remain proposals.
7. Do **not** update the doc's model-responsibility table to imply the
   supervisor handles facts — it routes only.

## Success Criteria

- [ ] Scenario set covers all seven documented cases above
- [ ] Regex vs. supervisor labels recorded per scenario
- [ ] Latency measured with model and hardware recorded
- [ ] R1 gate result recorded — hotel-pick gate holds, or is reported broken
- [ ] Report written with an explicit default-flag recommendation
- [ ] Architecture doc updated in all three places listed
- [ ] `trip_intake.py` / `trip_scheduler.py` still zero-diff across the whole plan

## Risk Assessment

**Risk:** Temptation to tune the prompt until the scenario set passes, which
overfits to the fixture and hides real-world weakness.
**Mitigation:** Fix the fixture before the first supervisor run. If tuning
happens, add fresh unseen scenarios and re-measure; report both numbers.

**Risk:** Live-model measurements are not reproducible across machines, so the
recommendation may not transfer.
**Mitigation:** Record model, quantization, and hardware with every number.
Frame the recommendation as conditional on that setup.

**Risk:** The R1 gate check is the only empirical defense of a user decision
that removed a deterministic safety gate. Skipping it leaves D1 unvalidated.
**Mitigation:** Step 4 is a hard gate. If it cannot run against a live model,
the phase stays open — do not close it on stubs.

**Rollback:** Documentation and test-only phase; nothing to roll back.
