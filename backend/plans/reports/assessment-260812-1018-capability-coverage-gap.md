# Capability coverage audit — full requirement list vs code + plan

Date: 2026-08-12 · Branch: main · No code changed
Compared against: current `backend/src/`, plan `260812-0927-langgraph-orchestration-state-patch-and-interrupts`

Legend: ✅ plan covers · ⚠️ partial / unspecified · ❌ gap, nothing covers it

## Headline

The plan was built for 5 reported bugs. This list is **~3x wider**. Three findings change scope:

1. **Booking + "không cho người khác xem" is an explicit non-goal in the current plan.** It also
   requires a **user/ownership model that does not exist** — `SessionRegistry` is anonymous, there
   is no `user_id` anywhere. Privacy/locking is a bigger prerequisite than booking itself.
2. **"Tổng ngân sách dưới 3tr" is a different concept from every budget in the system today.**
   All existing budget handling is *per-night hotel price*. `_calculate_trip_budget` computes a trip
   total but never constrains one.
3. **The "không được phép" list has no mechanism at all.** `guardrails/jailbreak.py` blocks only
   prompt-injection, not out-of-scope requests. Math/code/flight requests reach `_run_chat_agent`
   and the LLM will most likely just answer them.

## A. Dates

| Case | Today | Plan | Verdict |
|---|---|---|---|
| `01/07` no year | LLM invents a year; `_format_start_date:591` accepts any parseable date | Phase 5 `interrupt()` asks the year | ✅ |
| `31/07` month/day order | `31` is not a valid month so DD/MM resolves by luck, not by rule | Phase 5 validators listed: missing year, past date, end ≤ start, implausible span | ⚠️ **order rule not stated** |
| `1-2-2026` | Ambiguous: 1 Feb or 2 Jan. Separator differs; no rule either way | Same as above — not covered | ⚠️ **same gap** |
| `1/7-7/7` outside data coverage | Date is valid, no `room_prices` rows → search returns empty → *"Không tìm thấy khách sạn có tọa độ hợp lệ"* | Phase 7 covers "zero results names the binding constraint" but only for amenity/radius | ❌ **no "valid date, no inventory" message** |

**Gap:** a date can be syntactically valid, temporally valid, and still have no data. That is a
third state the plan does not model. It is also the single most misleading error in the product
today, because the message blames coordinates.

## B. Itinerary editing

| Case | Today | Plan | Verdict |
|---|---|---|---|
| Ngày 1 chọn thiên nhiên khám phá | Theme discarded by `normalize_day_themes:534`; prompt collision at `trip_edit_planner.py:442`/`:445` | Phase 1 + Phase 3 | ✅ |
| Đổi địa điểm này sang địa điểm khác | `replace_item` works | — | ✅ |
| Đổi **nhiều** địa điểm | Multi-op allowed — only `change_hotel`/`update_trip_preferences` are exclusive (`:409-411`) | — | ✅ structurally |
| **Gợi ý địa điểm phù hợp** (đề xuất rồi mới chọn) | System replaces directly. There is no "here are 3 options, pick one" flow for places — only hotels have that | Not covered | ❌ **gap** |

## C. Hotel search filters

| Case | Today | Plan | Verdict |
|---|---|---|---|
| Search theo tiện ích | Soft ranking bonus only (`+0.03`), never a filter | Phase 7 hard filter | ✅ |
| **Kết hợp nhiều tiện ích** | `hotel_amenity_prefs.split(",")` — structurally multiple | Phase 7 | ⚠️ **AND vs OR semantics never stated** |
| "có gym", "có spa" | `_AMENITY_KEYWORD_TAGS` has 7 tags: non_smoking, pool, swimming_pool, wifi, parking, parking_lot, family. **No gym, no spa.** Only the dynamic `discover_and_store_amenities` path can learn them | Phase 7 assumes the taxonomy exists | ❌ **taxonomy gap** — doc §19 lists gym/spa as canonical |
| Bán kính 3km | Plumbed in `select_hotel_candidates:84-86`, never passed by `recommend_hotels` | Phase 7 + center = selected hotel | ✅ |
| **Đánh giá trên 4 sao** | `min_star_rating` exists (`supabase_search.py:214`) **but silently falls back to unfiltered semantic matches when nothing matches** (`:281`) | Not in `ALLOWED_PATHS` | ⚠️ **exists but unreliable + not in plan** |
| Sang trọng / bình dân | `_QUALITATIVE_BUDGET_PHRASES` covers luxury/budget/mid_range | — | ✅ |
| **"giá hợp lý"** | Not in the phrase list (has `vua tui tien`, `vua phai`, `tam trung`) | — | ⚠️ near-miss |

**Note on "4 sao":** `star_rating` (1–5) and `review_score` (0–10) are different columns.
"Đánh giá trên 4 sao" is genuinely ambiguous between them. Only `star_rating` is filterable today;
`review_score` is not filterable at all.

## D. Budget

| Case | Today | Plan | Verdict |
|---|---|---|---|
| Giá phòng/đêm | Full support: tiers, ranges, free-text parsing | Phase 2 `budget.min/max/target` | ✅ |
| **Tổng ngân sách dưới 3tr** | `_calculate_trip_budget:458` **computes** a total into `itinerary["budget"]`. Nothing ever constrains it | `ALLOWED_PATHS` has only per-night budget | ❌ **gap** |

This is not a small addition. A trip-total constraint has to feed back into hotel selection **and**
itinerary cost, then re-plan when violated — the doc's §18 "budget changed → hotel + itinerary"
loop. Phase 6's `IMPACT_MAP` is the right hook, but the constraint itself does not exist.

## E. Per-day itinerary constraints

| Case | Today | Plan | Verdict |
|---|---|---|---|
| Giới hạn N địa điểm/ngày (1, 10) | `planning_constraints` supports **only** `latest_outing_start_by_day`, `latest_outing_end_by_day`, `meal_preferences`, `meal_preferences_by_day` | Phase 6 adds `locked_days` only | ❌ **gap** |
| Các địa điểm gần nhau dưới 1km | Radius exists for *hotel search*; there is no inter-item distance constraint in scheduling | Not covered | ❌ **gap** |

Related: `MINIMUM_ITEMS_PER_DAY = 7` (`itinerary_reuse.py:19`) is a reuse-template quality gate, not
a scheduling rule — so it does not block "1 địa điểm 1 ngày", but it does mean a 1-item day can
never be reused as a template. Worth deciding deliberately.

## F. Places / restaurants

| Case | Today | Plan | Verdict |
|---|---|---|---|
| Tìm nhà hàng xung quanh | Restaurants exist **only** as fixed meal-slot queries inside itinerary building (`trip_planner.py:334-374`, `:642-678`). No standalone place-search tool | Not covered | ❌ **gap** |

Doc §22 names `search_places` / `get_place_details` as core tools. The project has neither as a
user-facing capability — only hotels are searchable on demand.

## G. Travel style

| Case | Today | Verdict |
|---|---|---|
| Đi chơi cùng người yêu | `_COMPANION_LABELS` includes "đi cùng người yêu hoặc vợ chồng"; flows through `_build_hotel_preferences` | ✅ |

## H. Booking & privacy — largest gap

| Case | Today | Plan | Verdict |
|---|---|---|---|
| Giữ chỗ khi đặt phòng (hold) | Nothing | **Declared non-goal** | ❌ |
| Sold out | Nothing | Non-goal | ❌ |
| Handoff booking | Nothing | Non-goal | ❌ |
| **Lock lịch trình, không cho người khác xem** | Nothing — and no user model to hang it on | Non-goal | ❌ **blocked on prerequisite** |

`grep` for booking/hold/reserve/sold_out/availability across `src/` returns **zero** functional hits.

The privacy requirement is the harder half. It presumes:
- authenticated users (none — `SessionRegistry` issues anonymous UUIDs)
- itinerary ownership (`itineraries` has no `user_id`)
- a sharing/visibility model (nothing)

Doc §6 assumes `trips.user_id NOT NULL` throughout. The project never adopted it. **Any locking or
"not visible to others" work is blocked until an auth + ownership model exists** — that is a
separate plan, not a phase.

## I. "Không được phép" — no mechanism exists

| Case | Today | Verdict |
|---|---|---|
| Từ chối yêu cầu giải toán / code | Nothing | ❌ |
| Từ chối đặt vé máy bay | Nothing | ❌ |

`guardrails/jailbreak.py` blocks exactly four things: role spoofing, prompt exfiltration,
instruction override, jailbreak persona (`:56-69`). Scope refusal is a **different** control and is
absent. Today these requests fall through to `_run_chat_agent`, where a general-purpose LLM will
very likely answer them — the supervisor prompt never says "refuse out-of-scope".

Cheapest correct fix: a scope classifier in the same guardrail layer, plus an explicit refusal
clause in `SUPERVISOR_PROMPT`. Defence in depth, mirroring the existing jailbreak shape.

## Coverage summary

| Bucket | Count |
|---|---|
| ✅ Plan already covers | 7 |
| ⚠️ Partial / semantics unspecified | 6 |
| ❌ Real gap, nothing covers it | 9 |

## Recommended plan changes

**Amend existing phases (cheap):**

| Phase | Amendment |
|---|---|
| 2 | Add `budget.trip_total`, `hotel_preferences.min_star_rating`, `constraints.max_items_per_day`, `constraints.max_item_distance_km` to `ALLOWED_PATHS` |
| 5 | Add day/month-order ambiguity + "valid date, no inventory data" to the validator list |
| 7 | State AND/OR semantics for multi-amenity; seed gym/spa/restaurant into the canonical taxonomy; make `min_star_rating` a hard filter (kill the `:281` silent fallback) |
| 6 | `IMPACT_MAP` must route `budget.trip_total` → both hotel and itinerary |

**New phases required:**

| # | Phase | Why it cannot be an amendment |
|---|---|---|
| 9 | Scope guardrail (refuse math/code/flights) | New control type; independent of everything else. **Small — do it early** |
| 10 | Per-day itinerary constraints (count, inter-item distance) | New constraint family in the scheduler, not the orchestrator |
| 11 | Standalone place search + "suggest options before replacing" | New user-facing tool surface (doc §22) |
| 12 | Trip-total budget constraint + re-plan loop | Constraint→replan feedback loop; depends on 6 |

**Separate plan (blocked):**

| Plan | Blocker |
|---|---|
| Auth + itinerary ownership | Prerequisite for *any* privacy/locking work |
| Booking (hold / sold-out / handoff) | Depends on auth, plus an inventory source the project does not have |

## Unresolved questions

1. "Đánh giá trên 4 sao" — `star_rating` (1–5) or `review_score` (0–10)? They are different columns.
2. Multi-amenity: AND (all must match) or OR (any)? AND is the literal reading of "kết hợp" and is
   what I would default to, but it will return zero results often on this dataset.
3. "1-2-2026" — commit to a fixed DD-MM-YYYY rule, or `interrupt()` and ask every time?
4. "Giữ chỗ / sold out" — is there a real inventory/availability source, or is this simulated?
   Without a real source, booking cannot be built honestly.
5. Does the product actually need multi-user auth now, or is "không cho người khác xem" satisfied by
   the existing per-session isolation (nobody can see another session's plan today anyway)?
6. `MINIMUM_ITEMS_PER_DAY = 7` vs "1 địa điểm 1 ngày" — keep the reuse gate and accept that sparse
   days are never reusable as templates?
