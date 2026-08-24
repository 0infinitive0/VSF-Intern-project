---
phase: 10
title: "Quản lý phòng (B5)"
status: pending
priority: P1
effort: "1.5d"
dependencies: [9]
---

# Phase 10: Quản lý phòng — B5

## Overview

Tab `Phòng` bên trong B3. Bắt buộc, không phải tuỳ chọn: `bookings.room_id` trỏ vào
`rooms`, khách sạn không có phòng thì **không bán được** và bot không gợi ý.

**Thiết kế bám theo:** artboard `B5 · QUẢN LÝ PHÒNG (tab Phòng, drawer sửa phòng
đang mở)` và biến thể `B5 · trạng thái rỗng`.

## Bám sát thiết kế — checklist đối chiếu 1:1

**Header:** breadcrumb `Quản trị · Khách sạn · Silk Path Hà Nội · Phòng` ·
tiêu đề tên khách sạn · chip `✎ Tự nhập` · nút `+ Thêm phòng`.
Tabs như B3, tab `Phòng` đang chọn, badge `4`.

**Bảng phòng — cột:** `TÊN PHÒNG` · `SỨC CHỨA` · `GIƯỜNG` · `DIỆN TÍCH` ·
`TIỆN NGHI` · `ẢNH` · `GIÁ THẤP NHẤT` · `THAO TÁC`. Chiều cao dòng ≥ 52px.

Dữ liệu mẫu (`roomList`):

| Tên phòng | Sức chứa | Giường | Diện tích | Tiện nghi | Ảnh | Giá thấp nhất |
|---|---|---|---|---|---|---|
| Deluxe King | 2 khách | 1 giường đôi lớn | 32 m² | 8 tiện nghi | 4 ảnh | 1.200.000 ₫ |
| Panorama Studio | 2 khách | 1 giường đôi | 40 m² | 9 tiện nghi | **Chưa có ảnh** | 1.800.000 ₫ |

Ô `Chưa có ảnh` dùng `--warn-ink` weight 600 (cảnh báo mềm), ô có ảnh dùng `--t2`.

**Cột `THAO TÁC`:** nút `Giá theo ngày` (→ Phase 11) · `Sửa` (mở drawer).

**Chú thích dưới bảng:**
`Giá thấp nhất tính trên bảng giá theo ngày trong 30 ngày tới.`

**Drawer `Sửa phòng`** (trượt từ phải, nền kính, có `✕`):
- Phụ đề `Deluxe King · Silk Path Hà Nội`
- `Tên phòng` — `Deluxe King`
- `Sức chứa tối đa` (select) — `2`
- `Diện tích (m²)` — `32`
- `Mô tả giường` — `1 giường đôi lớn (King)`
- `Hướng nhìn` (select) — `Nhìn ra thành phố`
- `Tiện nghi phòng` — chip bật/tắt: `✓ Điều hoà` `✓ Minibar` `✓ Két an toàn`
  `Bồn tắm` `Ban công` `Bếp nhỏ`
- `Ảnh phòng` — vùng `Kéo thả ảnh vào đây`
- Nút `Huỷ` · `Lưu phòng`

**Trạng thái rỗng** (biểu tượng `!`):
- Tiêu đề: `Khách sạn chưa có phòng — chưa thể bán`
- Mô tả: `Bot sẽ không gợi ý khách sạn này cho khách vì không có phòng nào để đặt.
  Thêm ít nhất một phòng kèm giá theo ngày.`
- Nút `+ Thêm phòng đầu tiên`

Đây là trạng thái rỗng **nói rõ hậu quả**, không phải "Chưa có dữ liệu" chung chung.

## Trường phòng ảnh hưởng RAG

Từ `TABLE_COLUMNS["rooms"]` (`embed_supabase_dag.py:57`):

```
name, bed_description, view, room_facilities
```

Đúng **4 cột**. Sửa chúng → `rooms.embedding = NULL`. `max_guests`, `room_size_sqm`,
`images` **không** ảnh hưởng.

> ⚠️ Template text của `rooms` trong `_build_text` **phải giữ nguyên byte-for-byte** —
> vector đã lưu sinh từ nó. Chỉ nhánh `hotels` được phép đổi. Phase này không đụng DAG.

## Lệch giữa thiết kế và code — phải xử lý

| # | Thiết kế | Thực tế | Xử lý |
|---|---|---|---|
| L40 | `Kéo thả ảnh vào đây` (upload file) | **Không có object storage** trong dự án. `rooms.images` là `TEXT[]` chứa URL do crawler lấy về | **Đổi thành ô nhập URL + danh sách URL, có xoá và sắp xếp.** Không hứa upload không làm được. Ghi rõ trên UI: `Dán URL ảnh (chưa hỗ trợ tải ảnh lên)` |
| L41 | `Hướng nhìn` là select | `rooms.view` là `VARCHAR(255)` tự do | Combobox: gợi ý từ `DISTINCT view FROM rooms` + cho nhập tự do. **Là cột RAG** → phải có nhãn cảnh báo |
| L42 | `Sức chứa tối đa` là select | `max_guests SMALLINT`, và schema ghi rõ Agoda tính **chỉ người lớn**, Booking tính **tổng khách** — hai nguồn khác ngữ nghĩa | Select 1–10. Với phòng ETL, thêm tooltip nêu sự khác biệt này để admin không "sửa cho khớp" giữa hai nguồn |
| L43 | `Tiện nghi phòng` 6 chip mẫu | `rooms.room_facilities` là canonical id từ `amenity_catalog` với `scope IN ('room','both')` | Lấy từ catalog, lọc `scope`. Dùng lại nhóm/ánh xạ của Phase 9 |
| L44 | `GIÁ THẤP NHẤT 1.200.000 ₫` | `room_prices` là **một dòng mỗi đêm** (F2) | `min(price)` trên các đêm `check_in_date ∈ [hôm nay, hôm nay+30)` và `sold_out = false`. Không có dòng nào → hiện `Chưa có giá` màu `--warn-ink` |
| L45 | Nút `Sửa`/`Xoá` cho phòng | `bookings.room_id` là `ON DELETE RESTRICT` | Cho **xoá cứng** phòng **chỉ khi** không có booking nào trỏ tới (kể cả đã huỷ — vẫn là lịch sử). Có booking → 409 + gợi ý "đặt giá `Hết phòng` cho mọi ngày" thay vì xoá. Thiết kế không có nút Xoá ở cột thao tác — **không thêm** |
| L46 | Phòng của khách sạn ETL | `rooms` bị `ota_pipeline` upsert theo `UNIQUE(hotel_id, source_room_id)` | Cùng cơ chế quyết định #7: vẫn sửa được, có cảnh báo. Phòng admin tạo dùng `source_room_id = nextval('manual_room_source_id_seq')` (Phase 1) |

## Backend — hợp đồng API

```
GET /api/v1/admin/hotels/{hotel_id}/rooms
→ 200 { "items": [{
    "id": "uuid",
    "name": "Deluxe King",
    "max_guests": 2,
    "max_occupancy_raw": "2 người lớn",
    "bed_description": "1 giường đôi lớn (King)",
    "room_size_sqm": 32,
    "view": "Nhìn ra thành phố",
    "room_facilities": ["air_conditioning","minibar","safe"],
    "facility_count": 8,
    "images": ["https://..."], "image_count": 4,
    "available_room_count": 5,
    "lowest_price_30d": "1200000.00",     // null nếu chưa có giá  (L44)
    "currency": "VND",
    "embedding_state": "embedded",
    "is_manual": true,
    "booking_count": 3                     // để quyết định cho xoá hay không (L45)
  }] }
```

```
POST   /api/v1/admin/hotels/{hotel_id}/rooms      → 201
PATCH  /api/v1/admin/rooms/{room_id}              → 200
DELETE /api/v1/admin/rooms/{room_id}              → 204
                                                  → 409 {"detail":"room_has_bookings","count":3}
```

Body của POST/PATCH:

```jsonc
{
  "name": "Deluxe King",
  "max_guests": 2,
  "bed_description": "1 giường đôi lớn (King)",
  "room_size_sqm": 32,
  "view": "Nhìn ra thành phố",
  "room_facilities": ["air_conditioning","minibar"],
  "images": ["https://..."]
}
```

Quy tắc ghi:

```python
RAG_FIELDS_ROOM = {"name", "bed_description", "view", "room_facilities"}

# POST
source_room_id = nextval('manual_room_source_id_seq')
embedding      = NULL

# PATCH
if set(changed) & RAG_FIELDS_ROOM:
    changed["embedding"] = None
```

- `hotel_id`, `source_room_id`, `embedding` không nhận từ body.
- `room_facilities` validate qua `amenity_catalog` scope `room`/`both`, dùng
  `bind_amenity_rows` đã có.
- `image_count` set lại bằng `len(images)` — đừng để hai trường lệch nhau.
- Response của PATCH kèm `rag_fields_changed` + `embedding_cleared` như Phase 9,
  để UI mở hộp thoại re-embed cùng một cơ chế.
- Audit: `action='room.create' | 'room.update' | 'room.delete'`.

## Frontend — tab Phòng

```
src/admin/pages/hotels/rooms/
  hotel-tab-rooms.tsx        bảng + rỗng
  room-drawer.tsx            drawer sửa/tạo
  room-images-field.tsx      L40 — danh sách URL
  rooms-empty.tsx            trạng thái rỗng có hậu quả
```

- Drawer dùng chung cho tạo và sửa; tiêu đề `Thêm phòng` / `Sửa phòng`.
- Nút `Giá theo ngày` → `/admin/hotels/:hotelId/rooms/:roomId/prices` (Phase 11).
  Nếu Phase 11 chưa xong, **ẩn** nút.
- Ô `ẢNH` hiện `Chưa có ảnh` màu cảnh báo khi `image_count = 0` — đúng thiết kế.
- Xoá phòng: xác nhận đơn giản; 409 → banner nêu số booking và gợi ý dùng
  `Hết phòng` ở B6.
- Sau khi lưu phòng có sửa cột RAG → cùng hộp thoại `Chạy lại embedding ngay?`
  của Phase 9, phạm vi ghi `1 phòng`.

## Related Code Files

- Create: `backend/src/api/admin/rooms.py`
- Create: `backend/tests/test_api/test_admin_rooms.py`
- Create: `frontend/src/admin/pages/hotels/rooms/**`
- Modify: `backend/src/api/admin/__init__.py`, `embedding_fields.py`
- Modify: `frontend/src/admin/api/hotels-client.ts`, `hotel-detail-page.tsx`, `router.tsx`
- Reference: `backend/src/services/amenity_catalog.py` (`bind_amenity_rows`), `backend/src/airflow/dags/data_pipeline/embed_supabase_dag.py`, `frontend/src/lib/room-capacity.ts`

## Implementation Steps

1. Thêm `RAG_FIELDS_ROOM` vào `embedding_fields.py`.
2. `rooms.py`: 4 endpoint + tính `lowest_price_30d` + `booking_count`.
3. Test.
4. Tab Phòng + drawer + trạng thái rỗng theo checklist.
5. `npm run openapi:check`.

## Success Criteria

- [ ] Tạo phòng → `source_room_id` tăng dần, `embedding IS NULL`, không vi phạm `UNIQUE(hotel_id, source_room_id)`
- [ ] Sửa `bed_description` → `rooms.embedding` thành NULL
- [ ] Sửa `room_size_sqm` → `embedding` **giữ nguyên**
- [ ] Xoá phòng không có booking → 204; xoá phòng có booking → 409 kèm số lượng, phòng vẫn còn
- [ ] `lowest_price_30d` khớp `SELECT min(price) FROM room_prices WHERE room_id=... AND check_in_date >= current_date AND check_in_date < current_date + 30 AND sold_out = false`
- [ ] Phòng chưa có giá → cột hiện `Chưa có giá`, không hiện `0 ₫`
- [ ] `image_count` luôn bằng `array_length(images,1)`
- [ ] Khách sạn 0 phòng → trạng thái rỗng đúng câu chữ thiết kế, có nút `+ Thêm phòng đầu tiên`
- [ ] Vùng ảnh là nhập URL, **không** có ô kéo thả giả (L40)
- [ ] `room_facilities` chỉ nhận id thuộc scope `room`/`both`; id sai → 422
- [ ] Template `_build_text` nhánh `rooms` trong DAG **không** bị sửa (git diff xác nhận)

## Risk Assessment

| Rủi ro | Mức | Giảm thiểu |
|--------|-----|-----------|
| Sửa template `rooms` trong `_build_text` → hai cụm vector không tương thích trong cùng một cột | **Cao** | Ghi vào "Ranh giới không được vượt" của plan; có mục git diff trong Success Criteria |
| Xoá phòng làm lỗi FK hoặc mất lịch sử đơn | Cao | Đếm `bookings` **mọi trạng thái** trước khi xoá; 409 nếu có |
| Vùng "kéo thả ảnh" hứa suông rồi không làm được | Trung bình | Đổi sang nhập URL ngay từ thiết kế lại (L40) |
| `lowest_price_30d` tính N+1 khi khách sạn nhiều phòng | Trung bình | Một truy vấn gộp `GROUP BY room_id` cho cả khách sạn, không lặp theo phòng |
| Admin sửa `max_guests` của phòng ETL để "khớp" giữa 2 nguồn, làm hỏng bộ lọc sức chứa | Trung bình | Tooltip nêu rõ khác biệt ngữ nghĩa Agoda/Booking (L42) |
