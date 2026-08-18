# OTA Customer Journey QA Report — Family persona, Nha Trang

**App tested:** http://localhost:5173/ ("V-OTA AI Travel Planner"), rebuilt from `main` at `4876b50` (post PR #18)
**Date:** 2026-08-18
**Purpose:** Full end-to-end journey with a persona type not yet used (family with young children), exercising the new Q&A context tools and the newly-durable session memory.

## Persona & trip brief

**Who:** Hùng, 41, an engineering manager from Hồ Chí Minh City, travelling with his wife and two children (7 and 4). Tech-comfortable and impatient — types full sentences, expects an answer rather than a menu.
**Trip:** Nha Trang, originally 10–13 Jul 2026, moved to 1–4 Jul 2026 (3 nights), 4 guests, ₫2,000,000–3,500,000/night.
**Top priorities:** a room that actually fits four, a pool the kids can use, breakfast included, and not being made to work for an answer.

## Step-by-step timeline

| Step | What happened | Time | Status |
|---|---|---|---|
| Landing | Clean load, no console errors | ~2s | smooth |
| Search #1 (10–13 Jul) | One sentence → destination, 4 guests, dates and budget all parsed correctly. No availability for those dates | ~12s | smooth (honest dead-end) |
| Date change | "Vậy đổi sang từ 1/7/2026 đến 4/7/2026" → re-searched cleanly, 1 hotel | ~15s | smooth |
| Room capacity question | Full, grounded, per-room-type answer in one turn | ~18s | smooth — see Errors #2, #3 |
| Open hotel detail | 5 of 6 room types sold out; 1 bookable | ~4s | friction — see Errors #1 |
| Build cart | Added 2 Suites (family of 4, 2 guests each) — total ₫12,583,854, arithmetic correct | ~5s | smooth |
| **Hold rooms** | **"Giữ phòng" disabled with a valid 2-room cart — journey ends here** | — | **broken — see Errors #1** |
| Reload page | Destination, guests, dates and budget all survived; hotel list did not | ~3s | partial — see Errors #4 |
| Re-search with preferences | Same dates now returned **0** breakfast hotels where minutes earlier they returned 1 | ~14s | broken — see Errors #5 |
| Drop breakfast | 6 hotels returned, list rendered correctly | ~13s | smooth |
| List-spanning question | Cheapest identified correctly; pool question answered **wrongly** | ~16s | broken — see Errors #6 (now fixed) |

The journey never reached guest details, payment or confirmation: the hold button is disabled, so there is no path past hotel selection.

## AI conversation quality

| Interaction | What happened | Verdict |
|---|---|---|
| Free-form multi-fact sentence | Destination, party size, dates and budget extracted correctly in one turn | excellent |
| Mid-conversation change (dates) | Applied cleanly, re-searched, no drift in the other fields | handled cleanly |
| Direct question about one hotel's rooms | Listed every room type with beds and size, and **volunteered a data inconsistency** ("Liberty Central Suite mô tả có giường sofa nhưng max_guests = 2") | excellent grounding |
| Question spanning the whole list | Cheapest correct; "which have a pool" wrong for 4 of 6 | see Errors #6 |
| Compromise request ("bỏ bữa sáng") | Understood and re-ran correctly | handled cleanly |

The assistant no longer asks permission before looking things up, and no longer turns a question into a new search or an itinerary rebuild — the three regressions fixed in PRs #16–#18 all held up across this run.

## Errors encountered

1. **[BLOCKER] "Giữ phòng" is disabled with a valid cart.** Two Suite rooms selected, ₫12,583,854 totalled and displayed, yet the button is `disabled: true` / `cursor: not-allowed`. `canStart` (hotel-detail-panel.tsx:589) requires `cartCount > 0 && checkInDate && checkOutDate` plus an idle hold; the cart and hold state were both fine, which points at `checkInDate`/`checkOutDate` arriving null from `state.intake` on that turn. **This ends the customer journey** — there is no way to reach booking, payment or confirmation. Highest priority: everything downstream of hotel selection is unreachable and therefore untested.

2. **[MEDIUM] Raw database field names are read out to the user.** The room answer says "không có loại phòng nào có trường `max_guests` = 4", "`max_guests` = null", "`lowest_price` là 2.097.309 VND". Same class as the amenity-ID leak fixed earlier, one layer up: `query_hotel_rooms` hands the model raw column names and it repeats them. A customer does not know what `max_guests = null` means.

3. **[MEDIUM] The room tool is blind to price and availability.** It reported "dữ liệu chi tiết giá theo từng loại phòng không được trả về" while the UI showed **2.097.309 ₫** for the Suite, and it listed all six room types as options without mentioning that **five were sold out**. `query_hotel_rooms` selects only `name, max_guests, room_size_sqm, bed_description, view, room_facilities` — no price, no availability. The assistant can therefore recommend rooms the user cannot book.

4. **[MEDIUM] Reload keeps the trip but loses the hotel list.** After a refresh, destination/guests/dates/budget were all correctly restored (the new Postgres checkpointer working), but the app returned to "Bước 1", dropped the hotel list, and re-asked for preferences. The user must re-run the search to get back to where they were.

5. **[HIGH] Identical constraints returned different results across two runs.** At 15:21, Nha Trang 1–4 Jul with a breakfast filter returned **1 hotel** (Liberty Central, breakfast tag visible on the card). At 22:29, the same destination, dates, party size and budget returned **"Không có khách sạn nào… Bao gồm bữa sáng"** and offered 19 without it. One of those two answers is wrong, and a customer who reloads and re-searches sees their options vanish.

6. **[HIGH — fixed during this run] The assistant said four hotels had no pool while their cards showed one.** Asked which of the six had a pool, it named two and stated Virgo, Alana, Starcity and CostaBella "không liệt kê Hồ bơi". All four display **Hồ bơi** on the card. Root cause was mine, introduced in PR #18: `get_hotel_options` capped each hotel's amenities at the first 8, and `amenities` is stored in no meaningful order — hotels carry 50–123 entries, so pools routinely fell past the cut. The data was never wrong; every hotel carries `swimming_pool`. Fixed in PR #19 (cap removed, regression test added), verified in a clean session: *"Tất cả 5 khách sạn trong danh sách đều có hồ bơi."*

## Missing / expected features

1. **No family-room search.** The persona needs one room for 2 adults + 2 children; nothing in the flow filters by occupancy, and the answer to "phòng nào chứa được 4 người?" was "none" with no suggestion to book two rooms — which is what the cart then let me do unprompted. Any mainstream OTA asks for guests-per-room up front and filters on it.
2. **No child/occupancy handling at all.** Ages 7 and 4 were stated in the opening message and never used — no child pricing, no extra-bed option, no "children stay free" signal.
3. **Sold-out rooms are listed alongside bookable ones** rather than filtered or sorted down, so most of the room list is dead space.
4. Cancellation policy, price breakdown and written reviews remain absent, as in previous reports.

## Satisfaction score

**4/10** — "The first thirty seconds were genuinely impressive: I typed one long sentence about my family and it got the city, the dates, all four of us and the budget right, then told me honestly that my dates were full instead of pretending Nha Trang had no hotels. Asking about rooms gave me a real answer, and it even warned me the hotel's own data contradicted itself, which I appreciated. But it never told me five of the six rooms were sold out, it couldn't tell me what any room cost when the screen was showing me the price, and when I asked which hotels had a pool it told me four of them didn't — while I was looking at 'Hồ bơi' on all four cards. Then I picked two suites for my family, ₫12.5 million sitting on screen, and the button to hold them simply would not work. I never got to a booking form. For a family trip I have to actually book, this stopped being useful right at the point it mattered."

## Recommendations

1. **Fix the disabled hold button first (Errors #1).** Nothing past hotel selection can be tested or used until it works; the whole booking, payment and confirmation flow is currently unreachable from a normal journey. Start with why `checkInDate`/`checkOutDate` reach `HoldFooter` as null when `state.intake` holds them.
2. **Give `query_hotel_rooms` price and availability** (Errors #3). It already queries the `rooms` table; the UI gets both from the same data. Without them the assistant will keep recommending sold-out rooms and claiming prices are unavailable while they are on screen.
3. **Investigate the unstable search result (Errors #5).** Same constraints, different answers minutes apart is corrosive to trust and hard for a user to interpret as anything but a broken app.
4. **Translate field names before they reach the model** (Errors #2) — the same fix already applied to amenity IDs, extended to `max_guests` / `lowest_price` / `null`.
5. **Carry the hotel list across a reload** (Errors #4), or re-run the search automatically so the user lands back where they were.
6. **Add occupancy to the search** (Missing #1/#2) — for a family app this is table stakes, and the data already carries `max_guests`.
