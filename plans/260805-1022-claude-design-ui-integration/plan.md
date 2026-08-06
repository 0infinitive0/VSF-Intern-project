---
title: "Tích hợp Claude Design UI"
description: "Tích hợp bản export Claude Design (V-OTA Planner — Apple HIG glassmorphism) vào dự án hiện tại theo hướng contract-first, chia 2 track (backend + frontend) chạy song song, giữ nguyên toàn bộ business logic, chỉ bổ sung dữ liệu thật từ DB, và ghi nhận rõ những phần trong design chưa làm."
status: pending
priority: P1
effort: "12-16 ngày (2 dev song song sau Phase 1)"
tags: [frontend, backend, ui-redesign, glassmorphism, api-contract, leaflet, i18n, session-persistence]
blockedBy: []
blocks: []
created: 2026-08-05
updated: 2026-08-05
---

# Tích hợp Claude Design UI

## Tổng quan

Tích hợp bản export Claude Design tại `data/design/` vào dự án hiện tại. Bản export gồm:

- `V-OTA Planner.dc.html` — template Claude Design dạng `x-dc` (2613 dòng, inline-style
  binding với `sc-if`/`sc-for`)
- 7 tài liệu yêu cầu tiếng Việt trong `data/design/uploads/`
- 5 ảnh tham chiếu trong `data/design/screenshots/`

### Nguồn design chuẩn để đối chiếu

`data/trip_planner/trip_planner_components/` là **bản refactor thành component của chính
design đó** — cùng markup, cùng token, nhưng tách ra 16 file `*.dc.html` (một file một
component) cộng `styles/*.css` chứa toàn bộ token. Khi cần đối chiếu một thành phần cụ thể,
**dùng file component đó** thay vì đếm dòng trong file monolith 2613 dòng:

| Vùng UI | File đối chiếu | Phase |
|---|---|---|
| Chat panel, bong bóng, 5 picker intake | `ChatPanel/ChatMessage/DestinationPicker/PeoplePicker/DatePicker/BudgetSlider/InterestPicker.dc.html` | 6 |
| Sidebar, dòng lịch sử | `Sidebar.dc.html`, `HistoryRow.dc.html` | 5 |
| Card khách sạn, panel chi tiết, card phòng | `HotelCard.dc.html`, `HotelDetail.dc.html`, `RoomCard.dc.html` | 8 |
| Timeline, card ngày, panel địa điểm | `TimelineItem.dc.html`, `DayCard.dc.html`, `PlaceDetail.dc.html` | 9 |
| Token màu / motion | `styles/variables.css`, `theme.css`, `animation.css` | 1 |

Các tham chiếu dạng `V-OTA Planner.dc.html:NNN` còn lại trong các phase file vẫn trỏ đúng vào
`data/design/V-OTA Planner.dc.html` (bản monolith) — giữ được, nhưng ưu tiên file component
khi viết code.

Design này **không phải một sản phẩm mới** — nó là một bản re-skin cộng thêm ba thay đổi
cấu trúc trên chính ứng dụng đang chạy:

1. **Ngôn ngữ thị giác mới**: Apple HIG glassmorphism, layered translucency, theme
   sáng **và** tối, typography Be Vietnam Pro, motion dạng spring.
2. **Shell mới**: **sidebar rail thu gọn được → chat panel cố định → "stage" bên phải**,
   trong đó stage chuyển giữa 4 trạng thái và có thể thu gọn chat+map thành hai
   **focus mode** (chi tiết khách sạn, chi tiết địa điểm).
3. **Hai tính năng chưa có UI**: **lịch sử hội thoại** và **bản đồ tương tác thật**.

**Nguyên tắc xuyên suốt (giữ nguyên từ plan `260803-1200-stitch-ui-redesign-frontend`):
không bịa dữ liệu.** Mọi giá trị hiển thị phải đến từ database, hoặc được suy ra một cách
trung thực và ghi rõ là suy ra. Chỗ nào design yêu cầu dữ liệu không tồn tại thì bỏ phần
đó và ghi vào mục [Phần chưa làm](#phần-chưa-làm-not-implemented-register) — không fake.

### Vì sao khối lượng này khả thi

Phát hiện quyết định khi phân tích codebase: **database đã có gần như đủ mọi thứ design
cần.** Vấn đề chỉ là API không trả về.

| Design cần | Đã có trong DB | Python đã load | Có trong payload |
|---|---|---|---|
| Ảnh, tiện nghi, điểm đánh giá, địa chỉ khách sạn | `hotels.images/image_url/amenities/review_score/review_count/address` | ✅ `hotel_selection.py:50` | ❌ bị `to_hotel_options_payload` cắt bỏ |
| Toạ độ khách sạn | `hotels.coordinates` | ✅ `hotel_selection.py:50` | ❌ bị cắt bỏ |
| Giờ nhận/trả phòng, địa điểm lân cận | `hotels.check_in_time/check_out_time/nearby_attractions` | ❌ | ❌ |
| Card phòng | `rooms.*` + `room_prices.price` | ❌ | ❌ |
| Chi tiết địa điểm | `attractions.opening_time/ticket_price_adult/rating/images` | ❌ | ❌ |
| Marker trên map | `itinerary_items.coordinates` | ✅ | ✅ **đã trả về rồi**, frontend chưa dùng |
| **Route bám đường thật, khoảng cách, thời lượng** | `itinerary_items.route_to_next` (jsonb) | ✅ `routing.py` gọi routing API → `distance_km` / `duration_mins` / `polyline` | ❌ bị `to_trip_plan_payload` cắt bỏ |
| AI Match Score | — | ✅ `_composite_score` tính điểm relevance thật 0..1 | ❌ chỉ dùng để sort rồi bỏ |

Nghĩa là những tính năng lớn nhất về mặt thị giác (card khách sạn có ảnh, cả hai focus
mode, map thật, vòng tròn match score) **chỉ là việc nối dữ liệu thật đã có sẵn qua
payload**, không phải làm mới data model.

### Các quyết định đã chốt với người dùng trước khi viết plan

1. **Phạm vi backend: pass-through + detail endpoints.** Mở rộng
   `to_hotel_options_payload` với các field mà `hotel_selection.py` đã load sẵn, **và**
   thêm `GET /hotels/{id}` + `GET /attractions/{id}` để làm nền cho hai focus mode.
2. **Lịch sử hội thoại: làm persistence ở backend.** Hiện session chỉ nằm trong RAM, có
   TTL, không có endpoint list. Sẽ persist xuống bảng `sessions` / `chat_messages` có sẵn
   thông qua `persist_hook` đã tồn tại, cộng thêm endpoint list + restore.
3. **Map: Leaflet thật, route bám đường thật.**
   *Quyết định này đã được sửa sau khi người dùng chỉ ra `backend/src/services/routing.py`
   — bản plan đầu tiên đánh giá sai là "không có dữ liệu routing".* Thực tế:
   `recalculate_itinerary_routes` (`routing.py:93`) đã gọi routing cho từng cặp điểm liên
   tiếp và lưu `route_to_next = {distance_km, duration_mins, polyline}` lên itinerary item.
   Map vẽ **polyline bám đường thật**; leg pill hiển thị **khoảng cách + thời lượng thật**.
   Haversine chỉ còn là **fallback** khi routing lỗi.

4. **Nhà cung cấp routing: Mapbox Directions v5, thay OSRM public demo (Phase 12).**
   Mapbox là tác giả gốc của OSRM nên Directions v5 gần như tương thích shape — migration
   là drop-in. Đổi lấy được ba thứ:
   - `driving-traffic` cho thời lượng có traffic thật → **xoá được hệ số bịa `× 2.5`**
     (`routing.py:41`)
   - 4 profile (`driving-traffic` / `walking` / `cycling`) → **nhãn phương tiện thật**,
     chọn bằng luật khoảng cách haversine cục bộ nên vẫn 1 request/chặng
   - 300 req/phút có SLA và `https://`, thay cho demo server không cam kết

5. **Tile bản đồ: Mapbox raster tiles (`light-v11` / `dark-v11`), thay tile OSM.**
   Bỏ được hack CSS `invert(.92) hue-rotate(180deg)` mà bản export dùng để giả dark mode.
   Vẫn dùng **Leaflet**, không chuyển sang Mapbox GL JS — chỉ đổi URL tile, mọi thứ khác
   trong Phase 10 giữ nguyên. Cần **token thứ hai** (public, có URL restriction) tách biệt
   với token server của Phase 12.
6. **Ngân sách: chip theo mức (glass tier chips), không dùng slider số.** Backend intake
   match nhãn mức ngân sách theo closed-set bằng regex (`hotel_selection.py:509-531`).
   Slider 500k–50M của design sẽ đòi hỏi làm lại NLU. Giữ nguyên giá trị wire hiện tại,
   chỉ restyle thành card glass theo design.

### Cách chia việc (theo yêu cầu: 2 dev làm song song)

```
        ┌──────────────────────────────────────────┐
        │  Phase 1 — API CONTRACT + DESIGN TOKENS  │  ← chặn, cả 2 dev cùng làm
        │  docs/chat_api_contract.md · types.ts    │
        │  mock/server.js · styles.css tokens      │
        └───────────────┬──────────────────────────┘
                        │
        ┌───────────────┴───────────────┐
        ▼                               ▼
  TRACK BACKEND (Dev B)           TRACK FRONTEND (Dev F)
  Phase 2  hotel payload          Phase 5  design system + shell
  Phase 3  detail endpoints       Phase 6  chat panel
  Phase 4  session persistence    Phase 7  stage intake + generating
                                  Phase 8  stage hotels + hotel focus
                                  Phase 9  stage workspace + place focus
                                  Phase 10 Leaflet map
        └───────────────┬───────────────┘
                        ▼
              Phase 11 — TÍCH HỢP & KIỂM THỬ
```

**Điểm nối là Phase 1.** Khi contract và mock fixture xong, dev frontend phát triển hoàn
toàn trên `npm run mock` (file `frontend/mock/server.js` — đã tồn tại và đã phục vụ 4
endpoint hiện tại) và không bao giờ phải chờ backend. Hai track không sửa file của nhau.

| Track | Sở hữu | Không được đụng |
|---|---|---|
| Backend (Dev B) | `backend/src/**`, `backend/tests/**` | `frontend/**` |
| Frontend (Dev F) | `frontend/src/**`, `frontend/mock/server.js` | `backend/**` |
| Dùng chung, chỉ ở Phase 1 | `docs/chat_api_contract.md`, `frontend/src/types.ts` | — |

`frontend/src/types.ts` được viết **một lần duy nhất ở Phase 1** như bản mirror TypeScript
của contract, sau đó cả hai track coi như đã đóng băng. Mọi thay đổi sau Phase 1 đều là
thay đổi contract: phải được cả hai dev đồng ý và phải sửa kèm
`docs/chat_api_contract.md` + `mock/server.js` trong **cùng một commit**.

## Mục tiêu

| # | Mục tiêu | Ưu tiên |
|---|------|----------|
| 1 | Đưa ngôn ngữ thị giác của design (glass, dark/light, typography, motion) vào mà không tái cấu trúc dự án | P1 |
| 2 | Tái cấu trúc shell thành sidebar → chat cố định → stage, kèm hai focus mode | P1 |
| 3 | Trả về dữ liệu thật mà API đã load nhưng đang vứt đi (ảnh, tiện nghi, đánh giá, toạ độ, match score) | P1 |
| 4 | Cấp dữ liệu thật cho hai focus mode qua endpoint chi tiết khách sạn/địa điểm | P1 |
| 5 | Persist session để lịch sử hội thoại là thật và khôi phục được | P2 |
| 6 | Làm map thật: marker, route theo ngày, hover đồng bộ timeline ↔ map | P2 |
| 7 | Giữ nguyên mọi hành vi hiện có: chat contract, intake NLU, chọn khách sạn theo số thứ tự, i18n, vòng đời session | P1 |
| 8 | Cho phép 2 dev làm song song sau một contract đã đóng băng | P1 |
| 9 | Ghi nhận đầy đủ phần design chưa làm kèm lý do, thay vì fake | P1 |

## Danh sách Phase

| # | Phase | Track | Trạng thái | Phụ thuộc |
|---|-------|-------|--------|-----------|
| 1 | [API Contract & Design Tokens](./phase-01-api-contract-and-design-tokens.md) | Chung | Done² | — |
| 2 | [Mở rộng payload khách sạn](./phase-02-be-hotel-option-payload.md) | Backend | Pending | 1 |
| 3 | [Endpoint chi tiết khách sạn & địa điểm](./phase-03-be-detail-endpoints.md) | Backend | Pending | 1 |
| 4 | [Persist session & lịch sử hội thoại](./phase-04-be-session-persistence.md) | Backend | Pending | 1 |
| 12 | [Chuyển OSRM → Mapbox Directions](./phase-12-be-mapbox-routing.md) | Backend | Pending | 1 |
| 5 | [Design system & App Shell](./phase-05-fe-design-system-and-shell.md) | Frontend | Done¹ | 1 |
| 6 | [Chat panel cố định](./phase-06-fe-chat-panel.md) | Frontend | Done | 5 |
| 7 | [Stage: Intake & Generating](./phase-07-fe-stage-intake-generating.md) | Frontend | Done | 5 |
| 8 | [Stage: Khách sạn & Hotel Focus](./phase-08-fe-stage-hotels-focus.md) | Frontend | Pending | 5 |
| 9 | [Stage: Workspace & Place Focus](./phase-09-fe-stage-workspace-focus.md) | Frontend | Pending | 5 |
| 10 | [Leaflet Map & Route](./phase-10-fe-map.md) | Frontend | Pending | 9 |
| 11 | [Tích hợp & Kiểm thử](./phase-11-integration-verification.md) | Chung | Pending | 2,3,4,6,7,8,9,10,12 |

> ² Phần token của Phase 1 đã ship (chép tay giá trị vào `@theme`). Rà 06/08/2026 phát hiện
> Tailwind v4 có `@theme inline` — giải đúng bài toán mà bản đầu phải né bằng cách chép tay.
> Bốn tiêu chí đã mở lại: chuyển sang chép file design nguyên văn + alias `inline`. Ròng lại
> là **ít việc hơn** (xoá ~120 dòng chép tay, script gác đơn giản đi hẳn). Đóng lại cùng ngày
> 06/08/2026: `check:tokens`/`typecheck`/`lint`/`build` đều pass, `data-theme` đổi màu đúng cả
> hai chiều. Tiêu chí còn lại (cả hai dev review contract) là bước thủ công, không tự động
> hoá được.

> ¹ Phase 5 đã đánh Done **trước khi** có cơ chế nghiệm thu thị giác. Audit 06/08/2026 tìm
> thấy `app-shell.tsx:90` phủ màu đặc lên `--gradient-page`, giết toàn bộ hệ glass. Một tiêu
> chí đã được mở lại; sửa nằm ở Phase 6 bước 11 mục 1.

> Phase 12 nằm ở track backend, **chạy song song với Phase 2** (không phụ thuộc nhau):
> Phase 2 chuyển route từ item sang payload, Phase 12 đổi thứ tạo ra route. Đánh số 12 để
> không phải đánh lại số 11 phase đã viết.

## API Contract (điểm nối giữa 2 track)

Bản chuẩn đầy đủ sẽ nằm trong `docs/chat_api_contract.md` ở Phase 1. Tóm tắt:

### Mở rộng — `hotel_options[]` trong `PlannerChatResponse` (Phase 2)

Các field cũ giữ nguyên. Thêm mới (tất cả đều lấy từ các dòng mà `hotel_selection.py:50`
đã select sẵn, cộng điểm ranking đã được tính ở `hotel_selection.py:172-182`):

```jsonc
{
  "coordinates": "16.0544,108.2022",  // "lat,lng"; null nếu dòng DB không có
  "address": "Mỹ Khê, Ngũ Hành Sơn",
  "area_name": "Ngũ Hành Sơn",
  "image_url": "https://…",           // null nếu không có
  "amenities": ["Hồ bơi vô cực", "Bãi biển riêng"],
  "review_score": 8.9,                // thang 0..10
  "review_count": 1284,
  "match_score": 0.96,                // 0..1, điểm composite ranking thật
  "match_reasons": [                  // MÃ lý do + giá trị thô, KHÔNG phải câu chữ
    { "code": "budget_fit",     "value": 0.39 },
    { "code": "high_rating",    "value": 8.9 },
    { "code": "amenity_match",  "value": "Hồ bơi vô cực" }
  ]
}
```

`match_reasons` chỉ mang **mã + giá trị thô**; frontend tự dựng câu đã dịch từ catalog
i18n. Cách này giữ panel "AI đề xuất vì..." trung thực (nó chỉ diễn giải lại đúng những
tham số ranking thật) và đúng nguyên tắc i18n: backend không sinh chuỗi hiển thị.

### Mới — `GET /api/v1/hotels/{hotel_id}` (Phase 3)

Phục vụ Hotel Detail Focus Mode. Đọc `hotels` + `rooms` + `room_prices`. `404` nếu không có.

```jsonc
{
  "id", "name", "star_rating", "description",
  "address", "city", "area_name", "location_highlight", "coordinates",
  "image_url", "images": [],
  "amenities": [], "amenity_groups": {},
  "review_score", "review_count", "category_scores": {},
  "check_in_time", "check_in_until", "check_out_time", "reception_open_until",
  // shape đã xác nhận 06/08/2026 — KHÔNG có thời lượng, chỉ có khoảng cách.
  // distance_text/category là chuỗi VI đã format trong DB: truyền qua nguyên vẹn,
  // frontend dựng lại từ distance_km cho đúng locale.
  // Tên field là "attractions" nhưng nội dung gồm cả sân bay, bến xe...
  "nearby_attractions": [{ "name", "category", "coordinates", "distance_km", "distance_text" }],
  "nearby_essentials": [],
  "lowest_price", "currency",
  "rooms": [{
    "id", "name", "bed_description", "room_size_sqm", "max_guests", "view",
    "room_facilities": [], "images": [],
    "price": { "amount", "currency", "check_in_date", "check_out_date",
               "sold_out", "package_details" }   // null nếu không có dòng room_prices
  }]
}
```

### Mới — `GET /api/v1/attractions/{attraction_id}` (Phase 3)

Phục vụ Place Detail Focus Mode. Frontend lấy id từ
`trip_plan.days[].items[].reference_id` khi `reference_type == "attraction"`. `404` nếu
không có.

```jsonc
{
  "id", "name", "description", "category", "is_tour",
  "estimated_duration_minutes", "opening_time", "closing_time",
  "ticket_price_adult", "ticket_price_child",
  "rating", "review_count", "coordinates", "images": []
}
```

### Mới — `GET /api/v1/chat/sessions` (Phase 4)

Phục vụ rail lịch sử hội thoại.

```jsonc
{ "sessions": [{
    "session_id", "title",              // suy ra: "Đà Nẵng – Hội An 4N3Đ"
    "destination", "duration_days",
    "status": "draft" | "completed",    // completed khi đã có trip_data
    "created_at", "updated_at",
    "thumbnail_url"                     // image_url của khách sạn đã chọn, hoặc null
}]}
```

### Mới — `GET /api/v1/chat/{session_id}/restore` (Phase 4)

Mở lại một hội thoại cũ. Cùng shape với `PlannerChatResponse`, thêm luồng tin nhắn:

```jsonc
{ "session_id", "messages": [{ "role": "user"|"ai", "text", "stage", "at" }],
  "suggestions": [], "stage", "hotel_options": [], "trip_plan", "intake" }
```

### Mở rộng — `trip_plan.days[].items[]` (Phase 2)

`recalculate_itinerary_routes` (`routing.py:93`) đã tính và lưu route lên itinerary item,
nhưng `to_trip_plan_payload` không copy sang payload — **đúng cùng một kiểu cắt bỏ như
`hotel_options`**. Bổ sung:

```jsonc
{
  // đã trả về sẵn, chỉ thiếu trong types.ts
  "coordinates": "16.0678,108.2208",

  // MỚI — từ routing.py, dữ liệu Mapbox Directions thật
  "route_to_next": {
    "distance_km": 6.4,               // khoảng cách đường bộ thật
    "duration_mins": 14.2,            // thời lượng thật (Phase 12 xoá hệ số 2.5 cũ)
    "polyline": "yseeAo...",          // encoded polyline, precision 1e5, overview=full
    "profile": "driving-traffic"      // MÃ profile đã gọi: driving-traffic|walking|cycling
  } | null,

  "route_from_hotel": { … } | null   // chỉ item đầu ngày; null sau round-trip DB (mục 15)
}
```

`polyline` là chuỗi Google Encoded Polyline (precision 1e5). Mapbox trả cùng định dạng với
OSRM (`geometries=polyline` mặc định), nên frontend giải mã bằng hàm port từ
`backend/src/airflow/dashboard/templates/index.html:769-795` — **đã có sẵn bản chạy được,
không cần sửa khi đổi nhà cung cấp**.

`profile` là **mã**, không phải chuỗi hiển thị. Frontend dựng nhãn phương tiện qua i18n
(`routeProfile.walking` → "đi bộ"). Cùng nguyên tắc với `match_reasons`.

`route_to_next` là `null` khi: thiếu toạ độ ở một trong hai đầu, routing API lỗi/timeout,
hoặc không tìm được tuyến. Frontend **bắt buộc** phải có fallback đường thẳng cho mọi
trường hợp đó — xem `index.html:874-876` làm mẫu.

Trường hợp hai điểm trùng toạ độ, `get_route_to_next` trả `{0.0, 0.0, "", profile: null}`
chứ **không** trả `null` (`routing.py:84-89`). Frontend phải phân biệt "cùng chỗ, không cần
di chuyển" với "không có dữ liệu route" — hai trạng thái hiển thị khác nhau.

### Câu hỏi mở

**Hạn mức và chi phí Mapbox.** Directions API giới hạn 300 request/phút; một chuyến 4 ngày
≈ 24 request và `lru_cache` khiến việc chạy lại gần như miễn phí. Nhưng **hạn mức free tier
và đơn giá cần được kiểm tra trên trang giá Mapbox trước khi lên production** — chính sách
giá thay đổi theo thời gian nên plan này không ghi con số cụ thể. Nhớ bật cảnh báo quota
trong dashboard Mapbox, cho **cả** Directions API lẫn map loads (tile).

## Lấy gì từ bản design prototype

`data/trip_planner/trip_planner_components/` là app chạy được, nên câu hỏi "có copy code từ
đó không" là câu hỏi thật. Trả lời: **có, ba thứ cụ thể — và có một thứ tuyệt đối không.**

Bản thân các file `.dc.html` **không port được**: chúng là markup inline-style với binding
`{{ }}`/`sc-if`/`sc-for` chạy trên runtime riêng (`support.js`), không phải React, không
TypeScript, không build step. Cái lấy được nằm ở `scripts/` và `styles/`.

### Được lấy

| Nguồn | Dùng ở | Ghi chú |
|---|---|---|
| `styles/variables.css`, `theme.css`, `animation.css` | Phase 1 | **Chép nguyên văn** vào `frontend/src/styles/`, alias bằng `@theme inline`. Không dịch tay giá trị — xem Phase 1 §Nguồn token |
| `styles/global.css`, `layout.css` | — | **Không chép.** `global.css` đè font stack đã chọn; `layout.css` chứa hack `filter:var(--tile)` giả dark mode mà Phase 10 loại bỏ |
| Inline style trong `*.dc.html` | Phase 6-10 | **Giá trị** thì lấy (đã trích sẵn vào `design-fidelity-checklist.md`); **chuỗi `style=""`** thì không chép vào JSX — mở rộng bộ `@utility` glass của Phase 1 thay vì lặp công thức ~20 lần như bản export |
| `constants/config.js` → `DAY_COLORS`, `LEG_COLORS` | Phase 10 `lib/map-colors.ts` | Bảng màu chuẩn của design; Phase 9 `DayCard` dùng chung đúng bảng này |
| `utils/geo.js` → `kmFrom()` (haversine) | Phase 9 `lib/geo.ts` | Hàm thuần, ~6 dòng |
| `constants/i18n.js` (276 dòng vi/en) | Phase 6-11 catalog | **Lọc trước khi lấy** — lẫn chuỗi kịch bản hội thoại mock, không phải chuỗi UI |

### Không được lấy

| Nguồn | Vì sao |
|---|---|
| `constants/mock-data.js` | **Rủi ro số một.** Hotels/days/landmarks/convos giả, trông rất thật, nằm ngay cạnh thứ được lấy. Copy nó thì mọi tiêu chí "giống design" đều pass trong khi vi phạm nguyên tắc **không bịa dữ liệu** — và sẽ không ai phát hiện cho tới lúc demo với dữ liệu thật |
| `services/*.js` | Chúng đọc `window.VOTA.MockData` (xem `BACKEND_INTEGRATION.md` §1). Port service là kéo mock về theo cửa sau |
| `support.js` | Runtime của framework khác, 1911 dòng, vô nghĩa với React |
| `store/app-store.js`, `api/http-client.js` | Dự án đã có `use-theme`, `chat-client.ts`. Thêm lớp thứ hai là trùng lặp |
| `utils/geo.js` → **`curve()`** | Xem cảnh báo dưới |

### Cảnh báo: `curve()` là đồ hoạ nói dối

`geo.js:curve()` bẻ đoạn thẳng A→B thành cung bezier để "trông giống tuyến đường". Trong
prototype điều đó vô hại vì **mọi** route đều là giả.

Ở đây thì không. Phase 10 vẽ polyline Mapbox **thật**, và yêu cầu chặng fallback phải **nhìn
khác** chặng thật để người dùng phân biệt được. Dùng `curve()` cho nhánh fallback sẽ khiến một
đường nối ước lượng trông y hệt một tuyến đường có thật. Đó là bịa bằng đồ hoạ thay vì bằng
số — cùng loại với hệ số `× 2.5` (mục 2) và danh sách 6 bước tick (mục 14) mà plan đã loại bỏ.

Fallback vẽ **đường thẳng**, nét đứt thưa, màu nhạt. Đúng như Phase 10 §Route đã quy định.

### Hai lệch giá trị đã phát hiện trong `utils/formatters.js`

Ai port file này phải biết trước:

1. **Tiền tệ khác tài liệu i18n.** `formatters.vnd()` trả `"3.000.000đ"` (chữ `đ` dính liền),
   trong khi `Internationalization.md` và Phase 6 bước 2 quy định `"1.500.000 ₫"` (ký hiệu `₫`
   có khoảng trắng). `frontend/src/lib/format-currency.ts` **đã implement theo plan** — giữ
   nguyên. Bản design tự mâu thuẫn với tài liệu của chính nó ở điểm này.
2. **`countNights()` đếm sai theo tên của nó.** Nó trả `diff + 1` — tức là số **ngày**, không
   phải số đêm; trong khi `fmtNights()` cùng file lại tính đúng (n đêm / n+1 ngày). Port thẳng
   `countNights` là mang bug về. Số đêm dùng cho giá tổng khách sạn (Phase 8) nên sai chỗ này
   ra sai tiền.

## Nghiệm thu thị giác (3 lớp)

Tiêu chí dạng "khớp design" **không kiểm chứng được** — nó là ý kiến, do chính người viết code
tự chấm. Phase 6 đã chứng minh hậu quả: implement xong, typecheck sạch, lint sạch, 43/43 test
pass, mọi tiêu chí dữ liệu đạt — **và cột chat không có bề mặt glass nào cả**, còn shell thì
phủ màu đặc lên `--gradient-page`. Nội dung đúng, bề mặt biến mất, không tiêu chí nào bắt được.

Ba lớp dưới đây biến "khớp design" thành thứ đếm được.

### Lớp 1 — Token là **một bản gốc duy nhất**, gác bằng diff file

Cách chắc chắn nhất để giá trị token không lệch design là **không có bản thứ hai để mà lệch**.
Ba file CSS của design được chép vào `frontend/src/styles/` **nguyên văn**, rồi alias sang
namespace Tailwind bằng **`@theme inline`** (chi tiết + lý do `inline` là bắt buộc: Phase 1
§Nguồn token):

```css
@import "./styles/design-variables.css";   /* :root — token light */
@import "./styles/design-theme.css";       /* body[data-theme="dark"] — override dark */
@theme inline { --color-glass-1: var(--g1); --color-primary: var(--acc); /* … */ }
```

Gate `npm run check:tokens` (Phase 1 bước 8) vì vậy chỉ là **diff từng byte** ba file chép về
với bản gốc — không parse, không ánh xạ, không ngoại lệ. File chép mà bị sửa là sai theo định
nghĩa; muốn đổi giá trị thì đổi ở bản design rồi chép lại.

Script kiểm thêm một điều mà mắt không thấy: mọi `var(--xxx)` trong `@theme inline` phải tồn
tại thật trong `design-variables.css`. Alias trỏ vào biến không có là lỗi **im lặng** —
utility ra rỗng, không ai báo.

### Lớp 2 — Checklist bề mặt từng component (gate mỗi phase FE)

[`design-fidelity-checklist.md`](./design-fidelity-checklist.md) — trích từ chính các file
`.dc.html`, mỗi component một nhóm tick: token nền, blur, viền, shadow, radius, cỡ chữ chủ đạo,
animation vào.

Tick **trước khi** đánh dấu phase xong. Sai lệch có chủ đích thì ghi lý do ngay tại dòng đó,
không tick bừa. **Đây là lớp đáng giá nhất** — nó nhắm đúng loại lỗi Phase 6 vừa mắc: nội dung
đúng nhưng bề mặt không tồn tại.

### Lớp 3 — Ảnh cạnh nhau (Phase 11)

Bản design **chạy được**: `cd data/trip_planner/trip_planner_components && npm run dev` (server
node zero-dependency, mặc định `http://localhost:5173`). Không phải ảnh tĩnh — là app sống.

Chạy song song design và app thật, cùng viewport, cùng theme, cùng stage; chụp và đối chiếu ở
**4 breakpoint × 2 theme × 4 stage**. Ảnh tham chiếu có sẵn trong
`trip_planner_components/screenshots/` (`sb.png`, `hotel-focus.png`, `01-focus.png`,
`02-focus.png`, `dark.png`).

**Không** làm pixel-diff tự động: dữ liệu thật khác mock của design nên diff sẽ nhiễu tới mức
vô dụng. Mục tiêu là bắt lệch **cấu trúc** (thiếu panel, sai bố cục, sai thang bậc chữ), không
phải lệch từng pixel.

## Phần chưa làm (Not Implemented Register)

Ghi nhận theo yêu cầu: những gì design đòi hỏi mà plan này **không** làm. Không phần nào
là bỏ sót — mỗi phần đều thiếu nguồn dữ liệu hoặc là ranh giới phạm vi đã chấp nhận.

| # | Tính năng trong design | Tài liệu nguồn | Vì sao không làm | Thay bằng gì |
|---|---|---|---|---|
| 1 | Nhãn **cáp treo** cho chặng đi cáp | `UX Improvements.md` §5 | Mapbox Directions chỉ có 4 profile: `driving`, `driving-traffic`, `walking`, `cycling`. Không có cáp treo, và không có dữ liệu nào trong DB cho biết chặng nào đi cáp. | Ô tô / đi bộ **là thật** (Phase 12 gọi đúng profile tương ứng). Cáp treo không có nhãn riêng — chặng đó hiển thị như chặng ô tô hoặc đi bộ theo profile đã gọi |
| 2 | Thời lượng **chính xác tại thời điểm đi** | `UX Improvements.md` §5 | Route được tính lúc `persist_itinerary_bundle` chạy, không phải lúc người dùng thực sự di chuyển. `driving-traffic` phản ánh traffic **lúc lập lịch trình**. Với chuyến đi trong tương lai thì vẫn là ước lượng | Thời lượng **thật từ Mapbox** (hệ số bịa 2.5 đã bị xoá ở Phase 12), hiển thị có tiền tố `~`. Nâng cấp được sau bằng tham số `depart_at` với ngày giờ thật của lịch trình — ghi lại thành việc tiếp theo |
| 3 | Card "Yêu cầu đã thay đổi → Cập nhật / Giữ kết quả" | `Yêu cầu cập nhật thiết kế.md`, §Conversation State Management | Backend không phát ra diff có cấu trúc. `pending_trip_edit_request` chỉ là text tự do, không phải diff theo từng field kèm phạm vi ảnh hưởng. | Bỏ. Thay bằng danh sách `trip_plan.adjustments[]` đang có sẵn — đây mới là bản ghi thật của các thay đổi đã áp dụng |
| 4 | Chọn phòng làm cập nhật tổng giá / AI Summary | `Hotel Detail Focus.md` §Room Selection | `select_hotel` chỉ nhận số thứ tự khách sạn. Không có verb chọn phòng, cũng không có logic tính lại giá theo phòng. | Danh sách phòng hiển thị **chỉ đọc** với dữ liệu `room_prices` thật; mở rộng card phòng vẫn hoạt động; **không có nút "Chọn phòng"** |
| 5 | Đoạn văn "AI Summary" cho khách sạn và địa điểm | `Hotel/Place Detail Focus.md` §AI Recommendation | Cần gọi LLM cho từng thực thể — độ trễ và chi phí ngoài phạm vi plan, và sẽ sinh ra câu chữ không kiểm chứng được | Bullet đã dịch, dựng từ `match_reasons` — tức là các tham số ranking thật |
| 6 | "Đánh giá nổi bật" của địa điểm (trích dẫn review) | `Place Detail Focus.md` | Bảng `attractions` có `rating` và `review_count` nhưng **không có dòng nội dung review nào** | Chỉ hiển thị điểm số + số lượt đánh giá |
| 7 | "Gợi ý các địa điểm lân cận" | `Place Detail Focus.md` | Không tồn tại quan hệ địa điểm ↔ địa điểm lân cận. (`hotels.nearby_attractions` có; attractions thì không.) | Bỏ khỏi panel địa điểm. Panel khách sạn **vẫn có** `nearby_attractions` vì đó là dữ liệu thật |
| 8 | Shared Element Transition / FLIP morph thật | cả 4 tài liệu Focus/Motion | Cần thư viện motion (Framer Motion, hoặc View Transitions API kèm fallback rộng). Bản thân file export cũng chỉ dùng CSS transition + keyframes | Transition CSS `transform`/`opacity`/`blur`/`cubic-bezier` trên container dùng chung — nhìn rất gần, nhưng về cơ chế không phải FLIP morph |
| 9 | Slider ngân sách dạng số, 500k–50M VNĐ | `UX Improvements.md` §3 | Backend intake match **nhãn mức closed-set** bằng regex (`hotel_selection.py:509-531`). Dải liên tục đòi hỏi làm mới NLU backend. **Quyết định của người dùng.** | Chip mức ngân sách dạng glass, giữ nguyên giá trị wire chuẩn |
| 10 | Địa danh trên bản đồ theo ngôn ngữ giao diện | `Internationalization.md` §Map Localization | Tile OSM hiển thị tên theo ngôn ngữ bản địa; không điều khiển được nếu không dùng nhà cung cấp tile có localization (trả phí) | Chỉ lớp overlay của mình (legend, nhãn phương tiện, controls) được dịch — đúng phần mà tài liệu thực sự yêu cầu |
| 11 | `awards[]`, `warnings[]`, chi tiết `category_scores` của khách sạn | — (không có trong design) | Có trong DB và endpoint mới vẫn trả về, nhưng design không có chỗ hiển thị | Endpoint `GET /hotels/{id}` vẫn trả, UI không dùng. Làm thêm sau rất rẻ nếu muốn |
| 12 | Ngôn ngữ hội thoại tách khỏi ngôn ngữ giao diện (tự nhận diện) | `Internationalization.md` §AI Conversation | Đã đáp ứng một phần: `language` được truyền theo từng lượt và prompt LLM đã được localize. Việc *nhận diện* ngôn ngữ theo từng tin nhắn là hành vi NLU backend, không phải việc của UI | Giữ nguyên hành vi hiện tại, không mở rộng |
| 13 | Ô thống kê **tổng ngân sách / tổng chi phí** ở tab Tổng quan | `V-OTA_Frontend_Design_Specification.md` §Panel 2 Tab Tổng quan | `TripPlanPayload` không có trường chi phí nào (`schemas.py:121-133`). Giá chỉ tồn tại trên `hotel_options[]` trong lúc chọn khách sạn và không được chuyển sang `trip_plan`. Không suy ra được sau khi đã chốt lịch trình | Bỏ hẳn ô đó. Các ô còn lại (số ngày, số điểm, khách sạn, tổng quãng đường `≈`) đều tính được từ dữ liệu thật |
| 14 | Danh sách **6 bước AI Searching có dấu tick tuần tự** ("✓ Phân tích điểm đến", "✓ Tìm khách sạn phù hợp", …) | `Yêu cầu cập nhật thiết kế.md` §AI Searching State | Backend không phát ra tiến độ theo bước — chỉ có `pending: true` và thời gian đã trôi. Tick tuần tự sẽ là tuyên bố tiến độ bịa. Cùng tiền lệ đã loại bỏ "DeepDive Thinking" trong plan Stitch trước đó | Một trạng thái đang xử lý + số giây thật đã trôi + skeleton card + progress vô hạn (indeterminate). Nếu backend sau này phát ra tiến độ thật thì thêm vào được mà không đổi gì khác |
| 15 | Route **chặng đầu tiên mỗi ngày** (khách sạn → điểm đầu) sau khi đọc lại từ DB | — (lỗ hổng phát hiện khi rà `routing.py`) | `recalculate_itinerary_routes` **có** tính `route_from_hotel` (`routing.py:127`), nhưng `ITEM_RPC_FIELDS` (`itinerary_store.py:47-60`) **không chứa** `route_from_hotel` nên nó bị lọc bỏ trước khi persist. Chỉ `route_to_next` được lưu. Sau một vòng round-trip DB, chặng đầu mỗi ngày mất route | Chặng đầu ngày dùng **fallback đường thẳng** như mọi chặng lỗi routing khác. **Sửa được rất rẻ** — thêm `route_from_hotel` vào `ITEM_RPC_FIELDS` — nhưng cần migration/RPC phía DB nên để ngoài phạm vi plan này. Ghi lại thành việc tiếp theo |
| 16 | Chip/textarea chọn **đi cùng ai, nhịp độ, nhịp sinh hoạt, ghi chú** trong khối intake ("Tuỳ chọn khác" ở form cũ) | — (có trong bản pre-Phase-6 của `intake-parameters-form.tsx`, không có tài liệu design riêng) | Phase 6 chỉ định nghĩa 5 component progressive-disclosure (destination/people/dates/budget/preferences) khớp 5 field trong `intake.missing` + budget. Bốn field này không nằm trong bộ đó và không có card thay thế nào được dựng. Phát hiện sau khi refactor xong, không phải quyết định trước. | `composeIntakeMessage()` (không đổi) vẫn phát đúng câu `Đi cùng:` / `Nhịp độ:` / `Nhịp sinh hoạt:` / `Ghi chú:` nếu 4 field đó có giá trị — chỉ là không còn UI chip/textarea để set trực tiếp. Người dùng vẫn khai báo được qua chat tự do; nếu backend NLU trích xuất được vào `intake.companions/pace/day_rhythm/notes`, form sẽ seed lại đúng giá trị đó (`intake-parameters-form.tsx` seed effect) và câu composed vẫn giữ nguyên. Khôi phục UI có cấu trúc cho 4 field này là việc tiếp theo nếu cần |

| 17 | **"Đánh giá nổi bật" của khách sạn** — card review có avatar, tên người, thời điểm, điểm, nội dung | `HotelDetail.dc.html` §`dict.topReviews` | `hotels` chỉ select `review_score` + `review_count` (`hotel_selection.py:50`); **không có bảng/cột nào chứa nội dung review**. Mục 6 trước đây chỉ ghi cho *địa điểm*, bỏ sót panel khách sạn | Chỉ hiển thị điểm tổng + số lượt, giống hệt cách xử lý ở panel địa điểm |
| 18 | **Khối "Liên hệ"** của khách sạn (2 ô label/value ở cuối panel) | `HotelDetail.dc.html` §`hDet.contact` | Không có cột điện thoại/email/website trong `hotels`, và `GET /hotels/{id}` (Phase 3) không định nghĩa field nào cho việc này | Bỏ cả khối. Không suy ra từ `address` |
| 19 | **"cách trung tâm X km"** trên card và trên hero panel khách sạn | `HotelCard.dc.html`, `HotelDetail.dc.html` | Không có `distance_to_center`, và cũng **không có toạ độ "trung tâm"** của từng điểm đến trong DB. Tự chọn một điểm làm tâm rồi tính haversine là bịa một con số nghe như dữ liệu thật | Hiển thị `area_name` (dữ liệu thật) ở đúng chỗ đó. **`distToSights` trong panel chi tiết vẫn làm** vì nó dựa trên `nearby_attractions` thật — xem Phase 8 |
| 20 | **Khối "Tiện ích"** của địa điểm | `PlaceDetail.dc.html` §`dict.facilities` | `attractions` không có cột tiện ích/tiện nghi; `GET /attractions/{id}` (Phase 3) không có field tương ứng. Tiện nghi là dữ liệu của khách sạn, không phải của điểm tham quan | Bỏ khối. Panel địa điểm giữ mô tả, giờ mở cửa, giá vé, thời lượng — đều là thật |
| 21 | **Chính sách huỷ / thanh toán của từng phòng**, và ô "Phòng đã chọn" ở header panel | `RoomCard.dc.html` §`r.cancel`/`r.pay`, `HotelDetail.dc.html` §`dict.roomChosen` | `rooms`/`room_prices` không có cột chính sách huỷ hay thanh toán. Ô "Phòng đã chọn" là hệ quả trực tiếp của mục 4 (không có verb chọn phòng) | Badge tình trạng phòng **vẫn làm** — nó ánh xạ từ `price.sold_out` thật. Hai ô chính sách và ô "Phòng đã chọn" bị bỏ |

| 22 | **Nút "Chia sẻ"** ở header workspace | `V-OTA Planner.dc.html:207` | Nút không gắn với hành vi nào ngay trong design, và không có gì để chia sẻ: session không có URL công khai, `GET /chat/{session_id}/restore` (Phase 4) yêu cầu biết `session_id` và không có tầng phân quyền. Ship một nút bấm vào không làm gì là hứa hẹn suông. **Quyết định của người dùng 06/08/2026** | Bỏ nút. Header chỉ còn "Tạo lại". Khi nào có link chia sẻ thật (URL công khai + phân quyền) thì thêm lại rất rẻ |

| 23 | **Cột thời lượng** trong danh sách "khoảng cách tới điểm nổi bật" của panel khách sạn | `HotelDetail.dc.html` §`d.mins` | `nearby_attractions` chỉ có `distance_km`/`distance_text`, **không có thời lượng** (shape xác nhận 06/08/2026). Suy ra phút từ km đòi hỏi giả định tốc độ — đúng loại hệ số bịa mà Phase 12 vừa xoá khỏi `routing.py` | Render hai cột (tên · km) thay vì ba. Gọi routing cho từng mục lân cận là việc tiếp theo nếu thật sự cần |

## Rủi ro

| Rủi ro | Mức độ | Cách giảm thiểu |
|---|---|---|
| Contract lệch nhau giữa 2 track | Cao | `types.ts` + `mock/server.js` + `chat_api_contract.md` sửa cùng lúc hoặc không sửa; Phase 11 chạy frontend với backend thật trước khi nghiệm thu |
| Persist session làm hỏng chat graph | Cao | Loại `TripState.messages` (object LangChain) và `remaining_steps` khỏi serialize; đi qua đúng seam `persist_hook` có sẵn và mang tính **cộng thêm** — không bật hook thì hành vi y hệt hôm nay |
| `backdrop-filter` (glass/blur) chậm trên máy yếu | Trung bình | Giới hạn số lớp blur chồng nhau; tôn trọng `prefers-reduced-transparency` và `prefers-reduced-motion` |
| URL ảnh khách sạn là link ngoài, có thể 404 | Trung bình | Mọi ô ảnh phải có placeholder dự phòng — tái dùng pattern icon Material đang có |
| Viết lại layout làm hỏng luồng intake / chọn khách sạn đang chạy tốt | Cao | Chat contract, giá trị wire của `composeIntakeMessage`, và chọn khách sạn theo số thứ tự bị đóng băng tuyệt đối; Phase 11 chạy lại toàn bộ kịch bản hội thoại mock |
| Theme tối không đạt tương phản WCAG trên nền glass | Trung bình | Rà tương phản cho cả hai theme ở Phase 11 |
| **Token Mapbox lọt ra ngoài** | Cao | **Hai token tách biệt**: secret token phía server cho Directions (Phase 12, không bao giờ vào payload/log), public token có URL restriction cho tile trình duyệt (Phase 10). Không commit token nào. Không dùng chung |
| Vượt quota Mapbox | Trung bình | `lru_cache` đã có; 1 request/chặng nhờ lọc haversine cục bộ; bật cảnh báo quota cho cả Directions và map loads |

## Tiêu chí hoàn thành

- [ ] `docs/chat_api_contract.md` mô tả đủ mọi endpoint và payload ở trên; `types.ts` và `mock/server.js` khớp chính xác
- [ ] Dev frontend dựng được toàn bộ màn hình phase 5-10 chỉ với `npm run mock`
- [ ] Dev backend hoàn thành phase 2-4 mà không sửa file nào trong `frontend/`
- [ ] Shell sidebar → chat → stage hiển thị đủ 4 trạng thái stage và cả hai focus mode
- [ ] Có cả theme sáng và tối; toggle được lưu lại; không dùng đen/trắng tuyệt đối theo đúng tài liệu design
- [ ] Card khách sạn hiển thị ảnh thật, tiện nghi, điểm đánh giá và match score thật
- [ ] Hai focus mode đều chạy trên dữ liệu endpoint thật; không phải modal, không phải popup
- [ ] Map hiển thị marker và route theo ngày từ `coordinates` thật; hover đồng bộ hai chiều
- [ ] Route vẽ từ polyline Mapbox bám đường thật; leg pill có phương tiện + thời lượng thật
- [ ] Hệ số `× 2.5` đã bị xoá khỏi `routing.py`
- [ ] Hai token Mapbox tách biệt; không token nào bị commit hay lọt vào payload
- [ ] Lịch sử hội thoại liệt kê session đã persist thật và khôi phục được
- [ ] Mọi chuỗi đều được dịch; catalog `en` và `vi` đầy đủ; không còn text hardcode
- [ ] Hành vi cũ nguyên vẹn: vòng đời session, giá trị wire intake NLU, chọn khách sạn theo số thứ tự, xử lý lỗi
- [ ] `npm run typecheck`, `npm run lint` và test suite backend đều pass
- [ ] `check-design-tokens` pass; mọi lệch token còn lại đều có lý do được khai báo
- [ ] `design-fidelity-checklist.md` đã tick hết cho phase 5-10; dòng bỏ tick có ghi lý do
- [ ] Đã đối chiếu ảnh cạnh nhau với bản design đang chạy ở 4 breakpoint × 2 theme
- [ ] Mọi mục trong bảng "Phần chưa làm" hoặc đã được làm, hoặc vẫn còn liệt kê chính xác

<!-- slug: claude-design-ui-integration -->
