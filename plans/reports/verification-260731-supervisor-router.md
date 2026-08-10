# Verification: Supervisor ReAct Router (Phase 4)

Plan: `260731-1508-supervisor-react-router-for-chat-turn`. Measured 2026-07-31
against a live local Ollama and the live destination table (Nha Trang, Hà Nội,
Đà Nẵng, Huế, Hồ Chí Minh). Model/hardware: whatever `get_settings().llm_model`
resolves to on this developer machine (`llama3.1` unless overridden) — not
representative of any other environment; re-measure before trusting these
numbers elsewhere.

## Scenario table (regex label vs. supervisor label vs. expected)

| Message | Expected | Regex label | Supervisor label | Result |
|---|---|---|---|---|
| "đi Đà Nẵng 3 ngày 2 người" | new_trip | new_trip | **intake** | Supervisor wrong |
| "đổi khách sạn ngày 2" | edit_draft | edit_draft | edit_draft | Both correct |
| "3" (list pending) | select_hotel | select_hotel | select_hotel | Both correct |
| "chốt lịch trình" (list pending) | finalize | select_hotel* | finalize | Supervisor correct, regex needs a fall-through hop |
| "thêm quán cà phê ngày 2" (list pending) | edit_draft | select_hotel* | edit_draft | Supervisor correct, regex needs a fall-through hop |
| "sau 20h tôi không muốn đi đâu nữa" | edit_draft | edit_draft | **chat** | Supervisor wrong |
| "tôi muốn đi Hội An" (unsupported city) | new_trip† | edit_draft† | **intake** | Supervisor wrong, and riskier than a label mismatch (see below) |

\* `decide_route_by_rules` always answers `select_hotel` first when a list is
pending — by design (D1's stated risk). The actual escape from the trap
happens one level down, inside `process_chat_turn`'s `select_hotel` branch
body, after `select_hotel.invoke()` fails to resolve a pick and the list is
dropped; the turn is then re-routed. So the regex layer *reaches* the correct
final behavior, just via an extra hop — the raw label isn't the full story.

† `decide_route_by_rules`'s raw label for an unsupported city on a weak signal
is `edit_draft` (grounding finds no known match for "Hội An", so
`_new_trip_would_begin` is `False`). The **correct final behavior** — naming
the supported destinations instead of a generic "can't understand your edit"
reply — comes from `_unsupported_destination_reply`, which `process_chat_turn`
runs for **both** `new_trip` and `edit_draft` labels alike (see
`session.py`'s combined `if route in ("new_trip", "edit_draft")` gate). So the
regex layer's raw label doesn't match the table's "expected" column literally,
but the user-visible behavior is still correct.

**The supervisor's `intake` answer for this last scenario is not a label
quibble — it's a real regression risk.** `process_chat_turn` only runs the
saved-plan / unsupported-destination gate when `route in ("new_trip",
"edit_draft")`. If the supervisor's `intake` label is trusted, that gate is
skipped entirely: the turn falls straight into deterministic intake
(`session.intake_state.with_message(...)`), silently treating "Hội An" as a
fresh intake message instead of telling the user it isn't supported. This is
the concrete failure mode R1 anticipated when it noted D1 "accepts a real
regression risk" — except it fires on an *unsupported-destination* message,
not (only) the pending-hotel-list case R1 was written about.

## Accuracy summary

**Supervisor: 5/7 correct labels (71%), 2 wrong.** Regex: 7/7 correct **final
behavior**, but 2 of those require the documented fall-through hop rather than
a direct label. Per this phase's own three legitimate outcomes, this is
**outcome 3: the supervisor is worse** on this scenario set — it does add
real value on the "escape the pending-hotel trap" cases (the reason D1 exists
at all), but it also introduces a new failure mode regex didn't have.

## Latency

n=7, this session: regex avg ≈ 465ms, supervisor avg ≈ 579ms, **added ≈
114ms/turn**. (Regex's own ~465ms is dominated by the two weak-signal
scenarios that call the intake-extraction LLM themselves — see Phase 1
Deviations; it is not zero-cost either.) No latency budget was set by the
user for this phase — reported, not gated.

## R1 gate: hotel-pick gate holds (structurally, independent of routing)

```
Tools registered with the ReAct agent: {select_hotel, recommend_hotels, finalize_trip_plan, modify_trip_plan}
generate_full_itinerary reachable via any route: False
```

`generate_full_itinerary` is never registered with `create_react_agent`
(`src/agents/graph.py`'s `SessionTools`) — it is only reachable *through*
`select_hotel`. This holds regardless of which route the supervisor or the
regex fallback picks, because it is enforced at the tool-registration layer,
not the router. **R1 gate: holds**, independent of the supervisor's accuracy.

## Recommendation vs. decision made

This phase's own instruction for "supervisor is worse": default
`TRIP_SUPERVISOR_ROUTER` to `False` and report before any prompt-tuning loop.
That is the recommendation.

**The user was presented this finding and explicitly chose to keep the flag
on (`True`, the current default) despite the measured regression risk on
unsupported-destination messages with a saved plan.** This is a recorded user
decision overriding the plan's own default recommendation — not a silent
override. If this risk materializes in practice (a user with a saved plan
naming an unsupported city gets treated as if they were doing fresh intake
instead of being told which cities are supported), the fix is either:
narrowing the supervisor's `route_intake` tool description to exclude "message
mentions a saved-plan-adjacent request", or reverting to `False` via env var
(no deploy needed — D3's whole point).

## Scope note

This measurement used a synthetic 7-scenario fixture built from the cases
this codebase already documents as past bugs (per this phase's own
instruction), not a broad statistical sample. Treat the 71% figure as
indicative of a real, reproduced failure mode — not a precise accuracy rate.
