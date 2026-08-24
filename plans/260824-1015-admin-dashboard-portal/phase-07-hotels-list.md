---
phase: 7
title: "Danh sách khách sạn (B1)"
status: pending
priority: P1
effort: "1.5d"
dependencies: [3]
---

# Phase 7: Danh sách khách sạn — B1

## Overview

Cổng vào của toàn nhánh Khách sạn. Bảng có filter, chọn nhiều dòng, và — quan trọng
nhất — **dấu hiệu thị giác phân biệt khách sạn do pipeline ETL quản lý**, vì đó là
thứ quyết định admin sửa được gì mà không mất công.

**Thiết kế bám theo:** artboard `B1 · DANH SÁCH KHÁCH SẠN`.

## Bám sát thiết kế — checklist đối chiếu 1:1

**Header:** breadcrumb `Quản trị · Khách sạn` · tiêu đề `Danh sách khách sạn` ·
nút phụ `↓ Xuất CSV` · nút chính `+ Thêm khách sạn`.

**Thanh công cụ:** ô tìm `⌕ Tên khách sạn hoặc thành phố…` · 3 select:
`Nguồn dữ liệu: Tất cả` · `Đang bán: Tất cả` · `Embedding: Chưa embed` ·
nhãn phải `Hiển thị 8 / 64 khách sạn`.

**Cột:** `☐` · `KHÁCH SẠN` · `THÀNH PHỐ` · `HẠNG SAO` · `NGUỒN` · `SỐ PHÒNG` ·
`EMBEDDING` · `ĐANG BÁN` · `⋯`

Chi tiết từng cột (theo `hotels` trong `renderVals()`):

| Cột | Nội dung | Style |
|---|---|---|
| `☐` | Checkbox 16px, bo 5px. Chọn: nền `--acc`, chữ `--on-acc`, dấu `✓`. Chưa chọn: viền `--stroke`, nền trắng | |
| `KHÁCH SẠN` | Ô vuông chữ cái đầu (`MT`, `SP`) + tên (đậm) + địa chỉ dòng dưới (`962 Ngô Quyền, Sơn Trà`, `--t3`) | |
| `HẠNG SAO` | `'★'.repeat(star_rating)` | |
| `NGUỒN` | Chip `✎ Tự nhập` (`--acc-soft`/`--acc`) hoặc `⟳ Từ pipeline` (`--fill2`/`--t2`), cao 22px, `font-size:11.5px` | |
| `SỐ PHÒNG` | Số nguyên | |
| `EMBEDDING` | Chấm 8px + nhãn. Đã embed: chấm `--ok`, chữ `--t2` weight 500. Chưa embed: chấm `--warn`, chữ `--warn-ink` weight **600** | |
| `ĐANG BÁN` | Switch 34×20px. Bật: nền `--acc`, núm phải. Tắt: nền `--fill2`, núm trái + đổ bóng. Nhãn dưới: `Đang bán` (`--t4`) / `Ngừng bán` (`--t3`) | |

**Dòng "Từ pipeline" có nền kẻ sọc** — đây là cơ chế thị giác then chốt:

```css
background: repeating-linear-gradient(135deg,
  rgba(21,24,28,.030) 0 6px, rgba(21,24,28,0) 6px 12px);
```

Dòng đang chọn: nền `--acc-soft` (đè lên sọc).

**Chú thích dưới bảng:** `Dòng kẻ sọc: dữ liệu do pipeline ETL ghi đè lúc 06:00 hằng
ngày — sửa tay sẽ mất.` (xem L21 — phải sửa câu này cho đúng lịch thật)

**Phân trang:** `‹ 1 2 3 ›`

**Thanh hành động hàng loạt** (nổi lên khi có dòng được chọn):
`Đã chọn 3 khách sạn` · `Chạy embedding` · `Ngừng bán` · `Xoá` · `Bỏ chọn`

## Lệch giữa thiết kế và code — phải xử lý

| # | Thiết kế | Thực tế | Xử lý |
|---|---|---|---|
| L19 | Nút hàng loạt `Xoá` | Quyết định #3: **chỉ soft delete**. `bookings.room_id` là `ON DELETE RESTRICT` — xoá cứng sẽ lỗi DB hoặc mất lịch sử đơn | **Bỏ nút `Xoá`.** Thanh hàng loạt còn 3 nút: `Chạy embedding` · `Ngừng bán` · `Bỏ chọn` |
| L20 | Nút hàng loạt `Chạy embedding` | Cần endpoint re-embed theo danh sách hotel | **Giữ** — gọi `POST /admin/hotels/reembed` với `hotel_ids[]` (Phase 12 định nghĩa; ở phase này chỉ render nút, nối API ở Phase 12). Nếu Phase 12 chưa xong thì **ẩn** nút, không render disabled |
| L21 | `pipeline ETL ghi đè lúc 06:00 hằng ngày` | Chỉ `embed_supabase_tables_pipeline` có `schedule="@daily"`. `google_maps`, `hotel_nearby`, `tour` đều `schedule=None` (chạy tay). **Không có DAG nào ghi đè `hotels` theo lịch 06:00** — `hotel_pipeline.py`/`ota_pipeline.py` là module, phải được gọi thủ công | Sửa câu thành: `Dòng kẻ sọc: dữ liệu lấy từ nguồn OTA — sẽ bị ghi đè khi chạy lại pipeline nhập liệu.` Không nêu giờ cụ thể không có thật |
| L22 | Cột `SỐ PHÒNG` | Cần `count(rooms)` theo hotel | Thêm vào view (xem dưới), không N+1 |
| L23 | Cột `EMBEDDING` một chấm cho cả khách sạn | Cả `hotels.embedding` **và** `rooms.embedding` đều ảnh hưởng tìm kiếm | Chấm xanh **chỉ khi** `hotels.embedding IS NOT NULL` **và** không phòng nào thiếu embedding. Tooltip nêu rõ: `Khách sạn đã embed · 3/42 phòng chưa embed` |
| L24 | `Xuất CSV` | Không có gì cản | Giữ, cùng cơ chế `?format=csv` như D1 |

## Backend — tầng dữ liệu

```sql
CREATE VIEW admin_hotel_rows AS
SELECT
  h.id, h.name, h.address, h.city, h.star_rating,
  h.source_platform, h.is_active, h.image_url,
  (h.source_platform = 'manual')                    AS is_manual,
  (h.embedding IS NOT NULL)                         AS hotel_embedded,
  count(r.id)                                       AS room_count,
  count(r.id) FILTER (WHERE r.embedding IS NULL)    AS rooms_missing_embedding,
  h.updated_at
FROM hotels h
LEFT JOIN rooms r ON r.hotel_id = h.id
GROUP BY h.id;

REVOKE ALL ON admin_hotel_rows FROM anon, authenticated, PUBLIC;
GRANT  SELECT ON admin_hotel_rows TO service_role;
```

`hotels` bản thân **không** bị REVOKE khỏi `anon` (app chat đọc được), nhưng view này
gộp thông tin vận hành nên vẫn khoá lại cho gọn.

## Backend — hợp đồng API

```
GET /api/v1/admin/hotels
  ?q=<tên hoặc thành phố>
  &source=manual|pipeline|all             (pipeline = source_platform <> 'manual')
  &is_active=true|false
  &embedding=embedded|missing|all
  &page=1&page_size=25
  &format=json|csv
```

`200`:

```jsonc
{
  "items": [{
    "id": "uuid",
    "name": "Mường Thanh Grand Đà Nẵng",
    "address": "962 Ngô Quyền, Sơn Trà",
    "city": "Đà Nẵng",
    "star_rating": 4,
    "source_platform": "booking",
    "is_manual": false,
    "is_active": true,
    "room_count": 128,
    "hotel_embedded": true,
    "rooms_missing_embedding": 0,
    "embedding_state": "embedded",          // embedded | partial | missing
    "image_url": "https://..."
  }],
  "total": 64, "page": 1, "page_size": 25
}
```

`embedding_state` tính ở backend, một quy tắc duy nhất, dùng lại ở B7:

```
missing   khi hotel_embedded = false
partial   khi hotel_embedded = true và rooms_missing_embedding > 0
embedded  khi hotel_embedded = true và rooms_missing_embedding = 0
```

```
PATCH /api/v1/admin/hotels/{id}/active
  body: { "is_active": false }
→ 200 { "id": "uuid", "is_active": false }
→ 409 {
    "detail": "hotel_has_future_confirmed_bookings",
    "count": 3,
    "bookings": [{"booking_id":"uuid","check_in_date":"2026-09-01","room_name":"Deluxe King"}]
  }
```

**Chặn ngừng bán khi còn đơn CONFIRMED trong tương lai.** Vì màn B4 (hộp thoại
Ngừng bán) đã bị bỏ theo quyết định #10, ràng buộc này sống ở backend và frontend
hiện nó bằng banner lỗi liệt kê tối đa 5 đơn — không có hộp thoại riêng.

```
POST /api/v1/admin/hotels/bulk-active
  body: { "hotel_ids": ["uuid"], "is_active": false }
→ 200 { "updated": 2, "blocked": [{"hotel_id":"uuid","count":3}] }
```

Mọi thao tác đổi `is_active` ghi `admin_audit_log`
(`action='hotel.deactivate'` / `'hotel.activate'`).

## Frontend — màn hình B1

```
src/admin/pages/hotels/
  hotels-page.tsx
  hotels-toolbar.tsx
  hotels-table.tsx
  hotel-source-chip.tsx        ✎ Tự nhập / ⟳ Từ pipeline
  hotel-embedding-dot.tsx      3 trạng thái + tooltip (L23)
  hotels-bulk-bar.tsx          3 nút (L19)
src/admin/api/hotels-client.ts
```

- Switch `ĐANG BÁN` bật/tắt **ngay tại dòng**, optimistic UI. Lỗi 409 → hoàn switch
  về trạng thái cũ + banner đỏ liệt kê đơn chặn.
- Không có xác nhận riêng cho một dòng (B4 đã bỏ); thao tác hàng loạt `Ngừng bán`
  **có** xác nhận vì tác động nhiều khách sạn cùng lúc.
- Click dòng (ngoài switch/checkbox) → `/admin/hotels/:id` (Phase 9).
- Nền kẻ sọc là `repeating-linear-gradient` đúng như thiết kế — **không** thay bằng
  màu nền phẳng, đó là tín hiệu phân biệt chính.

## Related Code Files

- Create: `backend/scripts/migrations/20260824_add_admin_hotel_view.sql`
- Create: `backend/src/api/admin/hotels.py`
- Create: `backend/tests/test_api/test_admin_hotels.py`
- Create: `frontend/src/admin/api/hotels-client.ts`, `frontend/src/admin/pages/hotels/**`
- Modify: `backend/src/api/admin/__init__.py`, `frontend/src/admin/router.tsx`
- Modify: `frontend/src/types/wire.generated.ts`
- Reference: `frontend/src/lib/format-source-platform.ts` (đã có, kiểm xem nhãn có tái dùng được không)

## Sở hữu file

Nhánh Khách sạn sở hữu `backend/src/api/admin/hotels.py`, `rooms.py`,
`frontend/src/admin/pages/hotels/**`, `frontend/src/admin/api/hotels-client.ts`.

## Implementation Steps

1. Migration view + kiểm số dòng khớp `hotels`.
2. `hotels.py`: list + đổi `is_active` + bulk + CSV.
3. Logic chặn: đếm `bookings` CONFIRMED có `check_out_date >= current_date` thuộc
   phòng của khách sạn.
4. Test.
5. Dựng màn theo checklist; đặc biệt đối chiếu nền sọc, chip nguồn, chấm embedding.

## Success Criteria

- [ ] `count(*) FROM admin_hotel_rows` = `count(*) FROM hotels`
- [ ] Khách sạn có 42 phòng, 3 phòng thiếu embedding → `embedding_state = 'partial'`, tooltip đúng
- [ ] Dòng `source_platform <> 'manual'` có nền kẻ sọc; dòng `manual` thì không
- [ ] Tắt switch khách sạn còn 3 đơn CONFIRMED tương lai → 409, switch bật lại, banner liệt kê 3 đơn
- [ ] Tắt switch khách sạn không có đơn → thành công, `admin_audit_log` có 1 dòng
- [ ] Khách sạn `is_active=false` không còn được `match_hotels_with_rooms` trả về (nối tiếp Phase 1)
- [ ] Thanh hàng loạt **không** có nút `Xoá` (L19)
- [ ] Chú thích dưới bảng không nhắc "06:00" (L21)
- [ ] Lọc + tìm + phân trang khớp SQL viết tay
- [ ] `?format=csv` mở được bằng Excel, tiếng Việt đúng font

## Risk Assessment

| Rủi ro | Mức | Giảm thiểu |
|--------|-----|-----------|
| Optimistic switch làm admin tưởng đã ngừng bán trong khi backend từ chối | Cao | Hoàn switch + banner lỗi rõ ràng khi 409; test riêng |
| `count(rooms)` trong view làm chậm khi nhiều khách sạn | Trung bình | `GROUP BY h.id` trên vài nghìn dòng là rẻ; đo `EXPLAIN ANALYZE`, thêm index `rooms(hotel_id)` nếu chưa có |
| Bulk `Ngừng bán` chặn một phần → admin không biết cái nào trượt | Trung bình | Trả `blocked[]` kèm lý do; UI liệt kê |
| Nền sọc bị coi là "trang trí" rồi bị bỏ khi code | Trung bình | Ghi rõ trong Success Criteria; đây là tín hiệu ngữ nghĩa, không phải trang trí |
