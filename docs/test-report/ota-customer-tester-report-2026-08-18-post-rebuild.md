# OTA Customer Journey QA Report — Post-Rebuild Pass

**App tested:** http://localhost:5173/ ("V-OTA AI Travel Planner"), Docker images rebuilt from latest `main` (post-merge of PR #12, #13, #14, plus the concurrent session's room-hold/VNPay booking feature)
**Date:** 2026-08-18
**Purpose:** Fresh persona run against the newly rebuilt containers, specifically re-checking the previously-reported amenity-label bug and probing the new booking/room-hold flow.

## Persona & trip brief

**Who:** Minh (34) and his wife Thảo (32), from Hà Nội, celebrating their 5th wedding anniversary with a beach getaway in Đà Nẵng. Mid-to-high budget, tech-comfortable, want a sea-view room with breakfast, care about romantic atmosphere and genuine reviews.
**Trip:** Đà Nẵng, 3–7 Jul 2026 (4 nights), 2 guests, budget ₫1.5–3,000,000/night, priorities: sea view, breakfast, culture, high reviews.

## Step-by-step timeline

| Step | What happened | Time taken | Status |
|---|---|---|---|
| Landing | Clean load, no console errors | ~2s | smooth |
| Search (free-form sentence) | Destination, dates, guests, and budget all parsed correctly from one sentence; 5 hotels found | ~10s | smooth — see Errors #2 |
| Direct question about a named hotel | Reinterpreted as a new search instead of being answered | ~8s | broken — see Errors #3 |
| Follow-up ambiguous question | Triggered a disambiguation reply AND an unexpected revert to Step 1 asking for "Sở thích" | ~14s | broken — see Errors #4 |
| Recovery (explicit "remove sea view" message) | Recovered cleanly, 14 hotels, no stuck note this time | ~9s | smooth |
| Browse & select hotel | Hotel detail panel, room list, all labels in Vietnamese | ~10s | smooth |
| Room hold → itinerary build | "Giữ phòng" auto-selected the hotel and built a full 4-day themed itinerary in one step | ~12s | smooth |
| Day 1 timeline | "Bắt đầu từ DLG Hotel Danang" / "Kết thúc tại DLG Hotel Danang" bookends rendered correctly | n/a | smooth |
| Navigate back to "2 Khách sạn" step | Amenity tags reverted to raw IDs (swimming_pool, spa, wheelchair_accessible_entrance, airport_shuttle) | n/a | **broken — see Errors #1** |

## Errors encountered

1. **[HIGH] Amenity labels revert to raw IDs after selecting a hotel via the new room-hold flow, then navigating back to the hotel step.** Immediately after searching, hotel cards showed correct Vietnamese labels ("Nhìn ra biển", "Hồ bơi", "Gói spa/chăm sóc sức khỏe"). After picking a room and completing "Giữ phòng" (which auto-selects the hotel and builds the itinerary), clicking back to the "2 Khách sạn" step tab shows the exact same hotel cards now labeled with raw canonical IDs: `swimming_pool`, `spa`, `wheelchair_accessible_entrance`, `airport_shuttle`. This is the same symptom as the original QA report bug, but triggered via the new "Giữ phòng"/room-hold selection path rather than the "đổi khách sạn" button — a path that didn't exist when the earlier fix (un-gating `hotel_amenities` from `stage` in `respond.py`) was made and verified. Root cause not yet isolated — worth checking whether the room-hold/select flow's response path (likely `POST /hotels/select` → `_run_turn_via_graph` with `selected_hotel_id`, which routes to `itinerary_node` rather than `hotel_node`) populates `hotel_amenities` the same way `respond()` does for a hotel-search turn, or whether the frontend is holding onto a stale `hotelOptions` list from an earlier turn while `hotelFilterData.hotelAmenities` from the newer (itinerary) turn overwrote the catalog to empty.

2. **[MEDIUM] "view biển" (colloquial "sea view") is not recognized as a supported amenity filter, and the note is self-contradictory.** The very first search reply says *"Mình chưa hỗ trợ lọc theo: view biển"* despite the user's message literally asking for "view biển" and despite the returned hotel cards showing a "Nhìn ra biển" tag. Later, after re-stating the preference through the "Sở thích" chips (which include "biển"), the reply says *"Không có khách sạn nào vừa có đủ các tiện ích: Nhìn ra biển... Mình chưa hỗ trợ lọc theo: view biển"* — in the same message, "Nhìn ra biển" is being treated as an active, hard, zero-match filter, while "view biển" is *also* reported as unsupported. Two different amenity-resolution paths appear to disagree about the same underlying request.

3. **[HIGH] A direct follow-up question about an already-named hotel gets reinterpreted as a brand-new search.** Asking "Khách sạn Mangata này có gần bãi biển Mỹ Khê không và có phòng nào view biển thật không?" (a question, referencing a specific hotel already shown) produced *"Mình tìm được 9 khách sạn phù hợp"* — a fresh, wider search — instead of an answer. This is the same failure mode as the original report's bug #9, which an earlier fix targeted by adding prompt guidance to `extract_patch`'s system prompt (`prompts.py`) telling the model that a question about already-shown results should be `general_question` with no changes. That guidance is text-only/probabilistic, and this run shows it does not reliably prevent the misclassification for a compound sentence combining two sub-questions.

4. **[MEDIUM] An unresolved hotel reference caused an unrelated revert to Step 1.** Asking "Khách sạn đầu tiên có hồ bơi ngoài trời không?" after two different hotel-count results existed in the conversation (5, then 9) produced a reasonable disambiguation reply from the assistant ("bạn đang hỏi về Khách sạn Mangata, hay 'khách sạn đầu tiên' trong danh sách 5, hay danh sách 9?") — but immediately after, a second assistant message appeared re-asking "Sở thích của bạn?" and the whole UI reverted from "Bước 2 · Chọn khách sạn" to "Bước 1 · Thu thập thông tin", hiding the hotel list entirely. Nothing about my message referenced preferences. Recovery required manually re-answering "Sở thích" and resubmitting the whole intake.

## Missing / expected features

Unchanged from prior reports — no booking-policy details (cancellation policy, price breakdown) surfaced anywhere in the flow; out of scope for this pass.

## Satisfaction score

**5/10** — "The initial search was genuinely impressive — one sentence, and it got our destination, dates, budget, and guest count right. But the moment I tried to actually *ask* something about a hotel instead of clicking a button, it fell apart: my question got silently swapped for a new search, twice, and at one point the whole planner threw away our hotel list and made us answer a preferences question we'd never been asked before. The room-hold-to-itinerary flow itself was slick — one click and we had a real 4-day plan — but going back to look at hotels again showed nonsense tags like `wheelchair_accessible_entrance` instead of real words. For an anniversary trip we want to feel confident about, that's a lot of rough edges to hit in one short session."

## Fix applied (post-report)

**Errors #1 (amenity labels reverting to raw IDs) — root cause found and fixed.**

`App.tsx` retains the last non-empty `hotelOptions` list per session (`hotelOptionsBySession`) specifically so the hotel cards stay visible across turns that don't re-run the hotel search (selecting a hotel, building the itinerary, a qa_node answer — any of which legitimately return an empty `hotel_options` from the backend). `hotelFilterData` (which carries `hotelAmenities`, the id→Vietnamese-label catalog) had no equivalent retention — `stage-hotels.tsx` read it straight off live `state.hotelFilterData`, which genuinely goes empty on those same turns. The retained hotel cards kept rendering, but with nothing to resolve their amenity tags against, so `displayAmenityLabels` fell back to the raw canonical id for every tag.

Fixed by retaining `hotelFilterData` the same way, alongside `hotelOptions`, in a new `hotelFilterDataBySession` cache (`App.tsx`), threaded down as an explicit prop through `AppShell` → `StageRouter` → `StageHotels` (mirroring the existing `hotelOptions` prop), replacing `StageHotels`'s direct reads of `state.hotelFilterData.*`.

Verified live: reproduced the bug on the rebuilt (pre-fix) image via the room-hold → itinerary-build → back-to-hotel-list path, confirmed the fix resolves it after rebuilding with the change, and confirmed no regression via `vitest run` (232/233 passing, one pre-existing unrelated failure) and `tsc --noEmit` (same 30 pre-existing errors, all unrelated missing-type-declaration issues).

**Errors #2, #3 and #4 — root-caused and fixed in a follow-up pass**, together with the "view đẹp → Dép lê" false positive carried over unfixed from the earlier verification report.

- **#3 (questions became new searches) was a self-inflicted regression.** `extract_patch.py`'s deterministic grounding rescues (`_ground_sea_view`, added in the previous fix pass, and the pre-existing `_ground_included_breakfast`) ran on *every* message regardless of intent. A read-only question naming an amenity therefore had a `hotel_preferences.amenities` change appended after the model had correctly returned `general_question` with no changes — the exact contract `prompts.py` spells out, overridden by code running after it. A non-empty patch makes `pending_tasks` non-empty, which sends the supervisor's zero-LLM fast path straight to `hotel_node`. Because the injection was deterministic, so was the bug. Both rescues are now gated on intent.
- **#2 (self-contradictory sea-view reply)** had two causes: the extractor's raw echo of the user's wording ("view biển") sat in the slot beside the canonical `sea_view`, and never resolved — so the same reply applied "Nhìn ra biển" as a filter while reporting "view biển" unsupported. Grounding now replaces the raw spelling instead of sitting next to it, and `view biển` / `hướng biển` were added to the `sea_view` catalog row's `match_keywords` so already-polluted sessions resolve too.
- **#4 (Step-1 revert)** was the same class as Errors #1: `derive-stage.ts` and `chat-panel.tsx` read the **live** `state.hotelOptions`, which legitimately empties on any turn that didn't re-run the search, so a qa_node answer fell through every branch to `'intake'` and resurfaced the preferences card. Both now use the retained per-session signal, with `workspace` precedence preserved so a built itinerary still wins.
- **"view đẹp" → "Dép lê"** traced to `_match_terms` dropping ≤2-character tokens. Vietnamese syllables are frequently exactly two letters once diacritics are stripped, so "dép lê" collapsed to `{dep}` and `_phrase_match_score`'s "every phrase token present" rule fired on that one token appearing anywhere in the request (`"view đẹp"` scored 0.860 vs 0.706 for the runner-up — clearing both the 0.85 bar and the 0.15 ambiguity guard). The same defect made "giá rẻ" resolve to "Gia vị thiết yếu". Two-character tokens are now kept, which restores the syllable that tells those pairs apart and routes multi-syllable labels through the strong subset rule instead. `chỗ đậu xe` was the one probe that regressed (it had been matching `parking` only by accident via the weak rule) and was closed by adding it as a catalog keyword.

Verified live after a rebuild: the sea-view search no longer contradicts itself; a question naming "view biển đẹp nhất" (both former triggers in one sentence) returns an answer with the hotel count unchanged at 5 and the panel still on "Bước 2"; and "view đẹp và giá rẻ" searches cleanly with only the "Nhìn ra biển" chip applied. Backend suite: 12 failures vs 14 on pristine `origin/main` — a strict subset, no new failures. Frontend: 235/236 (one pre-existing unrelated failure), `tsc` error count unchanged at 30.

## Recommendations

1. **Isolate why the room-hold/select-hotel path produces an empty amenity catalog** while `hotel_options` itself stays populated — this is the highest-priority item, as it's a regression of an already-fixed bug via a new code path (the concurrent booking feature).
2. **Add a deterministic rescue for "view biển"** in `extract_patch.py`'s grounding pass (mirroring the existing `_ground_sea_view`/`_ground_included_breakfast` pattern) — the phrase should resolve to the same `sea_view` slot as more formal phrasings, and the "unsupported" note should never be echoed once the term IS being applied as an active filter.
3. **Investigate why asking about a specific, named hotel still routes to a new search** roughly half the time — the current fix is prompt-only; consider a deterministic pre-check (e.g., if the message contains a hotel name that matches an already-shown option, force `general_question`) as a backstop the way `_derive_dates_from_explicit_range` backstops date parsing.
4. **Investigate the stray "Sở thích" re-ask / Step-1 revert** triggered by an ambiguous hotel-reference question — likely a routing edge case where `qa_node`'s disambiguation reply is followed by a second, unrelated intake-completion turn firing on stale/leftover state.
