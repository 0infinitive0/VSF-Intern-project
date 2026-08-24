---
phase: 8
title: "Tạo khách sạn mới (B2)"
status: done
priority: P1
effort: "1d"
dependencies: [7]
---

# Phase 8: Tạo khách sạn mới — B2

## Overview

Form một cột tạo khách sạn `source_platform='manual'` — loại duy nhất pipeline không
đụng tới (quyết định #1). Bản ghi mới có `embedding = NULL`, nên **bot chưa tìm thấy
cho tới khi chạy lại pipeline embedding** — màn phải nói rõ điều đó.

**Thiết kế bám theo:** artboard `B2 · TẠO KHÁCH SẠN MỚI`.

## Bám sát thiết kế — checklist đối chiếu 1:1

**Header:** breadcrumb `Quản trị · Khách sạn · Thêm mới` · tiêu đề
`Tạo khách sạn mới` · nút `Huỷ` · `Lưu nháp` · `Lưu và tạo phòng` (chính).

**Banner thông tin trên cùng** (biểu tượng `i`, nền `--acc-soft`):
`Khách sạn tạo tay sẽ không bị pipeline ghi đè.`

**Form 1 cột rộng ~760px, 3 nhóm có tiêu đề:**

1. `Thông tin cơ bản`
   - `Tên khách sạn` + nhãn nhỏ `ảnh hưởng tìm kiếm của bot` — mẫu
     `Boutique Hoi An Riverside`
   - `Loại hình` (select) — `Khách sạn boutique`
   - `Hạng sao` (select) — `★★★★`
   - `Mô tả` (textarea) + nhãn `ảnh hưởng tìm kiếm của bot` + bộ đếm
     `183 / 1.000 ký tự`
2. `Vị trí`
   - `Địa chỉ` + nhãn `ảnh hưởng tìm kiếm của bot` — `42 Nguyễn Phúc Chu, phường Minh An`
   - `Thành phố / Tỉnh` (select) — `Quảng Nam`
   - `Vĩ độ` `15.87721` · `Kinh độ` `108.32694`
   - Ô `Xem trước vị trí trên bản đồ`
3. `Giờ nhận / trả phòng`
   - `Giờ nhận phòng` `14:00` · `Giờ trả phòng` `12:00`

**Banner cảnh báo dưới nút lưu** (biểu tượng `!`, nền `--warn-soft`):
`Khách sạn mới chưa được embedding — bot chưa tìm thấy cho tới khi chạy lại pipeline.`

**Nhãn `ảnh hưởng tìm kiếm của bot`** xuất hiện đúng 3 chỗ ở B2: `Tên khách sạn`,
`Mô tả`, `Địa chỉ`. Đây là danh sách rút gọn của B3 — xem "Trường ảnh hưởng RAG".

## Trường ảnh hưởng RAG — nguồn sự thật

Lấy từ `TABLE_COLUMNS["hotels"]` trong `backend/src/airflow/dags/data_pipeline/embed_supabase_dag.py:56`:

```
name, accommodation_type, area_name, address, location_highlight, description, amenities
```

Đúng **7 cột** này. Sửa bất kỳ cột nào trong đó (hoặc tạo hàng mới) → phải
`SET embedding = NULL` rồi chạy lại DAG. Mọi cột khác (`star_rating`, `images`,
`check_in_time`, `coordinates`, `city`…) **không** ảnh hưởng.

**Backend tự so** cột đã đổi với danh sách này. Không để frontend quyết định, không
để admin bấm tay — cả hai đều sẽ lệch khi danh sách đổi. Đặt hằng số ở
`backend/src/api/admin/embedding_fields.py` kèm comment trỏ về file DAG.

> `_build_text` trong DAG ghi rõ: **chỉ nhánh `hotels` được phép đổi template**;
> `rooms`/`attractions` phải giữ nguyên byte-for-byte. Không đụng vào.

## Lệch giữa thiết kế và code — phải xử lý

| # | Thiết kế | Thực tế | Xử lý |
|---|---|---|---|
| L25 | Nút `Lưu nháp` | Không có trạng thái "nháp" trong schema | **Bỏ nút này.** Còn `Huỷ` · `Lưu và tạo phòng`. Thêm cột `status` chỉ để có nút nháp là phình schema cho một tính năng không ai yêu cầu |
| L26 | `Thành phố / Tỉnh` là select | `hotels.city` là `VARCHAR(100)` text tự do; có bảng `destinations` với `destination_id` FK | Select lấy từ `destinations`, ghi **cả hai**: `destination_id` (FK, dùng cho truy vấn chuẩn) và `city` (text, giữ tương thích với dữ liệu ETL). Cho phép nhập tự do nếu không khớp destination nào |
| L27 | `Loại hình` là select | `accommodation_type` là `VARCHAR(50)` tự do, ETL đổ giá trị khác nhau giữa Agoda/Booking | Select có `DISTINCT accommodation_type FROM hotels` làm gợi ý + cho nhập tự do (combobox). **Đây là cột ảnh hưởng RAG** — nhãn cảnh báo phải có |
| L28 | Nhãn `ảnh hưởng tìm kiếm của bot` chỉ ở 3 ô | Thực tế 7 cột (xem trên). B2 thiếu nhãn ở `Loại hình` | **Thêm nhãn vào `Loại hình`.** `area_name`, `location_highlight`, `amenities` không có trên B2 (chúng nằm ở B3) — đúng |
| L29 | `Vĩ độ` / `Kinh độ` hai ô riêng | `hotels.coordinates` là `VARCHAR(50)` dạng `'10.762622, 106.660172'` | UI hai ô, backend ghép thành `"{lat}, {lng}"` đúng định dạng đang dùng. Kiểm bằng `place_details`/`geo.ts` xem parser mong đợi gì |
| L30 | `Xem trước vị trí trên bản đồ` | Có `mapbox-gl` + `VITE_MAPBOX_ACCESS_TOKEN` | Dùng ảnh tĩnh Mapbox Static Images API — **không** nhúng `mapbox-gl` vào bundle admin (nó nặng, và Phase 3 đã chốt không kéo thư viện của app chat sang) |
| L31 | `Giờ nhận / trả phòng` là select | `check_in_time`/`check_out_time` là `VARCHAR(20)` | Select `HH:MM` bước 30 phút, lưu chuỗi `"14:00"` |
| L32 | Bộ đếm `183 / 1.000 ký tự` | `description` là `TEXT`, không giới hạn | Chặn mềm ở 1.000 ký tự đúng như thiết kế. Mô tả quá dài làm loãng vector embedding — giới hạn này có lý do thật, không phải giới hạn DB |

## Backend — hợp đồng API

```
POST /api/v1/admin/hotels
  body: {
    "name": "Boutique Hoi An Riverside",          // bắt buộc
    "accommodation_type": "Khách sạn boutique",
    "description": "...",                          // ≤ 1000 ký tự
    "star_rating": 4,                              // 0–5, bước 0.5
    "address": "42 Nguyễn Phúc Chu, phường Minh An",
    "destination_id": "uuid" | null,
    "city": "Quảng Nam",
    "latitude": 15.87721, "longitude": 108.32694,
    "check_in_time": "14:00", "check_out_time": "12:00"
  }
→ 201 {
    "id": "uuid",
    "source_platform": "manual",
    "source_hotel_id": 17,
    "embedding_state": "missing",
    "is_active": true
  }
→ 422 lỗi hợp lệ (theo trường)
```

Quy tắc ghi:

```python
source_platform  = "manual"                       # cố định, không nhận từ client
source_hotel_id  = nextval('manual_hotel_source_id_seq')   # Phase 1, BIGINT
embedding        = NULL                            # luôn, bản ghi mới chưa học
is_active        = True
coordinates      = f"{latitude}, {longitude}"      # L29
```

`source_platform` **không bao giờ** nhận từ request body — cho client tự đặt
`'booking'` là mở đường cho hàng giả lọt vào không gian dữ liệu ETL.

```
GET /api/v1/admin/destinations
→ 200 [{"id":"uuid","name":"Quảng Nam"}]           // cho select L26

GET /api/v1/admin/hotels/accommodation-types
→ 200 ["Khách sạn", "Khách sạn boutique", "Resort", ...]   // gợi ý L27
```

Audit: `action='hotel.create'`, `after` = payload đã chuẩn hoá.

## Frontend — màn hình B2

```
src/admin/pages/hotels/
  hotel-create-page.tsx
  hotel-basic-fields.tsx        dùng lại ở B3 tab Cơ bản
  hotel-location-fields.tsx     dùng lại ở B3 tab Vị trí
  rag-field-label.tsx           nhãn "ảnh hưởng tìm kiếm của bot"
  map-static-preview.tsx        L30
```

- `hotel-basic-fields.tsx` và `hotel-location-fields.tsx` **thiết kế để dùng lại
  cho B3** (Phase 9) — chúng nhận prop `lockedFields: string[]` (B2 truyền `[]`,
  B3 truyền danh sách cột ETL). Làm ngay từ đầu, đừng viết hai lần rồi hợp nhất.
- `Lưu và tạo phòng` → POST xong điều hướng tới `/admin/hotels/:id?tab=rooms`
  (Phase 10). Nếu Phase 10 chưa xong thì về `/admin/hotels/:id`.
- Xác nhận rời trang khi form đang dở (`beforeunload` + chặn navigate nội bộ).

## Related Code Files

- Modify: `backend/src/api/admin/hotels.py`
- Create: `backend/src/api/admin/embedding_fields.py`
- Modify: `backend/tests/test_api/test_admin_hotels.py`
- Create: `frontend/src/admin/pages/hotels/hotel-create-page.tsx` + 4 file con
- Modify: `frontend/src/admin/api/hotels-client.ts`, `router.tsx`
- Reference: `backend/src/airflow/dags/data_pipeline/embed_supabase_dag.py` (`TABLE_COLUMNS`), `frontend/src/lib/geo.ts` (định dạng toạ độ)

## Implementation Steps

1. Đọc `TABLE_COLUMNS` trong DAG, chép sang `embedding_fields.py` kèm comment.
2. Đọc `frontend/src/lib/geo.ts` xem `coordinates` được parse ra sao → khớp định dạng ghi.
3. Endpoint `POST /admin/hotels` + 2 endpoint tra cứu.
4. Test: tạo thành công · thiếu `name` (422) · `source_platform` truyền từ client bị bỏ qua · `source_hotel_id` tăng dần.
5. Dựng form theo checklist, bỏ L25.

## Success Criteria

- [x] Tạo khách sạn → hàng mới có `source_platform='manual'`, `embedding IS NULL`, `source_hotel_id` là số nguyên tăng dần
- [x] Gửi `"source_platform": "booking"` trong body → vẫn ra `manual`
- [x] Tạo 2 khách sạn liên tiếp → `source_hotel_id` khác nhau, không vi phạm `UNIQUE(source_platform, source_hotel_id)`
- [x] `coordinates` ghi ra parse được bằng đúng hàm app chat đang dùng
- [x] Khách sạn mới hiện ở B1 với `embedding_state = 'missing'` (chấm cam) — suy ra từ B1 (`admin_hotel_rows.hotel_embedded = embedding IS NOT NULL`, không sửa ở phase này) + `embedding` luôn NULL khi tạo tay
- [x] Khách sạn mới **không** xuất hiện trong `match_hotels_with_rooms` (vì `embedding IS NULL`) — đúng như banner cảnh báo (hành vi có sẵn của hàm match, không cần sửa ở phase này)
- [x] Không có nút `Lưu nháp` (L25)
- [x] Nhãn `ảnh hưởng tìm kiếm của bot` có ở đúng 4 ô: Tên, Loại hình, Mô tả, Địa chỉ (L28)
- [x] Bộ đếm ký tự chặn ở 1.000
- [x] Bản đồ xem trước không kéo `mapbox-gl` vào bundle admin (kiểm kích thước chunk — admin-*.js ~40KB, không có `mapbox-gl`/`mapboxgl` trong build output)

## Implementation Notes (post-review)

Triển khai xong + review bởi `code-reviewer` subagent, đã sửa các phát hiện quan trọng:

- **Trust boundary**: `destination_id` giờ typed `UUID | None` (không phải `str`) — id sai định dạng 422 thay vì 500 khi chạm DB FK constraint. `accommodation_type`/`address`/`city` giờ có `max_length` khớp cột DB (50/500/100) — tránh Postgres `22001` không được xử lý.
- **Vĩ độ/Kinh độ**: bắt buộc cả hai hoặc không cái nào (`model_validator`) — trước đó nhập lệch một ô sẽ âm thầm bỏ `coordinates` mà không báo.
- **`adminFetch`**: giờ hiểu `detail` dạng mảng (422 field errors của FastAPI) — trước đó mọi lỗi 422 hiện ra "Lỗi máy chủ (422)." không rõ trường nào sai. Sửa chung cho toàn bộ admin, không riêng B2.
- **`destination_id` khớp theo `city`**: chuyển việc match từ lúc gõ phím (có thể race với fetch `/admin/destinations` chưa xong) sang lúc bấm Lưu, match theo state `destinations` mới nhất.
- **Điều hướng sau khi lưu**: về `/admin/hotels` (B1) thay vì `/admin/hotels/:id` — route đó còn là `RouteStub` (Phase 9 chưa xây), điều hướng tới đó không xác nhận được gì.
- **CSV export**: `name`/`address`/`city` giờ escape ký tự đầu `=+-@` (formula injection) — B2 là đường đầu tiên biến các cột này thành do người nhập tay, trước đó luôn từ ETL.
- **`useId()`** cho id DOM trong `hotel-basic-fields.tsx`/`hotel-location-fields.tsx` — hai component này thiết kế để B3 mount cùng lúc nhiều field-group, id cứng sẽ đụng nhau.
- Debounce 500ms cho ảnh xem trước bản đồ (Mapbox Static Images API tính phí theo request).

Chưa sửa (deferred, có lý do): `list_accommodation_types` quét tối đa 5000 hàng thay vì `SELECT DISTINCT` qua view riêng — dữ liệu hiện tại (~1100 khách sạn) còn xa mức trần, chưa cần thêm migration cho việc này.

## Risk Assessment

| Rủi ro | Mức | Giảm thiểu |
|--------|-----|-----------|
| Client tự đặt `source_platform` → hàng giả lọt vào không gian ETL, bị pipeline ghi đè bất ngờ | **Cao** | Cố định ở server; test riêng |
| `source_hotel_id` trùng do đọc `nextval` sai cách (ví dụ `currval`) | Cao | Dùng `nextval` trong chính câu INSERT; test tạo liên tiếp |
| Định dạng `coordinates` lệch với parser hiện có → bản đồ app chat vỡ | Trung bình | Bước 2 của Implementation đọc parser trước |
| Nhúng `mapbox-gl` làm bundle admin phình | Trung bình | Dùng Static Images API; có mục kiểm trong Success Criteria |
| Admin tạo xong không hiểu vì sao bot chưa thấy khách sạn | Trung bình | Banner cảnh báo là bắt buộc, không được bỏ; nối tiếp bằng B7/C2 |
