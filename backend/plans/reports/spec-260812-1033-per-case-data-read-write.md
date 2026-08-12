# Per-case data spec — what each capability READS and WRITES

Date: 2026-08-12 · No code changed · Grounded in `backend/scripts/database_schema.sql`

Notation: `state:` = canonical TravelState path (Phase 2) · `db:` = Postgres column ·
`calc:` = derived at runtime, not stored

## Findings that change earlier estimates

Reading the real schema moved five items:

| Item | Earlier call | Actual | Why |
|---|---|---|---|
| Sold out | ❌ gap | **cheap** | `room_prices.sold_out BOOLEAN` already exists and is populated by ETL |
| Giữ chỗ (hold) | ❌ gap | **impossible with current data** | Schema comment: *"không nguồn nào có số phòng trống, chỉ có cờ hết phòng"* — no room count exists, so nothing can be decremented |
| Tìm nhà hàng | ❌ gap | **cheap** | `attractions.category` already includes `'Nhà hàng'` |
| Địa điểm gần nhau <1km | ❌ gap | **cheap to read** | `itinerary_items.route_to_next JSONB {distance_km, duration_mins, polyline}` is already stored |
| Tổng ngân sách | ❌ gap | **half exists** | `itineraries.budget DECIMAL(12,2)` column exists; `_calculate_trip_budget` writes it. Only the *constraint* is missing |

Sold-out and hold are **not the same feature**. Displaying "hết phòng" is a read of existing
data. Holding a room requires inventory the product does not have and cannot derive.

---

## 1. Ngày tháng

### 1a. `01/07` thiếu năm · 1b. `31/07` thứ tự ngày/tháng · 1c. `1-2-2026`

| | |
|---|---|
| **Đọc** | `calc:` today's date (planning timezone) · user message |
| **Ghi** | `state: dates.start`, `dates.end` → `db: itineraries.start_date, end_date` |
| **Thiếu** | Validator phân biệt 3 kết quả: `VALID` / `REJECT(lý do)` / `AMBIGUOUS(câu hỏi)`. Hiện `_format_start_date:591` chỉ có VALID/REJECT |

Quy tắc cần chốt (hiện chưa có ở đâu):
- Không có năm → `AMBIGUOUS` → hỏi năm.
- Số đầu > 12 → chắc chắn DD/MM, resolve thẳng (`31/07`).
- Cả hai ≤ 12 và mơ hồ (`01/02`, `1-2-2026`) → **quyết định sản phẩm**: cố định DD/MM hay hỏi. Xem câu hỏi 3.
- Ngày quá khứ → `REJECT` với lý do nói rõ là ngày, không phải toạ độ.

### 1d. Ngày ngoài vùng dữ liệu (`1/7-7/7`)

| | |
|---|---|
| **Đọc** | `db: room_prices.check_in_date, check_out_date` (theo `destination_id`) · `db: hotels.price_check_in_date, price_check_out_date` |
| **Ghi** | Không ghi gì — đây là trạng thái báo lỗi |
| **Thiếu** | Truy vấn "vùng phủ dữ liệu" + thông điệp riêng |

Đây là **trạng thái thứ ba**: ngày hợp lệ về cú pháp, hợp lệ về thời gian, nhưng không có
dữ liệu giá. Hiện gộp chung với "không tìm thấy khách sạn" → báo *"Không tìm thấy khách sạn
có tọa độ hợp lệ"*, sai hoàn toàn về nguyên nhân.

Dữ liệu để phát hiện **đã có sẵn** — chỉ cần `SELECT min(check_in_date), max(check_out_date)`
theo điểm đến rồi so với khoảng user nhập, và đề xuất khoảng gần nhất có dữ liệu.

---

## 2. Lịch trình ngày 1 chọn thiên nhiên khám phá

| | |
|---|---|
| **Đọc** | `db: itineraries.day_themes` (JSONB `[{day_number,title,query}]`) · `db: itineraries.preferences`, `duration_days`, `destination_id`, `hotel_id` · `db: attractions` (theo `category`, `coordinates`, embedding) · `db: itinerary_items` của **ngày đó** |
| **Ghi** | `state: daily_preferences.1.theme` → `db: itineraries.day_themes[day=1]` (+ `selection_mode:"user_specified"`) · `db: itinerary_items` **chỉ day_number=1** · `db: itineraries.updated_at, status='Draft'`, `budget` tính lại |
| **Không được đụng** | `itinerary_items` các ngày khác · `itineraries.hotel_id` · `planning_constraints` |

Bug hiện tại: `normalize_day_themes:534` ghi đè `query` bằng preference cũ → ghi đúng `title`
nhưng sai `itinerary_items`.

---

## 3. Search theo tiện ích, kết hợp nhiều tiện ích

| | |
|---|---|
| **Đọc** | `db: hotels.amenities TEXT[]` (VD `{"Hồ bơi","Spa","Wifi"}`) · `db: hotels.amenity_groups JSONB` · `db: rooms.room_facilities TEXT[]` · `db: hotel_amenity_catalog` (tag đã duyệt) |
| **Ghi** | `state: hotel_preferences.amenities: []` — thao tác `append` / `remove`, không phải chỉ `set` |
| **Thiếu** | gym/spa **không có** trong `_AMENITY_KEYWORD_TAGS` (7 tag) dù `hotels.amenities` chứa `"Spa"` thật · ngữ nghĩa AND/OR chưa chốt · chưa là filter |

Lưu ý: tiện ích phòng (`rooms.room_facilities`) tách khỏi tiện ích khách sạn
(`hotels.amenities`). "Có gym" là khách sạn; "có bồn tắm" là phòng. Hai nguồn khác nhau —
cần quyết định tag nào tra ở bảng nào.

---

## 4. Khách sạn trong bán kính 3km

| | |
|---|---|
| **Đọc** | `db: hotels.coordinates VARCHAR(50)` (`'10.762622, 106.660172'`) · tâm: `db: itineraries.hotel_id` → `hotels.coordinates`; hoặc `attractions.coordinates` nếu user nêu địa danh |
| **Ghi** | `state: hotel_preferences.radius_km`, `hotel_preferences.center {type, id, lat, lng}` |
| **Thiếu** | `recommend_hotels` không truyền `max_radius_km` xuống · chưa có hàm resolve tâm |

`coordinates` là **VARCHAR chuỗi**, không phải PostGIS geography. RPC hiện đã parse và tính
khoảng cách được (`validate_radius_filter`), nên không cần đổi kiểu — nhưng cũng có nghĩa là
không có index không gian, và bán kính là quét tuyến tính trong phạm vi `destination_id`.

---

## 5. Booking — tách làm 3 phần rất khác nhau

### 5a. Sold out — **làm được ngay**

| | |
|---|---|
| **Đọc** | `db: room_prices.sold_out BOOLEAN` · `db: hotels.rooms_available BOOLEAN` |
| **Ghi** | Không ghi — chỉ hiển thị và loại khỏi kết quả |
| **Thiếu** | Chỉ cần đọc cột đã có. Hiện `search_hotels_with_rooms` không lọc theo cột này |

### 5b. Handoff booking — **làm được ngay**

| | |
|---|---|
| **Đọc** | `db: room_prices.source_url` (link affiliate/đặt phòng), fallback `db: hotels.source_url` |
| **Ghi** | Không ghi |
| **Thiếu** | Chỉ cần đưa link ra UI. Đây là handoff sang OTA, không phải đặt phòng nội bộ |

### 5c. Giữ chỗ (hold) — **không làm được với dữ liệu hiện tại**

Schema nói thẳng: *"không nguồn nào có số phòng trống, chỉ có cờ hết phòng"*. Không có số
phòng thì không thể trừ, không thể giữ, không thể hết hạn hold. Muốn làm cần một nguồn
inventory thật (API OTA có booking, hoặc kho phòng của chính mình) — đây là thay đổi sản phẩm,
không phải thay đổi code.

### 5d. Lock lịch trình, không cho người khác xem — **bị chặn bởi thiếu nền**

| | |
|---|---|
| **Đọc** | Cần `user_id` — **không tồn tại** |
| Hiện có | `db: sessions.session_id VARCHAR PRIMARY KEY` (không có `user_id`) · `db: itineraries.session_id` |

Quyền sở hữu hiện tại là **theo session ẩn danh**. Ai có `session_id` thì xem được; không ai
khác xem được. Nếu định nghĩa "không cho người khác xem" = "người dùng khác không thấy" thì
**điều đó đã đúng sẵn**. Nếu nghĩa là chia sẻ có kiểm soát / khoá chủ động, cần bảng user +
`itineraries.user_id` + model visibility — plan riêng. Xem câu hỏi 5.

---

## 6. Ngân sách

### 6a. Giá phòng/đêm (đã có)

| | |
|---|---|
| **Đọc** | `db: room_prices.price` theo `check_in_date/check_out_date` · `db: hotels.lowest_price` (cache) |
| **Ghi** | `state: budget.min/max/target` |

### 6b. Tổng ngân sách dưới 3tr / trong tầm giá 3tr

| | |
|---|---|
| **Đọc** | `db: room_prices.price × số đêm` · `db: attractions.ticket_price_adult, ticket_price_child` · `db: itineraries.number_of_adults, number_of_children` |
| **Ghi** | `state: budget.trip_total_max` (mới) · `db: itineraries.budget` (cột **đã có**) |
| **Thiếu** | Ràng buộc + vòng lặp replan khi vượt |

`_calculate_trip_budget:458` đã cộng đúng khách sạn + item có giá. Cột `itineraries.budget`
đã tồn tại. Thiếu duy nhất: coi nó là **ràng buộc** chứ không phải kết quả.

Phân biệt hai cách nói:
- *"dưới 3tr"* → trần cứng, vượt thì phải replan.
- *"trong tầm giá 3tr"* → mục tiêu mềm, dùng để xếp hạng (giống `target_price` hiện có).

Hai ngữ nghĩa khác nhau, cần hai path khác nhau.

---

## 7. Đánh giá trên 4 sao

| | |
|---|---|
| **Đọc** | `db: hotels.star_rating DECIMAL(2,1)` · `db: hotels.review_score DECIMAL(4,2)` · `db: hotels.review_count` |
| **Ghi** | `state: hotel_preferences.min_star_rating` và/hoặc `min_review_score` |
| **Thiếu** | Chưa có trong `ALLOWED_PATHS` · `supabase_search.py:281` **âm thầm bỏ filter** khi rỗng |

Hai cạm bẫy dữ liệu:
- `star_rating = 0` nghĩa là **chưa xếp hạng**, không phải kém. Lọc `>= 4` sẽ loại luôn nhóm
  chưa xếp hạng — cần quyết định có đúng ý không.
- `star_rating` có nửa sao (3.5). `review_score` thang 0–10. "Trên 4 sao" mơ hồ giữa hai cột.

---

## 8. Tìm nhà hàng xung quanh

| | |
|---|---|
| **Đọc** | `db: attractions WHERE category = 'Nhà hàng'` · `coordinates`, `rating`, `opening_time`, `closing_time`, `ticket_price_adult` · tâm: `itineraries.hotel_id → hotels.coordinates`, hoặc `itinerary_items.reference_id` của điểm đang xem |
| **Ghi** | Không ghi nếu chỉ tra cứu · nếu thêm vào lịch: `db: itinerary_items` (day_number, order_index, reference_id, start/end_time) |
| **Thiếu** | Tool tìm kiếm độc lập. Nhà hàng hiện chỉ xuất hiện qua query cố định trong slot bữa ăn (`trip_planner.py:334-374`) |

Dữ liệu **đã có sẵn** — `category` đã liệt kê `'Nhà hàng'` trong schema. Chỉ thiếu bề mặt tool.

---

## 9. Khách sạn sang trọng / bình dân / giá hợp lý

| | |
|---|---|
| **Đọc** | `db: hotels.star_rating`, `lowest_price`, `room_prices.price` |
| **Ghi** | `state: budget.min/max/target` qua `_QUALITATIVE_BUDGET_PHRASES` |
| **Thiếu** | `"giá hợp lý"` không có trong danh sách cụm từ (đang có `vua tui tien`, `vua phai`, `tam trung`) |

Chỉ là thêm cụm từ vào bảng ánh xạ — đúng nghĩa "mở rộng bằng data".

---

## 10. Đổi địa điểm / gợi ý phù hợp / đổi nhiều địa điểm

| | |
|---|---|
| **Đọc** | `db: itinerary_items` (id, day_number, order_index, reference_id, start_time, end_time) · `db: attractions` (embedding, category, coordinates, opening/closing, duration) · `db: itineraries.day_themes` |
| **Ghi** | `db: itinerary_items` — sửa `reference_id`, `activity`, giờ, `order_index`, `route_to_next` · `db: itineraries.updated_at`, `budget` |
| **Đã chạy được** | `replace_item`; nhiều thao tác trong một plan hợp lệ (`trip_edit_planner.py:409-411` chỉ cấm với `change_hotel`/`update_trip_preferences`) |
| **Thiếu** | "Gợi ý địa điểm phù hợp" — hiện thay thẳng, không đưa danh sách để chọn. Chỉ khách sạn mới có luồng chọn |

Muốn có luồng chọn cho địa điểm cần một `pending_place_selection` song song với
`pending_hotel_selection` đã có.

---

## 11. Ràng buộc theo ngày

### 11a. Giới hạn N địa điểm/ngày

| | |
|---|---|
| **Đọc** | `db: itinerary_items` đếm theo `day_number` (loại các `item_kind` bữa ăn/nghỉ) |
| **Ghi** | `db: itineraries.planning_constraints.max_items_per_day` (JSONB, cột **đã có**) |
| **Thiếu** | Key mới + hàm applier trong scheduler |

`planning_constraints` hiện chỉ có 4 key: `latest_outing_start_by_day`,
`latest_outing_end_by_day`, `meal_preferences`, `meal_preferences_by_day`. Cấu trúc lưu trữ
đã sẵn — thêm key là chuyện data, viết applier là chuyện code.

Lưu ý xung đột: `MINIMUM_ITEMS_PER_DAY = 7` (`itinerary_reuse.py:19`) khiến ngày có ít item
không bao giờ được tái dùng làm template. Không chặn tính năng, nhưng nên quyết định có ý thức.

### 11b. Các địa điểm gần nhau dưới 1km

| | |
|---|---|
| **Đọc** | `db: itinerary_items.route_to_next JSONB {distance_km, duration_mins, polyline}` — **đã lưu sẵn** · `db: attractions.coordinates` khi chọn ứng viên |
| **Ghi** | `db: itineraries.planning_constraints.max_leg_distance_km` |
| **Thiếu** | Ràng buộc lúc **chọn ứng viên** (trước khi xếp lịch), không phải kiểm tra sau |

`distance_km` đã được tính và lưu cho từng chặng → kiểm tra vi phạm là truy vấn thuần. Cái
khó là đưa ràng buộc vào bước chọn ứng viên để không sinh ra lịch vi phạm ngay từ đầu.

---

## 12. Từ chối ngoài phạm vi (toán, code, vé máy bay)

| | |
|---|---|
| **Đọc** | Chỉ nội dung tin nhắn |
| **Ghi** | Không ghi gì — **quan trọng**: một lượt bị từ chối không được đụng vào state |
| **Thiếu** | Toàn bộ. `guardrails/jailbreak.py:56-69` chỉ chặn 4 loại prompt-injection |

Đây là capability **không đọc và không ghi dữ liệu nào** — nên nó độc lập hoàn toàn với mọi
phase khác và làm được ngay.

---

## Tổng hợp theo chi phí

| Nhóm | Case | Vì sao |
|---|---|---|
| **Rẻ — dữ liệu đã có, chỉ thiếu nối** | sold out (5a), handoff link (5b), tìm nhà hàng (8), "giá hợp lý" (9), bán kính (4), vùng phủ ngày (1d) | Cột đã tồn tại và đã được ETL đổ dữ liệu |
| **Vừa — có nơi lưu, thiếu logic** | tổng ngân sách (6b), rating filter (7), giới hạn/ngày (11a), khoảng cách chặng (11b), theme ngày (2) | `itineraries.budget`, `planning_constraints`, `day_themes`, `route_to_next` đều đã có |
| **Vừa — cần bề mặt mới** | gợi ý địa điểm để chọn (10), tiện ích thành filter (3) | Cần `pending_place_selection`; cần taxonomy gym/spa |
| **Rẻ và độc lập** | từ chối ngoài phạm vi (12) | Không đọc/ghi dữ liệu |
| **Chặn bởi dữ liệu** | giữ chỗ (5c) | Không có số phòng — không thể giữ thứ không đếm được |
| **Chặn bởi nền tảng** | khoá/riêng tư (5d) | Không có `user_id` |

---

## Câu hỏi chưa giải

1. **"Trên 4 sao"** — `star_rating` (1–5, có nửa sao, 0 = chưa xếp hạng) hay `review_score` (0–10)? Và `star_rating = 0` nên loại hay giữ?
2. **Nhiều tiện ích** — AND (phải có đủ) hay OR (có cái nào cũng được)? AND đúng nghĩa "kết hợp" nhưng trên dataset này sẽ ra rỗng thường xuyên.
3. **`1-2-2026`** — cố định quy tắc DD-MM-YYYY, hay `interrupt()` hỏi mỗi lần?
4. **Tiện ích phòng vs khách sạn** — `rooms.room_facilities` và `hotels.amenities` là hai nguồn. Tag nào tra ở đâu?
5. **"Không cho người khác xem"** — per-session isolation hiện tại đã đủ chưa, hay cần user thật + chia sẻ có kiểm soát?
6. **"Giữ chỗ"** — có nguồn inventory thật không? Nếu không, có chấp nhận chỉ làm 5a + 5b (sold out + handoff link) và bỏ hold?
7. **`MINIMUM_ITEMS_PER_DAY = 7`** — giữ gate tái dùng và chấp nhận ngày thưa không bao giờ thành template?
