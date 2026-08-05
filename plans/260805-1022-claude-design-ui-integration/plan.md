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
| 1 | [API Contract & Design Tokens](./phase-01-api-contract-and-design-tokens.md) | Chung | Pending | — |
| 2 | [Mở rộng payload khách sạn](./phase-02-be-hotel-option-payload.md) | Backend | Pending | 1 |
| 3 | [Endpoint chi tiết khách sạn & địa điểm](./phase-03-be-detail-endpoints.md) | Backend | Pending | 1 |
| 4 | [Persist session & lịch sử hội thoại](./phase-04-be-session-persistence.md) | Backend | Pending | 1 |
| 12 | [Chuyển OSRM → Mapbox Directions](./phase-12-be-mapbox-routing.md) | Backend | Pending | 1 |
| 5 | [Design system & App Shell](./phase-05-fe-design-system-and-shell.md) | Frontend | Done | 1 |
| 6 | [Chat panel cố định](./phase-06-fe-chat-panel.md) | Frontend | Pending | 5 |
| 7 | [Stage: Intake & Generating](./phase-07-fe-stage-intake-generating.md) | Frontend | Pending | 5 |
| 8 | [Stage: Khách sạn & Hotel Focus](./phase-08-fe-stage-hotels-focus.md) | Frontend | Pending | 5 |
| 9 | [Stage: Workspace & Place Focus](./phase-09-fe-stage-workspace-focus.md) | Frontend | Pending | 5 |
| 10 | [Leaflet Map & Route](./phase-10-fe-map.md) | Frontend | Pending | 9 |
| 11 | [Tích hợp & Kiểm thử](./phase-11-integration-verification.md) | Chung | Pending | 2,3,4,6,7,8,9,10,12 |

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
  "nearby_attractions": [], "nearby_essentials": [],
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
- [ ] Mọi mục trong bảng "Phần chưa làm" hoặc đã được làm, hoặc vẫn còn liệt kê chính xác

<!-- slug: claude-design-ui-integration -->
