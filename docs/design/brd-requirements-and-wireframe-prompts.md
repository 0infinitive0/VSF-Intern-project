# BRD Requirements & Wireframe Prompts — V-OTA AI Chat

Nguồn: [`docs/brd/BRD_V-OTA_AI-Chat_VSF2026_2.pdf`](../brd/BRD_V-OTA_AI-Chat_VSF2026_2.pdf) (v1.2, 20/07/2026). Xem thêm [`design_proposal.md`](./design_proposal.md) cho tech stack và sơ đồ hệ thống.

## 1. Yêu cầu nghiệp vụ (BR) — bắt buộc, có mã truy vết

> Cột **Trạng thái** là ánh xạ best-effort vào code trên `main` (2026-08-27), cần đội tiếp nhận xác nhận lại.
> ✅ xong · ⚠️ một phần / chưa đo · ❌ chưa làm · 🔄 đang làm

| Mã | Yêu cầu | Sprint | Trạng thái |
|---|---|---|---|
| BR-01 | Kho dữ liệu du lịch chuẩn hóa từ **≥ 2 nguồn OTA**, có ghi nguồn gốc + cập nhật được | 1 | ✅ Agoda + Booking; `source_platform`/`source_hotel_id`; UPSERT |
| BR-02 | Thu thập dữ liệu phải trong khuôn khổ pháp lý (ToS, robots.txt), đánh giá rủi ro trước khi mở rộng | 1 | ⚠️ ràng buộc PoC ghi trong `data_pipeline_flow.md`; chưa có tài liệu đánh giá rủi ro riêng |
| BR-03 | Tìm dịch vụ bằng **hội thoại tự nhiên** (VI hoặc EN), thay thao tác từ khóa + bộ lọc | 2 | ✅ graph + RAG semantic search |
| BR-04 | **Tinh chỉnh kết quả trong hội thoại** (giá, hạng sao, tiện ích, khu vực) không cần bắt đầu lại | 2 | ✅ `hotel_preferences.*`, pill filter |
| BR-05 | Luồng **liền mạch tìm kiếm → đặt phòng**, không mất ngữ cảnh lựa chọn | 2 | ✅ room-card → booking-modal → VNPay; hold theo `session_id` |
| BR-06 | Lịch trình cá nhân hóa theo **ngày – ngân sách – sở thích**, tối ưu hành trình, gắn khách sạn/điểm tham quan | 3 | ✅ `trip_scheduler` + `budget_check` |
| BR-07 | Mọi thông tin AI đưa ra (giá, khách sạn, lịch trình) **phải grounding trên dữ liệu thật** của hệ thống | 2–3 | ✅ enforce bằng contract + assertion tất định trong eval |
| BR-08 | Tài liệu hóa đủ để đội khác tiếp nhận sau khi intern kết thúc | 1–3 | 🔄 `docs/` đang được rà soát/cập nhật; còn thiếu runbook vận hành, env reference, tài liệu Admin/Auth |
| BR-09 | Kết thúc PoC phải có đánh giá KPI + khuyến nghị **go/no-go** | 3 | ❌ chưa có báo cáo KPI / go-no-go (eval harness có sẵn số liệu retrieval/e2e để dựng) |
| BR-10 | Hiểu **truy vấn trộn VI/EN** (vd tên địa danh/khách sạn tiếng Anh trong câu tiếng Việt), trả lời đúng ngôn ngữ người dùng đang dùng | 2–3 | ✅ `bge-m3` xuyên ngữ; `language` trong request; eval có cặp vi/en |

## 2. Mục tiêu kinh doanh (BO) — có ngưỡng đo được

| Mã | Mục tiêu | Ngưỡng đề xuất | Hạn | Trạng thái |
|---|---|---|---|---|
| BO-01 | PoC end-to-end chạy dữ liệu thật | Demo nghiệm thu + báo cáo go/no-go | Cuối S3 | ⚠️ chạy được end-to-end; báo cáo go/no-go chưa có (xem BR-09) |
| BO-02 | Dữ liệu chuẩn hóa | ≥2 nguồn OTA, **≥1.000 bản ghi** truy vấn được | Cuối S1 | ✅ ~1.103 khách sạn / 6.375 phòng (data_dictionary §1.4b) |
| BO-03 | Rút ngắn thời gian tìm-lập kế hoạch | **<5 phút hội thoại** thay hàng chục phút thao tác | S2–3 | ⚠️ chưa đo chính thức |
| BO-04 | Luồng dẫn đặt phòng liền mạch | **≥70%** kịch bản test hoàn thành đến bước chuyển đặt phòng | Cuối S2 | ⚠️ luồng có (VNPay thật); tỉ lệ chưa đo chính thức |
| BO-05 | Năng lực AI nội bộ | 2 intern hoàn thành 3 sprint + gói bàn giao | Cuối chương trình | 🔄 gói bàn giao đang chuẩn bị |

## 3. Phạm vi (Scope)

**Trong phạm vi:** PoC chat AI tìm kiếm (khách sạn/phòng/tour/vé) VI/EN, lọc theo nhu cầu, dẫn tới bước đặt phòng, gợi ý+tối ưu lịch trình; kho dữ liệu chuẩn hóa ≥2 nguồn OTA; kiểm thử/tài liệu/demo nội bộ.

**Ngoài phạm vi:** thanh toán thật + booking engine hoàn chỉnh; vận hành thương mại/SLA; marketing; đàm phán hợp đồng dữ liệu OTA; app mobile riêng; ngôn ngữ ngoài VI/EN.

## 4. Cột mốc (Milestones)

| Mốc | Thời điểm | Kết quả |
|---|---|---|
| M0 Kick-off | Đầu tuần 1 | Chốt KPI, lịch sprint, nguồn dữ liệu |
| M1 | Cuối tuần 2 | Báo cáo khả thi kỹ thuật+pháp lý, kiến trúc dữ liệu, PoC pipeline, dataset mẫu |
| M2 | Cuối tuần 4 | AI Chat tìm kiếm end-to-end, bộ lọc, chuyển đặt phòng |
| M3 | Cuối tuần 6 | Sản phẩm hoàn thiện (kèm lịch trình), báo cáo kiểm thử, gói bàn giao |

## 5. Thiết kế phân lớp L1/L2/L3 (mục 13 BRD)

**L1 (System Context):** Người dùng (VI/EN) ↔ V-OTA AI Chat ↔ [Nguồn OTA (crawl/API), LLM API (ngoài), Bước đặt phòng OTA/V-OTA (nhận handoff)].

**L2 (Component Architecture)** — 4 lớp:
1. **Giao diện người dùng** — Web Chat UI (demo nội bộ, S2)
2. **Lõi hội thoại (S2-3):** Điều phối hội thoại (ngữ cảnh phiên đa lượt) → NLU song ngữ (ý định+tham số) → Sinh trả lời (LLM + grounding)
3. **Dịch vụ nghiệp vụ (S2-3):** Tìm kiếm & bộ lọc (S2) · Lập lịch trình & tối ưu (S3) · Handoff đặt phòng (S2)
4. **Nền tảng dữ liệu (S1):** Connector OTA → Chuẩn hóa dữ liệu → Kho dữ liệu (CSDL + chỉ mục vector)

**L3 — luồng tuần tự "tìm kiếm→đặt phòng"** (Hình 3 BRD): User→ChatUI→Điều phối+NLU→Tìm kiếm→Kho dữ liệu→(LLM soạn trả lời có grounding, bắt buộc theo BR-07)→hiển thị kết quả+gợi ý lọc→user chọn→handoff đặt phòng kèm ngữ cảnh.

**L3 — mô hình dữ liệu khái niệm** (Hình 4 BRD): `Địa điểm` 1-n→ `Khách sạn`(nguồn, thu_thập_lúc) 1-n→ `Phòng` 1-n→ `Giá theo thời điểm`; `Địa điểm` 1-n→ `Điểm tham quan`, `Tour/Vé`; `Lịch trình`(ngân sách, sở thích, trạng thái) 1-n→ `Mục lịch trình`(ngày, thứ tự, tham_chiếu n-1 tới khách sạn/điểm tham quan/tour, chi phí).

**Danh mục sơ đồ cần lập thêm** (mục 13.4 BRD):
- Máy trạng thái hội thoại (dialog state machine) — S2
- **Wireframe giao diện chat** (L2) — khung chat, thẻ kết quả, nút lọc nhanh, nút chuyển đặt phòng — **S2** (nguồn gốc của các prompt Stitch dưới đây)
- Sơ đồ tuần tự luồng lịch trình (giống Hình 3) — S3
- Sơ đồ triển khai môi trường demo — S3
- DAG pipeline dữ liệu + từ điển dữ liệu/ERD chi tiết — S1

## 6. Các luồng (stages) cần thiết kế wireframe

Đối chiếu code hiện tại (`src/agents/graph.py`, `frontend/src/components/`):

| # | Luồng | Stage backend | Mục đích |
|---|-------|---------------|----------|
| 1 | Trip Intake | `intake` | Thu thập destination, ngày đi/về, số khách, sở thích qua chat + form gợi ý |
| 2 | Hotel Preference | `intake` (giai đoạn sau) | Hỏi ngân sách/tiện nghi khách sạn mong muốn |
| 3 | Hotel Selection | `hotel_options` | Hiển thị 3–5 thẻ khách sạn để chọn |
| 4 | Itinerary Result | `planned` | Hiển thị lịch trình đầy đủ theo ngày + bản đồ |
| 5 | Modify Itinerary | `modified` | Sửa lịch trình qua chat, thấy thay đổi phản ánh ngay |
| 6 | Finalize & Share | `finalized` | Chốt kế hoạch, đổi badge trạng thái, chia sẻ |
| 7 | Search Results | — (BR-03/BR-04) | Kết quả tìm kiếm đa dịch vụ (khách sạn/phòng/tour/vé) kèm bộ lọc nhanh |
| 8 | Booking Handoff | — (BR-05) | Chuyển ngữ cảnh lựa chọn sang bước đặt phòng OTA/V-OTA |

Chưa cover trong code hiện tại: luồng **Search Results** (7) với multi-service filter chips (giá/sao/tiện ích/khu vực), và **Booking Handoff CTA** (8) dẫn ra trang đặt phòng — cả hai đều được BRD yêu cầu rõ (BR-04, BR-05).

## 7. Prompt Google Stitch (theo luồng)

Chạy prompt **Design System** trước để giữ style nhất quán, sau đó chạy từng prompt luồng (dùng chung `--project-name` để nhóm 1 project).

### 0. Design System

```
A modern, clean web app design system for a travel-planning AI assistant called "VSF Trip Planner". Style: friendly, trustworthy, minimal — similar to Notion x Airbnb. Base layout is a 3-panel desktop app: left panel is a chat sidebar (min 300px, default 380px, resizable), middle panel is a content/itinerary panel (min 320px, default 420px, resizable), right panel fills remaining space with a map. Color system: neutral white/light-gray background, one primary accent blue for CTAs and active states, plus a 5-color day-accent cycle (Material blue, cyan, teal, purple, orange) used as left-border stripes on day cards. Typography: clean sans-serif, clear hierarchy (14px body, 12px meta labels, bold 16-18px headings). Components: rounded-corner cards (12px radius), soft shadows, pill-shaped suggestion chips, status badges (Draft = gray, Finalized = green). Icons: line-style icons for activity types (egg=breakfast, utensils=lunch/dinner, coffee cup=coffee, map-pin=attraction, bed=hotel/rest, moon=nightlife). Include a small language toggle (VI/EN) in the top-right corner of the chat panel. Desktop, 1440px width.
```

### 1. Trip Intake Flow

```
Desktop web app wireframe, 3-panel layout, "VSF Trip Planner" travel assistant. LEFT panel (380px): chat sidebar with an AI greeting bubble welcoming the user and asking about their trip, a user message bubble, a text input composer at the bottom with a send button, and a small elapsed-time spinner shown while the AI is "thinking". MIDDLE panel (420px): an intake summary card at top titled "Trip Parameters" showing partially-filled fields (Destination, Start date, End date, Guests) with empty/placeholder states for fields not yet answered, and below it a guided intake form with: a destination text input with autocomplete suggestions, a date-range picker (start/end date), a guest-count stepper, a row of selectable preference chips (Beach, Culture, Food, History, Shopping, Nightlife, Family), a companions selector (Solo/Couple/Family/Friends), a pace selector (Relaxed/Balanced/Packed), and a notes textarea. Below the form, horizontal pill-shaped "suggestion chips" the user can tap instead of typing. RIGHT panel: empty map placeholder with a centered message "Map will appear once your destination is set". Show this as an empty/in-progress state — no hotel or itinerary data yet.
```

### 2. Hotel Preference (Budget) Flow

```
Desktop web app wireframe, same 3-panel "VSF Trip Planner" layout and design system as before. LEFT panel: chat thread where the AI asks a follow-up question "What's your budget for accommodation?" with a row of tappable suggestion chips below it: "Budget", "Mid-range", "Luxury". A second AI message asks about hotel amenities/vibe with another row of chips: "Pool", "Beachfront", "City center", "Family-friendly", "Quiet". MIDDLE panel: the completed Trip Parameters card at the top (all intake fields filled, shown with checkmarks) with a subtle "Preferences" section below listing selected budget tier and amenity chips as tags. RIGHT panel: map showing a single pin at the destination city center, zoomed to city level, no other markers yet.
```

### 3. Hotel Selection Flow

```
Desktop web app wireframe, 3-panel "VSF Trip Planner" layout. LEFT panel: chat showing the AI message "Here are hotels matching your preferences — reply with a number to select" plus numbered suggestion chips 1-5. MIDDLE panel: a compact Trip Parameters summary bar at top (destination, dates, guests, collapsed), followed by a vertical list of 4 Hotel Option Cards. Each card shows: a large index number badge (1-5) in a circle, hotel name as heading, star rating (filled star icons, e.g. 4.5), a 2-line description, small tags for matched room types (e.g. "Deluxe Double", "Sea View Suite"), and a price block on the right showing average nightly price and total stay price with currency. Cards have a subtle hover/selectable border state; one card shown as "selected" with an accent border and checkmark. RIGHT panel: map with multiple pins, one per hotel location, clustered around the destination, with the selected hotel's pin highlighted in the accent color and slightly larger.
```

### 4. Itinerary Result Flow

```
Desktop web app wireframe, 3-panel "VSF Trip Planner" layout, this is the main/hero screen. LEFT panel: chat thread with the AI confirming "Here's your itinerary!" and the composer input below for follow-up modification requests. MIDDLE panel (itinerary panel): a header showing destination name as large title, a status badge "Draft" (gray pill), small edit and share icon buttons top-right; below that a metadata row with calendar icon + date range and a group icon + adult count; below that a horizontal scrollable row of day-navigation pills ("Day 1", "Day 2", "Day 3"...) with the active day pill highlighted in accent color; a hotel summary card showing hotel name, star rating, short description, and matched room tags. Below that, a vertical stack of Day Cards (show 2 days), each with a colored left-border accent (different color per day), a heading "Day 1 — Arrival & Old Town" and a vertical activity timeline: each activity row has a small circular icon (breakfast=egg, attraction=map-pin, lunch=utensils, rest=bed, nightlife=moon), a time range label (e.g. "08:00–09:30"), the activity name, and a small kind badge tag on the right (e.g. "Breakfast", "Attraction"). At the bottom of each day card, a small "Adjustments" note list with bullet points. RIGHT panel: a full map with numbered pins for each activity location of the active day, connected by a subtle route line, plus a pin for the hotel in a distinct color.
```

### 5. Modify Itinerary Flow

```
Desktop web app wireframe, 3-panel "VSF Trip Planner" layout, same as itinerary result screen but showing an in-progress edit interaction. LEFT panel: chat thread showing a user message "Can you move the museum visit to the afternoon and add a coffee break?" followed by an AI response confirming the change, with the elapsed-time spinner shown briefly above the composer to indicate processing. MIDDLE panel: the itinerary panel identical to the result screen, but the Day Card being edited has a subtle highlighted/glowing border to show it just changed, one activity row shows a small "updated" indicator (e.g. a colored dot or "new" tag) next to the modified item, and a new activity row for "Coffee break" has been inserted into the timeline with a coffee-cup icon. Status badge still reads "Draft". RIGHT panel: map updated with the new/moved pin position, with a brief connecting line showing the changed route segment in a dashed style.
```

### 6. Finalize & Share Flow

```
Desktop web app wireframe, 3-panel "VSF Trip Planner" layout, showing the finalized/completed state. LEFT panel: chat thread with the user message "Looks great, let's finalize it" and an AI confirmation message with a celebratory tone. MIDDLE panel: itinerary panel header now shows status badge changed to "Finalized" (green pill with checkmark icon) instead of "Draft", the edit icon button is now disabled/grayed out, and a prominent "Share" button is highlighted (accent color, with share icon) possibly opening a small dropdown/modal showing a shareable link field with a copy button and export options (PDF, Calendar). The day cards and hotel summary remain as before but with a subtle "read-only" visual treatment (e.g. slightly reduced interactivity affordances). RIGHT panel: final map view with all days' routes shown together in their respective day-accent colors, with a legend in the corner mapping colors to day numbers.
```

### 7. Search Results Flow (BR-03, BR-04)

```
Desktop web app wireframe, 3-panel "VSF Trip Planner" layout, design system consistent with previous screens. LEFT panel: chat thread where the user typed a natural-language search query mixing Vietnamese and English (e.g. "khách sạn gần Times Square giá dưới 2 triệu, có pool"), and the AI reply summarizes the interpreted search intent as a short recap line above the results. MIDDLE panel: a "Search Results" header showing the service type tabs (Hotels | Rooms | Tours | Tickets, with "Hotels" active), directly below a row of QUICK FILTER CHIPS that are toggleable pills: "Price range", "Star rating ★4+", "Amenities", "Area/District", each chip shows a small dropdown caret and an active state with accent-colored border when applied; a "Clear filters" text link at the end of the row. Below the filters, a vertical list of 4-5 result cards (mixed types: hotel, tour) each showing a thumbnail image placeholder on the left, name, star rating or category tag, 1-line description, small tags for matched filters (e.g. "Pool", "City center"), and a price block on the right with a "View details" button. One card shows an active hover/selected state. RIGHT panel: map with pins for each visible result, color-coded by service type (hotel pin vs tour pin), with a floating "Search this area" button overlaying the map top-center.
```

### 8. Booking Handoff Flow (BR-05)

```
Desktop web app wireframe, 3-panel "VSF Trip Planner" layout, design system consistent with previous screens. LEFT panel: chat thread showing the user's selection message (e.g. "Book this hotel, deluxe room") and the AI confirming with a summary line, followed by a prominent inline card embedded in the chat bubble titled "Ready to book" listing the carried-over context: hotel name, room type, check-in/check-out dates, number of guests, total price — and a large primary button "Continue to booking" with an external-link icon. MIDDLE panel: a "Booking Summary" panel (replacing itinerary panel in this state) with a clear header "Confirm & Continue", showing a structured summary card: hotel name + star rating + thumbnail, room type with amenities tags, a table-style breakdown of dates (check-in/check-out), guests count, nightly price x nights = subtotal, and a sticky footer bar at the bottom with the total price on the left and a large "Proceed to Booking" CTA button on the right (accent color), plus small secondary text below it: "You'll be redirected to complete payment on V-OTA" with a small external-link icon. RIGHT panel: map showing a single highlighted pin for the hotel/service location with an info card popup already open showing the address.
```

## Câu hỏi chưa giải quyết

- Kho dữ liệu OTA chuẩn hóa từ ≥2 nguồn (BR-01/BR-02) — chưa xác nhận trạng thái triển khai trong code hiện tại (scan trước chỉ khảo sát frontend + agent flow, chưa khảo sát data pipeline).
- Luồng Search Results (đa dịch vụ: hotel/room/tour/ticket) hiện có tồn tại trong backend hay chỉ có `recommend_hotels`? Cần xác nhận trước khi implement UI thật.
