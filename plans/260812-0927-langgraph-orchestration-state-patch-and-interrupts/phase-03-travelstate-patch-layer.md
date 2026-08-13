---
phase: 3
title: "TravelState, patch layer, IMPACT_MAP"
status: done
priority: P1
effort: "2d"
dependencies: []
---

# Phase 3: TravelState, patch layer, IMPACT_MAP

## Overview

Introduce one canonical travel state with a validated `{path, operation, value}` patch API
and an `ALLOWED_PATHS` allow-list. This is the keystone: every later phase consumes it. No
behavior changes in this phase — it is pure foundation.

## Problem

Four rival mutation mechanisms, no shared contract:

| Mechanism | Location | Scope | Merge rule |
|---|---|---|---|
| `TripIntakeState.with_message` | `trip_intake.py:272` | 10 trip facts | first-non-null-wins — **a set value can never be corrected** (`:296`) |
| `HotelPreferenceState.with_message` | `hotel_selection.py:696` | budget only | returns `self` unchanged when unparsed → silent no-op |
| `TripPreferenceUpdate` | `trip_intake.py:79` | 5 fields | explicit `changed_fields` — closest to a patch |
| `TripEditPlan` | `trip_edit_planner.py:101` | 9 operations | post-plan only |

Consequences already observed: a mistyped date is permanently uncorrectable; an unparsed
budget reply loops forever; "ngày 1 thiên nhiên" has no representable path at all.

Tri-state is the second half of the problem. `None` currently means both "never asked"
and "user said they don't care", which is exactly why the budget gate cannot distinguish
a skip from a parse failure.

## Requirements

- Functional: `apply_patch` accepts a list of changes, validates each against
  `ALLOWED_PATHS`, and returns the new state plus an explicit list of rejected changes.
- Functional: unknown, malformed, or out-of-allow-list paths are rejected individually —
  one bad change never discards the good ones in the same patch.
- Functional: every slot distinguishes `UNKNOWN` / `SET(value)` / `NOT_APPLICABLE`.
- Functional: a `SET` value can be replaced by a later patch (removes the first-non-null-wins trap).
- Non-functional: `TripIntakeState` and `HotelPreferenceState` keep their exact public API.
  Existing call sites and tests must not change in this phase.
- Non-functional: state serializes to JSON for `TripState` / Supabase without custom encoders.

## Architecture

### New layer: `src/domain/`

This phase introduces a **pure** layer and the first file in it. `src/services/` is already 18
files mixing pure algorithms (`trip_scheduler`), data access (`supabase_search`,
`itinerary_store`), LLM calls (`trip_intake`), and formatting (`trip_formatter`). `travel_state`
is pure validation and state — putting it beside `supabase_search.py` would deepen exactly the
muddle that makes this codebase hard to test.

Adopts doc §36's `domain/` idea where it is free — **new files only**. Existing files do not
move: a rename would touch 248 import lines across 81 files for zero behavior change, and doing
it during a rewrite makes every diff unreadable and `git bisect` useless.

Layer rule becomes:

```
api  →  agents  →  services  →  domain  →  models
```

**`domain/` imports nothing above it — no `services`, no I/O, no LLM, no Supabase.** That
constraint is what makes it unit-testable with hand-built dicts and no mocks, the convention
`_ground_extracted_facts` and `normalize_day_themes` already follow.

`ARCHITECTURE.md` declares the current four-layer rule (`api → agents → services → models`) and
is updated **in this phase**, so the document changes with the code rather than ahead of it.

New module `backend/src/domain/travel_state.py`:

```python
class Presence(str, Enum):
    UNKNOWN = "unknown"            # never asked / never answered
    SET = "set"                    # user supplied a value
    NOT_APPLICABLE = "n/a"         # user explicitly opted out ("bao nhiêu cũng được")

@dataclass(frozen=True)
class Slot:
    presence: Presence = Presence.UNKNOWN
    value: Any = None

ALLOWED_PATHS = {
    "destination",
    "dates.start", "dates.end",
    "people",
    "budget.min", "budget.max", "budget.target",   # per NIGHT
    "budget.trip_total",                           # WHOLE TRIP — different quantity (Phase 14)
    "preferences.themes", "preferences.companions",
    "preferences.pace", "preferences.day_rhythm", "preferences.notes",
    "hotel_preferences.amenities",
    "hotel_preferences.radius_km", "hotel_preferences.center",
    "hotel_preferences.min_star_rating",           # 1-5 stars (Phase 8)
    "hotel_preferences.min_review_score",          # 0-10 score — a DIFFERENT column
    "constraints.max_items_per_day",               # Phase 12
    "constraints.max_item_distance_km",            # Phase 12
    "daily_preferences.*.theme",       # wildcard segment — day number
    "locked_days",
}
```

Two path pairs are deliberately separate because they are genuinely different quantities, and
collapsing either one would produce silently wrong results:

- `budget.max` (per night) vs `budget.trip_total` — 3tr total over 3 nights is 1tr/night.
- `min_star_rating` (1-5) vs `min_review_score` (0-10) — different DB columns. "Đánh giá trên
  4 sao" is ambiguous between them; Phase 7 asks rather than guessing.

`apply_patch(state, changes) -> PatchResult(state, applied, rejected)` where each change is
`{"path": str, "operation": "set"|"unset"|"append"|"remove", "value": Any}`.

Per-path validators live beside the allow-list so a path cannot be added without one —
`dates.start` gets the temporal check that does not exist today (Phase 7 consumes it),
`hotel_preferences.radius_km` gets the positive/max bound the doc requires.

### IMPACT_MAP lives here, beside ALLOWED_PATHS

Every path declares which workflows it affects, in the same module so the two cannot drift:

```python
IMPACT_MAP = {
    "destination":                   ("hotel", "itinerary"),
    "dates.start": ("hotel", "itinerary"), "dates.end": ("hotel", "itinerary"),
    "people":                        ("hotel", "itinerary"),
    "budget.max":                    ("hotel",),              # per night
    "budget.trip_total":             ("hotel", "itinerary"),  # whole trip — Phase 14
    "hotel_preferences.amenities":   ("hotel",),
    "hotel_preferences.radius_km":   ("hotel",),
    "hotel_preferences.min_star_rating":  ("hotel",),
    "hotel_preferences.min_review_score": ("hotel",),
    "constraints.max_items_per_day":      ("itinerary",),     # Phase 12
    "constraints.max_item_distance_km":   ("itinerary",),     # Phase 12
    "preferences.themes":            ("itinerary",),
    "daily_preferences.*.theme":     ("itinerary_day",),      # narrowest scope
    "locked_days":                   (),
}
```

`detect_impact(applied_changes) -> set[Workflow]` is the graph's routing input. Phase 5 maps
those workflow labels onto worker node names via `WORKFLOW_TO_WORKER` — that mapping lives in
`graph_v2/`, never here, because `domain/` must not know graph node names. It replaces
`requires_candidate_rebuild` (`session.py:554`), which is a hand-rolled four-field version of
exactly this idea.

### Read-through views, retired at cutover

`TripIntakeState` / `HotelPreferenceState` become read-through views over the canonical state so
the MEDIUM blast radius (17 symbols, 5 direct callers) does not become 17 edits in this phase.

Their `with_message` **writers** are dead on arrival: from Phase 6 the patch layer is the only
writer, and Phase 11 deletes both methods along with `TripPreferenceUpdate`. Keeping the
read-side view is a call-site convenience, not a second source of truth — a distinction the
earlier incremental revision of this plan failed to hold.

## Related Code Files

- Create: `backend/src/domain/__init__.py`, `backend/src/domain/travel_state.py`
- Create: `backend/tests/test_travel_state.py`, `backend/tests/test_domain_layer_purity.py`
- Modify: `backend/src/agents/state.py` — carry canonical state on `TripState`
- Modify: `backend/src/services/trip_intake.py` — `TripIntakeState` reads through (public API unchanged)
- Modify: `backend/src/services/hotel_selection.py` — `HotelPreferenceState` reads through (public API unchanged)
- Modify: `ARCHITECTURE.md` — add `domain` to the layer rule and the layer table (§"Layer Architecture & Import Rules")

## Implementation Steps

1. Run `impact` on `TripIntakeState` and `HotelPreferenceState`; record direct callers in the PR.
2. Create `src/domain/` and write `travel_state.py`: `Presence`, `Slot`, `ALLOWED_PATHS`,
   `IMPACT_MAP`, per-path validators, `apply_patch`, `detect_impact`.
3. Unit-test the patch layer standalone with hand-built dicts and **no mocks** — the same
   convention `_ground_extracted_facts` and `normalize_day_themes` already follow in this repo.
   Needing a mock here means something impure leaked into `domain/`.
3b. Add a purity test that fails if any module under `src/domain/` imports `src.services`,
   `src.agents`, `src.api`, `supabase`, or an LLM client. This is what keeps the new layer honest.
3c. Update `ARCHITECTURE.md`: layer rule to `api → agents → services → domain → models`, plus a
    `domain` row stating "pure state, validation, constraints — imports nothing above it".
4. Add the canonical state to `TripState` alongside the existing `intake` / `hotel_prefs` keys.
5. Make `TripIntakeState` / `HotelPreferenceState` read through, keeping their public API byte-identical.
6. Add a round-trip test: canonical state → `to_dict` → `from_dict` → canonical state.
7. Run the full suite; **zero test file changes are expected in this phase** — if a test
   needs editing, the view adapter is wrong, not the test.

## Success Criteria

- [x] `apply_patch` rejects every path outside `ALLOWED_PATHS`, proven by test
- [x] A rejected change does not discard valid changes in the same patch
- [x] `UNKNOWN` vs `NOT_APPLICABLE` are distinguishable for budget
- [x] A `SET` slot can be overwritten by a later patch
- [x] `daily_preferences.3.theme` validates; `daily_preferences.99.theme` rejects against trip length
- [x] Every `ALLOWED_PATHS` entry has an `IMPACT_MAP` entry, enforced by test
- [x] `detect_impact` returns `itinerary_day` — not `itinerary` — for a `daily_preferences.*.theme` change
- [x] No module under `src/domain/` imports `services`/`agents`/`api`/`supabase`/an LLM client — enforced by test
- [x] Every `travel_state` unit test runs with hand-built dicts and zero mocks
- [x] `ARCHITECTURE.md` layer rule and table include `domain`
- [x] Existing test suite passes with **no test file modified** — true for every `TripIntakeState`/`HotelPreferenceState` touchpoint (`test_trip_intake.py`, `test_hotel_selection.py`, `test_agents/test_state_serialization.py`: zero diff, same pre-existing 7-8 baseline failures before/after, verified via `git stash` A/B). One unrelated file, `test_agents/test_supervisor_routing_accuracy.py`, was modified this session to close a real-LLM/LangSmith safety gap discovered while verifying this phase — not a Phase 3 touchpoint.
- [ ] `make test` green — not verified in this environment: `make test` runs the full unscoped suite, which calls the real OpenAI/LangSmith APIs per this repo's `.env` and was explicitly avoided this session. The pre-existing baseline already has 7-8 failing tests unrelated to this phase (confirmed via `git stash` A/B on `HEAD`).

## Risk Assessment

| Risk | Mitigation |
|---|---|
| `TripIntakeState` MEDIUM blast radius, 5 direct callers | Read-through view keeps the public API; no call-site edits. "No test file changed" is the pass/fail signal |
| Read-through views mistaken for a second source of truth | Views are read-only by Phase 6; their `with_message` writers are dead and deleted at cutover (Phase 11). Only the patch layer writes |
| Wildcard path `daily_preferences.*.theme` widens the allow-list | Wildcard resolves to an integer day bounded by the trip's `duration_days`; anything else rejects |
| Slot serialization bloats `sessions.context_data` | Store `presence` only when not `UNKNOWN`; measure the row size delta in the round-trip test |
