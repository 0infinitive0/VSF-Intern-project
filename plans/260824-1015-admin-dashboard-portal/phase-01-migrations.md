---
phase: 1
title: "Migration nền dữ liệu"
status: done
priority: P1
effort: "4h"
dependencies: []
---

# Phase 1: Migration nền dữ liệu

## Overview

Bốn thay đổi schema mà mọi phase sau phụ thuộc: soft-delete khách sạn, bảng audit,
cách cấp `source_hotel_id`/`source_room_id` cho dữ liệu admin tự nhập, và **sửa một
lỗi có sẵn** trong `match_hotels_with_rooms` sẽ nổ ngay khi admin bắt đầu sửa giá.

Không có màn hình nào trong phase này.

## Requirements

- Functional
  - `hotels.is_active` — "Ngừng bán" là soft delete, không xoá dòng (booking có
    `ON DELETE RESTRICT` trên `rooms`).
  - Khách sạn / phòng admin tự nhập có `source_hotel_id` / `source_room_id` hợp lệ
    mà không đụng dải id của OTA.
  - Bảng `admin_audit_log` ghi ai làm gì, trước/sau.
  - Khách sạn `is_active = false` không được bot gợi ý nữa.
- Non-functional
  - Migration chạy được trên DB đang có dữ liệu, không khoá bảng lâu.
  - Không đổi chữ ký (signature) của `match_hotels_with_rooms` — mọi call site hiện
    tại phải chạy nguyên trạng.

## Architecture

### 1. `hotels.is_active`

```sql
ALTER TABLE hotels ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT true;
CREATE INDEX hotels_is_active_idx ON hotels (is_active) WHERE is_active = false;
```

Chỉ thêm ở `hotels`, **không** thêm ở `rooms`: xoá phòng lẻ hiếm hơn nhiều và
`rooms` đã có `ON DELETE CASCADE` từ `hotels`. Nếu sau này cần thì thêm riêng.

### 2. Cấp phát id cho dữ liệu tự nhập  (sửa giả định F1)

`hotels.source_hotel_id` là `BIGINT NOT NULL`, khoá `UNIQUE(source_platform,
source_hotel_id)`. Report gốc nói "sinh UUID" — **sai kiểu**. Dùng sequence:

```sql
CREATE SEQUENCE manual_hotel_source_id_seq START 1;
CREATE SEQUENCE manual_room_source_id_seq  START 9000000000;
```

Khoá unique của `hotels` đã có `source_platform` nên id trùng với id của Agoda/Booking
là vô hại. `rooms` thì **không** có cột `source_platform` — khoá unique chỉ
`(hotel_id, source_room_id)` — nên phòng tự nhập thêm vào một khách sạn **đã crawl**
không có gì phân biệt với phòng OTA. Nếu lần crawl sau gán đúng `source_room_id` nhỏ
trùng với id phòng thủ công, `ON CONFLICT ... DO UPDATE` (xem `hotel_pipeline.py`) sẽ
âm thầm ghi đè phòng đó. Cho sequence phòng bắt đầu ở một mốc cao (vẫn nằm gọn trong
`BIGINT`) loại bỏ khả năng trùng này trên thực tế; sequence khách sạn giữ `START 1` vì
đã an toàn nhờ `source_platform`.

Backend đọc `nextval` khi INSERT (Phase 8, 10) — không đặt DEFAULT trên cột, vì
hàng ETL phải giữ id gốc của OTA.

### 3. `admin_audit_log`

```sql
CREATE TABLE admin_audit_log (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    actor_id     UUID NOT NULL,          -- Supabase user id
    actor_email  TEXT,
    action       TEXT NOT NULL,          -- 'hotel.update' | 'price.set' | 'order.cancel' | ...
    entity_type  TEXT NOT NULL,          -- 'hotel' | 'room' | 'room_price' | 'payment' | 'pipeline'
    entity_id    TEXT NOT NULL,
    before       JSONB,
    after        JSONB,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX admin_audit_log_created_idx ON admin_audit_log (created_at DESC);
CREATE INDEX admin_audit_log_entity_idx  ON admin_audit_log (entity_type, entity_id);

ALTER TABLE admin_audit_log ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE admin_audit_log FROM anon, authenticated, PUBLIC;
GRANT SELECT, INSERT ON TABLE admin_audit_log TO service_role;
```

> **Phạm vi:** màn E1 (Nhật ký thao tác) đã bị bỏ theo quyết định #10, nên bảng này
> **chưa có UI đọc**. Vẫn giữ vì admin được sửa giá và huỷ đơn trên dữ liệu tiền
> thật — không có vết nào là một lỗ hổng vận hành thật, trong khi chi phí chỉ là
> một bảng + một hàm insert. Đọc tạm bằng SQL/Supabase Studio.
> Nếu muốn cắt: bỏ file migration này và hàm `write_audit` ở Phase 2; các phase
> khác chỉ cần xoá lời gọi.

### 4. Sửa `match_hotels_with_rooms`  (F4 — P0)

Bản hiện tại (`20260820_add_guest_capacity_filter_to_match_hotels_with_rooms.sql`)
lọc phòng còn chỗ bằng:

```sql
(SELECT count(*) FROM room_prices rp
  WHERE rp.room_id = r.id
    AND rp.check_in_date >= filter_start_date
    AND rp.check_out_date <= filter_end_date
    AND rp.sold_out = false) = (filter_end_date - filter_start_date)
```

`room_prices` có **một dòng cho mỗi đêm** (F2). Nếu một đêm có hai dòng — ví dụ giá
admin vừa nhập và giá OTA crawl trước đó, hai `source_url` khác nhau nên khoá unique
`ux_room_prices_natural_key` không gộp chúng — thì `count(*)` **lớn hơn** số đêm, phép
so bằng sai, và **khách sạn biến mất khỏi kết quả tìm kiếm của bot**.

Lỗi này đã tồn tại sẵn (một đêm crawl từ hai `source_url`), Phase 11 chỉ làm nó xảy ra
thường xuyên. Sửa ở cả hai CTE `hotel_scores` và `room_scores`:

```sql
count(DISTINCT rp.check_in_date) = (filter_end_date - filter_start_date)
```

Cùng migration, thêm `AND h.is_active` vào hai CTE đó để soft delete có hiệu lực.

Dùng `CREATE OR REPLACE FUNCTION` với **đúng danh sách tham số cũ** (13 tham số, xem
file migration 20260820) — đổi signature sẽ tạo hàm overload thứ hai và call site cũ
gọi nhầm bản cũ.

## Related Code Files

- Create: `backend/scripts/migrations/20260824_add_hotel_is_active.sql`
- Create: `backend/scripts/migrations/20260824_add_manual_source_id_sequences.sql`
- Create: `backend/scripts/migrations/20260824_add_admin_audit_log.sql`
- Create: `backend/scripts/migrations/20260824_fix_match_hotels_distinct_nights_and_is_active.sql`
- Modify: `backend/scripts/database_schema.sql` (thêm `is_active` vào `CREATE TABLE hotels`, thêm khối bảng `admin_audit_log` + chú thích trỏ tới file migration, đúng theo cách các bảng khác đã làm)
- Reference (đọc, không sửa): `backend/scripts/migrations/20260820_add_guest_capacity_filter_to_match_hotels_with_rooms.sql`

## Implementation Steps

1. Viết 4 file migration theo thứ tự đánh số ở trên.
2. Ở file thứ 4, copy nguyên hàm từ migration 20260820, chỉ đổi hai chỗ `count(*)`
   → `count(DISTINCT rp.check_in_date)` và thêm `AND h.is_active` vào `WHERE` của
   `hotel_scores` và `room_scores`. Ghi comment giải thích tại sao (F4), không nhắc
   tới số phase.
3. Cập nhật `database_schema.sql` cho khớp.
4. Chạy migration trên DB dev.
5. Kiểm chứng bằng SQL trực tiếp (xem Success Criteria).

## Success Criteria

- [x] `SELECT is_active FROM hotels LIMIT 1` chạy được, mọi hàng hiện có = `true`
- [x] `SELECT nextval('manual_hotel_source_id_seq')` trả số tăng dần
- [x] Chèn thủ công 2 dòng `room_prices` cùng `room_id` + cùng `check_in_date` nhưng khác `source_url`, rồi gọi `match_hotels_with_rooms` với khoảng ngày phủ đêm đó → khách sạn **vẫn** nằm trong kết quả (trước khi sửa thì mất)
- [x] `UPDATE hotels SET is_active = false WHERE id = <x>` → `match_hotels_with_rooms` không còn trả `<x>`
- [x] Luồng chat + booking của khách chạy nguyên trạng: `pytest backend/tests` xanh (14 fail pre-existing trên `main`, không liên quan tới migration — xem Verification bên dưới)
- [x] `\df match_hotels_with_rooms` chỉ liệt kê **một** hàm (không sinh overload)

## Verification

Chạy trên container Postgres 16 + pgvector tạm (không đụng DB dev/prod thật):
loaded `database_schema.sql` bản cũ (từ `git show HEAD`), apply 4 migration file theo
đúng thứ tự, rồi chạy trực tiếp các kiểm tra ở Success Criteria — tất cả pass (xem log
trong session). `pytest backend/tests`: 1232 passed, 14 failed, 12 skipped — cùng 14
test fail y hệt khi chạy trên `main` chưa sửa (đã đối chứng bằng `git stash` +
rerun), nên không phải regression từ migration này.

## Risk Assessment

| Rủi ro | Mức | Giảm thiểu |
|--------|-----|-----------|
| `CREATE OR REPLACE` sai signature → sinh overload, call site cũ gọi nhầm bản cũ | Cao | Copy nguyên khối tham số từ file 20260820; kiểm bằng `\df` sau khi chạy |
| `count(DISTINCT ...)` đổi hành vi tìm kiếm ngoài dự kiến | Trung bình | Trước/sau: chạy `match_hotels_with_rooms` với cùng tham số trên DB dev, so số lượng và thứ tự kết quả. Vì `count(DISTINCT x) <= count(*)`, khách sạn **có thể mất** khỏi kết quả — nhưng chỉ đúng khi một đêm trong khoảng ngày yêu cầu **không có dòng giá nào còn hiệu lực** (không phải do trùng đêm). Mất khách sạn vì lý do khác thì mới là regression |
| Thêm `AND h.is_active` làm chậm truy vấn | Thấp | Cột `NOT NULL DEFAULT true`, index partial chỉ trên `false` — planner bỏ qua khi mọi hàng đều true |
| Bảng audit không ai đọc → chết dần | Thấp | Đã ghi rõ trong Architecture là chấp nhận, kèm hướng dẫn cắt |
