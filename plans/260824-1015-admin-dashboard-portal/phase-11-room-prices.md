---
phase: 11
title: "Quản lý giá phòng theo đêm (B6)"
status: done
priority: P1
effort: "2.5d"
dependencies: [10, 1]
---

# Phase 11: Quản lý giá phòng theo đêm — B6

## Overview

Màn phức tạp nhất của cả plan, và là màn duy nhất **ghi trực tiếp vào dữ liệu mà bot
dùng để trả lời giá**. Hai thứ phải đúng tuyệt đối:

1. `room_prices` là **một dòng mỗi ĐÊM** (F2), không phải "một dòng mỗi khoảng ngày".
2. Ghi thêm dòng cho một đêm đã có dòng khác sẽ làm khách sạn **biến mất khỏi tìm
   kiếm** nếu Phase 1 chưa sửa `match_hotels_with_rooms` (F4). **Phase 1 là điều kiện
   cứng, không phải khuyến nghị.**

Sửa giá **không** ảnh hưởng embedding (`room_prices` không có cột `embedding`) —
màn này **không được** hiện bất kỳ nhắc nhở embedding nào.

**Thiết kế bám theo:** artboard `B6 · QUẢN LÝ GIÁ PHÒNG THEO NGÀY` và biến thể
`B6 · chế độ xem bảng theo khoảng ngày`.

## Mô hình dữ liệu — đọc kỹ trước khi code

```
room_prices(room_id, price, currency, check_in_date, check_out_date,
            sold_out, crossed_out, review_score, review_text,
            source_url, crawled_at)

UNIQUE INDEX ux_room_prices_natural_key
  ON room_prices (room_id, check_in_date, check_out_date, COALESCE(source_url, ''))
```

- Một đêm = một dòng: `check_in_date` = đêm đó, `check_out_date` = hôm sau.
- Một đêm có thể có **nhiều dòng** (khác `source_url`). `place_details._average_price`
  chỉ lấy dòng có **`crawled_at` lớn nhất** cho mỗi đêm.
- ⇒ Admin ghi với `source_url = NULL` và `crawled_at = now()` sẽ **thắng** dòng OTA cũ.
  Lần crawl OTA tiếp theo (`crawled_at` mới hơn) **thắng lại**. Đây chính là ngữ nghĩa
  "cảnh báo, vẫn cho sửa" của quyết định #7, **không cần sửa pipeline**.
- ⇒ Ghi giá cho `[20/08, 31/08]` = **12 dòng UPSERT**, không phải 1 dòng.

## Bám sát thiết kế — checklist đối chiếu 1:1

**Header:** breadcrumb
`Quản trị · Khách sạn · Mường Thanh Grand Đà Nẵng · Phòng · Deluxe King` ·
tiêu đề `Giá phòng theo ngày · Deluxe King` · tab `Lịch tháng` / `Bảng khoảng ngày` ·
nút `Nhập từ CSV` (xem L47).

**Banner cảnh báo** (chỉ khi khách sạn `Từ pipeline`, biểu tượng `!`):
`Khách sạn này lấy dữ liệu **từ pipeline** — giá sửa tay sẽ bị ghi đè vào 06:00 hằng
ngày. Muốn giữ giá cố định, chuyển khách sạn sang chế độ tự nhập.` (xem L48)

**Chế độ Lịch tháng:**
- Điều hướng `‹ Tháng 8 · 2026 ›`
- Chú giải: `Đang chọn` · `Hết phòng` · `Kéo thả để chọn nhiều ngày`
- Nhãn cột `T2 T3 T4 T5 T6 T7 CN`
- Ô ngày cao 78px, bo 10px, gồm: số ngày (2 chữ số) · giá · nhãn `Hết phòng`

| Trạng thái ô | Style |
|---|---|
| Bình thường | nền `#fff`, viền `--stroke` |
| Đang chọn | nền `--acc-soft`, viền `--acc`, `inset 0 0 0 1px rgba(58,115,222,.25)` |
| Hết phòng | nền `--fill`, viền `--stroke`, giá **gạch ngang** màu `--t4`, chip `Hết phòng` |
| Hết phòng + đang chọn | nền `--fill2`, viền `--acc` |
| Ngày quá khứ | `opacity: .5` |
| Cuối tuần (T7/CN) | số ngày màu `--acc` |

Giá dùng `font-variant-numeric: tabular-nums`, weight 700, 11.5px.

**Panel đặt giá** (hiện khi đang chọn ngày):
- Tiêu đề `Đặt giá cho 12 ngày đã chọn`
- Phụ đề `20/08/2026 – 31/08/2026 · Deluxe King`
- `Giá mỗi đêm` — `1.500.000` + select `VND`
- Dòng phụ: `Giá hiện tại của 12 ngày này: 1.200.000 ₫ – 1.500.000 ₫`
  (khoảng min–max của các đêm đang chọn; một giá duy nhất thì hiện một số)
- Toggle `Đánh dấu hết phòng` + phụ đề `Khách không đặt được các ngày này`
- `Áp dụng thêm cho`: `Chỉ T7 & CN` · `Lặp lại 4 tuần`
- Ghi chú: `Ghi đè giá đang có của 12 ngày. Các đơn đã đặt trước giữ nguyên giá cũ.`
- Nút `Bỏ chọn` · `Đặt giá 12 ngày`

**Chế độ Bảng khoảng ngày:**
- Tiêu đề `Bảng giá theo khoảng ngày` · nút `+ Thêm khoảng ngày`
- Cột: `TỪ NGÀY` · `ĐẾN NGÀY` · `SỐ ĐÊM` · `GIÁ / ĐÊM` · `TÌNH TRẠNG` · `THAO TÁC`
- Chip tình trạng: `Còn phòng` (`--ok-soft`/`--ok-ink`) · `Hết phòng` (`--fill`/`--t3`)
- Dòng vừa sửa: nền `--acc-soft`, cột ghi chú `Vừa sửa`
- Thao tác: `Sửa` · `Xoá`

**Bảng khoảng ngày là VIEW GỘP, không phải mô hình lưu trữ.** Gộp các đêm liên tiếp
có cùng `(price, currency, sold_out)` thành một dòng. Ví dụ trong thiết kế:
`01/08–14/08 · 14 đêm · 1.200.000 ₫ · Còn phòng` = 14 dòng `room_prices`.

## Lệch giữa thiết kế và code — phải xử lý

| # | Thiết kế | Thực tế | Xử lý |
|---|---|---|---|
| L47 | Nút `Nhập từ CSV` | Chưa có gì | **Bỏ ở phase này.** Chọn ngày kéo thả + `Lặp lại 4 tuần` đã phủ phần lớn nhu cầu. Nhập CSV là tính năng riêng, thêm sau nếu admin thật sự cần |
| L48 | `ghi đè vào 06:00 hằng ngày` + `chuyển khách sạn sang chế độ tự nhập` | Không có DAG nào chạy 06:00 ghi `room_prices` (F5, L21). Và **không có** cơ chế "chuyển sang tự nhập" — `source_platform` là khoá UPSERT, đổi nó sẽ tách hàng khỏi ETL và làm mồ côi dữ liệu | Sửa banner thành: `Giá của khách sạn này do pipeline OTA quản lý — chạy lại pipeline sẽ ghi đè giá bạn vừa nhập.` **Bỏ** câu gợi ý chuyển chế độ |
| L49 | `Các đơn đã đặt trước giữ nguyên giá cũ` | Đúng: `bookings.total_amount` chốt tại lúc đặt, không đọc lại `room_prices` | Giữ nguyên câu này — nó đúng và trấn an được admin |
| L50 | `TÌNH TRẠNG` chỉ có `Còn phòng`/`Hết phòng` | Còn `get_room_availability` (đếm booking CONFIRMED) — một đêm `sold_out=false` vẫn có thể kín do đã bán hết | Thêm trạng thái thứ ba `Đã kín` (`--warn-soft`/`--warn-ink`) khi `sold_out=false` nhưng `available = 0`. Không sửa được bằng tay — chỉ để admin hiểu vì sao khách không đặt được |
| L51 | Ô ngày không có giá | Đêm chưa có dòng `room_prices` | Ô trống, chữ `Chưa có giá` màu `--t4`. **Quan trọng:** đêm không có giá làm `match_hotels_with_rooms` loại phòng khỏi kết quả (điều kiện `count = số đêm`) → hiện chú giải cảnh báo |
| L52 | `Xoá` khoảng ngày | Xoá dòng `room_prices` | Chỉ xoá dòng **do admin ghi** (`source_url IS NULL`). Dòng OTA để nguyên — xoá nó chỉ khiến lần crawl sau tạo lại. Nếu khoảng ngày toàn dòng OTA thì nút `Xoá` **ẩn**, chỉ còn `Sửa` |

## Backend — hợp đồng API

```
GET /api/v1/admin/rooms/{room_id}/prices?from=2026-08-01&to=2026-08-31
→ 200 {
    "room_id": "uuid",
    "room_name": "Deluxe King",
    "hotel_id": "uuid", "hotel_name": "...", "is_manual": false,
    "currency": "VND",
    "nights": [{
      "date": "2026-08-20",
      "price": "1500000.00",
      "sold_out": false,
      "available": 3,                 // get_room_availability cho đêm đó  (L50)
      "source": "manual",             // manual | pipeline — dòng crawled_at mới nhất
      "row_count": 2                  // số dòng room_prices cho đêm này
    }],
    "ranges": [{                      // đã gộp sẵn ở backend  (bảng khoảng ngày)
      "from": "2026-08-01", "to": "2026-08-14", "nights": 14,
      "price": "1200000.00", "sold_out": false, "source": "pipeline",
      "deletable": false              // L52
    }]
  }
```

`nights[]` chỉ chứa đêm **có** dòng; đêm thiếu giá không xuất hiện → frontend hiện
`Chưa có giá`.

`ranges[]` gộp ở backend, không ở frontend: cùng một thuật toán phải cho cùng kết quả
ở cả hai chế độ xem.

```
PUT /api/v1/admin/rooms/{room_id}/prices
  body: {
    "dates": ["2026-08-20", "2026-08-21", ...],   // danh sách ĐÊM rời rạc, ≤ 366
    "price": "1500000.00",
    "currency": "VND",
    "sold_out": false
  }
→ 200 { "written": 12, "created": 4, "updated": 8 }
→ 422 dates rỗng / > 366 / price âm
```

`PUT` nhận **danh sách đêm rời rạc**, không phải khoảng — vì UI cho chọn `Chỉ T7 & CN`
(không liên tục). Frontend khai triển `Lặp lại 4 tuần` và `Chỉ T7 & CN` thành danh
sách ngày trước khi gửi; backend không cần biết quy tắc lặp.

Thực thi:

```sql
INSERT INTO room_prices (room_id, price, currency, check_in_date, check_out_date,
                         sold_out, source_url, crawled_at)
VALUES (:room_id, :price, :currency, :night, :night + 1, :sold_out, NULL, now())
ON CONFLICT (room_id, check_in_date, check_out_date, COALESCE(source_url, ''))
DO UPDATE SET price = EXCLUDED.price,
              currency = EXCLUDED.currency,
              sold_out = EXCLUDED.sold_out,
              crawled_at = now();
```

- `source_url = NULL` cố định → mỗi phòng có **đúng một** "lớp admin" cho mỗi đêm,
  không bao giờ tự nhân bản dòng.
- `crawled_at = now()` là thứ khiến giá admin thắng dòng OTA cũ.
- Ghi trong **một** câu lệnh nhiều VALUES, không lặp 366 lần round-trip.
- Chỉ số dòng thật sự đổi mới ghi audit (`action='price.set'`,
  `before`/`after` = `{from, to, price, sold_out}` đã gộp, không phải 366 dòng).

```
DELETE /api/v1/admin/rooms/{room_id}/prices?from=...&to=...
→ 200 { "deleted": 12 }
```

Chỉ xoá `source_url IS NULL` (L52). Trả `deleted: 0` nếu khoảng đó toàn dòng OTA.

## Frontend — màn hình B6

```
src/admin/pages/hotels/prices/
  room-prices-page.tsx        header + 2 chế độ xem + banner
  price-calendar.tsx          lịch tháng, kéo thả chọn
  price-set-panel.tsx         panel đặt giá
  price-range-table.tsx       bảng khoảng ngày
  price-range-dialog.tsx      thêm/sửa khoảng ngày
src/admin/lib/expand-dates.ts  Chỉ T7&CN, Lặp lại 4 tuần
```

- **Kéo thả chọn nhiều ngày**: mousedown → mousemove → mouseup trên lưới. Hỗ trợ cả
  bàn phím (Shift+mũi tên) để không khoá người dùng chỉ dùng phím.
- Ngày quá khứ `opacity .5` và **không chọn được** — đặt giá cho đêm đã qua vô nghĩa.
- `Giá hiện tại của N ngày này: X – Y` tính từ `nights[]` đang chọn ở client.
- `Lặp lại 4 tuần` khai triển thành +7, +14, +21 ngày cho **mỗi** ngày đang chọn, khử
  trùng lặp, cắt bỏ ngày quá khứ. Hiện lại số ngày cuối cùng trên nút:
  `Đặt giá 48 ngày`.
- Sau khi PUT: tải lại tháng đang xem, đánh dấu `Vừa sửa` cho các dòng vừa ghi ở
  bảng khoảng ngày.
- **Không** hiện bất kỳ thứ gì liên quan tới embedding trên màn này.
- Chú giải khi có đêm thiếu giá: `N đêm trong tháng chưa có giá — khách không đặt
  được các đêm này.` (L51)

## Related Code Files

- Modify: `backend/src/api/admin/rooms.py` (hoặc tách `prices.py` nếu > 300 dòng)
- Create: `backend/tests/test_api/test_admin_room_prices.py`
- Create: `frontend/src/admin/pages/hotels/prices/**`, `frontend/src/admin/lib/expand-dates.ts`
- Modify: `frontend/src/admin/router.tsx`
- Reference: `backend/src/services/place_details.py` (`_average_price` — quy tắc `crawled_at` mới nhất), `backend/scripts/database_schema.sql` (`ux_room_prices_natural_key`), migration `20260820_add_guest_capacity_filter_to_match_hotels_with_rooms.sql`

## Implementation Steps

1. **Kiểm Phase 1 đã chạy**: `match_hotels_with_rooms` phải dùng
   `count(DISTINCT rp.check_in_date)`. Chưa có thì **dừng**, làm Phase 1 trước.
2. Đọc `place_details._average_price` để chắc quy tắc `crawled_at` đúng như mô tả.
3. `GET` + thuật toán gộp `ranges` + `available` cho mỗi đêm.
4. `PUT` UPSERT nhiều VALUES + audit gộp.
5. `DELETE` giới hạn `source_url IS NULL`.
6. Test (xem dưới) — **đặc biệt test hồi quy tìm kiếm**.
7. `expand-dates.ts` + test đơn vị cho `Chỉ T7 & CN` và `Lặp lại 4 tuần`.
8. Lịch tháng + panel + bảng khoảng ngày theo checklist.

## Success Criteria

- [x] Đặt giá cho khoảng 12 ngày → **12 dòng** `room_prices`, mỗi dòng `check_out_date = check_in_date + 1`
- [x] Đặt lại giá cho đúng 12 ngày đó → vẫn **12 dòng** (UPDATE, không nhân bản)
- [x] **Hồi quy tìm kiếm:** phòng thuộc khách sạn ETL đã có giá OTA; admin đặt giá đè lên 3 đêm → gọi `match_hotels_with_rooms` với khoảng ngày phủ 3 đêm đó, khách sạn **vẫn** trong kết quả — verified: Phase 1's `count(DISTINCT rp.check_in_date)` fix is in `database_schema.sql`, and writing an extra admin row per night (instead of replacing) doesn't change that count
- [x] `place_details` trả về **giá admin vừa nhập**, không phải giá OTA cũ — verified by code reading (`_average_price` picks max `crawled_at`; admin write always sets `crawled_at=now()`) plus this phase's own `test_get_prices_admin_row_outranks_older_ota_row_by_crawled_at`
- [x] `Chỉ T7 & CN` chỉ ghi vào thứ Bảy và Chủ nhật
- [x] `Lặp lại 4 tuần` ghi đúng 4× số ngày, không trùng, không có ngày quá khứ
- [x] Đánh dấu `Hết phòng` → `sold_out = true`, đêm đó biến mất khỏi điều kiện của `match_hotels_with_rooms` — xem "Vấn đề đã sửa" bên dưới, sửa ngoài phạm vi file gốc của phase với sự đồng ý của người dùng
- [x] Bảng khoảng ngày gộp đúng: 14 đêm cùng giá → 1 dòng `14 đêm`; đổi giá 1 đêm giữa → tách thành 3 dòng
- [x] Xoá khoảng ngày toàn dòng OTA → `deleted: 0`, nút `Xoá` ẩn ở UI
- [x] Đêm `sold_out=false` nhưng đã bán hết → chip `Đã kín` (L50)
- [x] Ngày quá khứ không chọn được
- [x] Màn này **không** có chữ "embedding" nào (grep xác nhận)
- [x] `admin_audit_log` ghi 1 dòng gộp cho mỗi lần đặt giá, không phải 12 dòng
- [x] Đặt giá 366 ngày hoàn tất dưới 3 giây — verified: 1 RPC call bất kể số đêm (test + phân tích code, không round-trip theo số đêm)

## Vấn đề đã sửa — ngoài phạm vi file gốc của phase, sửa với sự đồng ý của người dùng

**Đánh dấu `Hết phòng` không ẩn đêm đó khỏi tìm kiếm/giá nếu đêm đó đã có dòng OTA.**
Phát hiện lúc code review: cả `match_hotels_with_rooms` (2 nơi trong
`database_schema.sql`) lẫn `place_details._average_price` đều lọc
`sold_out = false` **trên từng dòng, trước khi** chọn dòng `crawled_at` mới
nhất — không phải "lọc theo trạng thái của dòng thắng". Khi một đêm có cả
dòng OTA (`sold_out=false`, cũ) và dòng admin (`sold_out=true`, mới), dòng
OTA vẫn thoả điều kiện lọc nên đêm đó vẫn tính là còn phòng còn giá.

Đã sửa (`20260824_fix_sold_out_freshest_row_precedence.sql`):
- Hàm mới `public.count_priced_open_nights(room_id, start, end)` — chọn
  dòng `crawled_at` mới nhất **cho mỗi đêm trước**, rồi mới kiểm tra
  `sold_out` trên đúng dòng đó. Thay thế `count(DISTINCT rp.check_in_date)
  WHERE sold_out=false` ở cả 2 nơi trong `match_hotels_with_rooms`.
- `place_details._average_price`: đổi thứ tự lọc — chọn dòng mới nhất mỗi
  đêm trước, kiểm tra `sold_out` trên dòng đó sau (thay vì lọc `sold_out`
  trên toàn bộ dòng thô trước khi chọn dòng mới nhất).
- `place_details.get_hotel_detail`: bỏ `.eq("sold_out", False)` ở câu
  query lấy `room_prices` — filter này ở tầng DB sẽ loại dòng
  `sold_out=True` **trước khi** `_average_price` kịp thấy, vô hiệu hoá fix
  phía trên. Phát hiện bằng cách viết test giả lập postgrest filter thật
  (fake cũ bỏ qua mọi `.eq()`/`.gte()`, không phát hiện được lớp lỗi này).
- Xác nhận cả 2 chiều bằng Postgres thật (không chỉ đọc code): OTA cũ
  `sold_out=false` + admin mới `sold_out=true` → 0 đêm mở; và chiều ngược
  lại (admin mở lại đè lên OTA cũ báo hết phòng) → 1 đêm mở.
- Vẫn giữ cảnh báo trong panel đặt giá (dùng `row_count`) làm lớp bảo vệ
  thứ hai — không gỡ, vì admin vẫn nên biết khi nào có dòng khác cùng đêm.

## Risk Assessment

| Rủi ro | Mức | Giảm thiểu |
|--------|-----|-----------|
| Phase 1 chưa chạy → sửa giá làm khách sạn **biến mất khỏi tìm kiếm** | **Cao nhất** | Bước 1 của Implementation là kiểm tra bắt buộc; có test hồi quy tìm kiếm trong Success Criteria |
| Hiểu `room_prices` là "một dòng mỗi khoảng ngày" → ghi 1 dòng cho 12 đêm | **Cao** | Mục "Mô hình dữ liệu" ở đầu file; test đếm đúng 12 dòng |
| Ghi thiếu `source_url = NULL` → mỗi lần lưu tạo dòng mới, nhân bản vô hạn | Cao | Cố định NULL trong câu INSERT; test lưu 2 lần vẫn 12 dòng |
| Quên `crawled_at = now()` → giá admin **thua** dòng OTA cũ, sửa xong không thấy đổi | Cao | Có test kiểm `place_details` trả giá mới |
| 366 round-trip khi đặt giá cả năm | Trung bình | Một câu lệnh nhiều VALUES; có mục đo thời gian |
| Kéo thả chọn ngày không dùng được bằng bàn phím | Trung bình | Hỗ trợ Shift+mũi tên; không phải yêu cầu a11y đầy đủ nhưng đừng khoá cứng |
| Thuật toán gộp `ranges` ở FE và BE cho kết quả khác nhau | Trung bình | Gộp **chỉ ở backend**, frontend chỉ render |
