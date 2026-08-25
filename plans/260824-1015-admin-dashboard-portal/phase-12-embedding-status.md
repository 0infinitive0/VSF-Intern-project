---
phase: 12
title: "Trạng thái & độ phủ embedding (B7, C4)"
status: done
priority: P2
effort: "1d"
dependencies: [7]
---

# Phase 12: Trạng thái & độ phủ embedding — B7, C4

## Overview

Hai mục sidebar `KHÁCH SẠN › Trạng thái embedding` và `DỮ LIỆU BOT › Độ phủ embedding`.
Trả lời một câu hỏi vận hành: **bot còn chưa học những gì?**

Chỉ đọc, không phụ thuộc Airflow → làm được ngay sau Phase 7, trước cả nhánh Pipeline.
Đây cũng là nơi cung cấp con số cho hộp thoại C2 (Phase 15) và ô KPI ở A3 (Phase 17).

## Trạng thái thiết kế

**Không có artboard riêng cho B7 và C4.** Hai màn này phải suy ra từ các mẫu đã có
trong `VSF Admin Portal.dc.html`:

| Nguồn | Dùng lại cho |
|---|---|
| A2 · thẻ `Pipeline embedding` (`Bản ghi đã nhúng 1.284 / 1.310` + banner `26 phòng chưa có embedding — bot sẽ không gợi ý được các phòng này.`) | Khối tổng quan của C4 |
| B1 · chấm embedding + chip nguồn + nền kẻ sọc | Bảng của B7 |
| C2 · chip bảng áp dụng (`✓ Khách sạn · 64`, `✓ Phòng · 1.246`, `Địa điểm · 312`) | Ba thẻ theo bảng của C4 |
| Z · `EmptyState`, `SkeletonTable`, `Banner` | Trạng thái phụ |

**Không sáng tác thành phần mới.** Nếu cần gì chưa có trong bộ Z thì thêm vào bộ Z
(Phase 3 sở hữu), không tự vẽ riêng cho màn này.

## Ba bảng có embedding — không hơn

Từ `TABLE_COLUMNS` trong `embed_supabase_dag.py:55-59`: `hotels`, `rooms`,
`attractions`. **`room_prices` KHÔNG có cột `embedding`** — không được đưa vào bất
kỳ ô đếm nào (prompt thiết kế đã ghi rõ điều này ở C2).

## Màn C4 — Độ phủ embedding

**Khối trên:** ba thẻ, mỗi thẻ một bảng.

```
Khách sạn        Phòng            Địa điểm
64 / 64          1.184 / 1.246    312 / 312
✓ Đủ             62 chưa nhúng    ✓ Đủ
```

- Số lớn `font-size:26px; font-weight:700; tabular-nums` (như `bigNum` ở thiết kế).
- Thẻ có bản ghi thiếu: dải trái `inset 3px 0 0 var(--warn)`, dòng phụ `--warn-ink`.
- Thẻ đủ: dòng phụ `✓ Đủ` màu `--ok-ink`.

**Banner dưới** (khi có bản ghi thiếu), lấy nguyên câu từ A2:
`62 phòng chưa có embedding — bot sẽ không gợi ý được các phòng này.`

**Nút** `Chạy pipeline embedding` → mở hộp thoại C2 (Phase 15). Chưa có Phase 15 thì
điều hướng sang `/admin/pipelines`.

**Bảng chi tiết** (tuỳ chọn, chỉ khi số thiếu > 0): 20 bản ghi thiếu gần nhất, cột
`BẢNG` · `TÊN` · `THUỘC KHÁCH SẠN` · `CẬP NHẬT LÚC` — để admin biết cái gì đang thiếu
chứ không chỉ biết con số.

## Màn B7 — Trạng thái embedding (theo khách sạn)

Bảng cùng kiểu B1 nhưng lọc mặc định `embedding=missing`:

Cột: `KHÁCH SẠN` · `NGUỒN` · `SỐ PHÒNG` · `PHÒNG CHƯA NHÚNG` · `TRẠNG THÁI` · `⋯`

- `TRẠNG THÁI` dùng đúng ba giá trị của `embedding_state` (Phase 7):
  `embedded` → chấm `--ok` `Đã embed` ·
  `partial` → chấm `--warn` `Thiếu {n} phòng` ·
  `missing` → chấm `--warn` `Chưa embed`
- Chọn nhiều dòng → nút `Chạy embedding cho {n} khách sạn`.
- Trạng thái rỗng (mọi thứ đã nhúng): `✓ Toàn bộ dữ liệu đã được bot học.` — trạng
  thái rỗng **tích cực**, không dùng khung `Chưa có dữ liệu` mặc định.

> B7 và B1 dùng chung `admin_hotel_rows` (Phase 7) và chung component bảng. B7 thực
> chất là B1 với bộ lọc khác + 1 cột khác. **Tái dùng, đừng viết bảng thứ hai.**

## Backend — hợp đồng API

```
GET /api/v1/admin/embedding/summary
→ 200 {
    "tables": [
      {"table": "hotels",      "label": "Khách sạn", "total": 64,   "embedded": 64,   "missing": 0},
      {"table": "rooms",       "label": "Phòng",     "total": 1246, "embedded": 1184, "missing": 62},
      {"table": "attractions", "label": "Địa điểm",  "total": 312,  "embedded": 312,  "missing": 0}
    ],
    "total_missing": 62
  }
```

Đếm bằng `count="exact"` với filter `embedding=is.null` — ba cặp truy vấn, không tải
dòng nào về.

```
GET /api/v1/admin/embedding/missing?table=rooms&limit=20
→ 200 { "items": [{"id":"uuid","name":"Deluxe King","hotel_name":"...","updated_at":"..."}] }
```

```
POST /api/v1/admin/hotels/reembed
  body: { "hotel_ids": ["uuid"], "include_rooms": true }
→ 202 { "cleared_hotels": 3, "cleared_rooms": 128, "dag_run_id": "manual__...", "queued": true }
→ 200 { "cleared_hotels": 3, "cleared_rooms": 128, "queued": false,
        "detail": "airflow_unavailable" }
```

Hai bước tách bạch:

1. `UPDATE hotels SET embedding = NULL WHERE id = ANY(:ids)` (+ `rooms` nếu
   `include_rooms`). **Luôn chạy được**, không cần Airflow.
2. Kích hoạt DAG `embed_supabase_tables_pipeline` với `only_null=true` — **cần Phase 13**.

Nếu bước 2 hỏng, trả `200` (không phải lỗi) với `queued: false` — bước 1 đã có giá trị
thật, và lần chạy `@daily` kế tiếp sẽ nhặt các dòng NULL. UI nói đúng điều đó:
`Đã đánh dấu cần nhúng lại. Pipeline sẽ tự nhặt ở lần chạy kế tiếp, hoặc chạy ngay ở
mục Dữ liệu bot.`

Đây là endpoint dùng chung cho: nút hàng loạt ở B1 (L20), nút ở B7, và hộp thoại
re-embed ở B3/B5 (Phase 9, 10). **Một endpoint, không phải bốn.**

Audit: `action='embedding.reembed'`, `after = {hotel_ids, cleared_hotels, cleared_rooms}`.

## Frontend

```
src/admin/pages/embedding/
  embedding-coverage-page.tsx      C4
  embedding-status-page.tsx        B7 — tái dùng hotels-table của Phase 7
  embedding-table-cards.tsx        3 thẻ
```

Route: `/admin/pipelines/do-phu-embedding` (C4) và `/admin/embedding` (B7),
đúng bảng route ở Phase 3.

## Related Code Files

- Create: `backend/src/api/admin/embedding.py`
- Create: `backend/tests/test_api/test_admin_embedding.py`
- Create: `frontend/src/admin/pages/embedding/**`
- Modify: `backend/src/api/admin/__init__.py`, `frontend/src/admin/router.tsx`
- Modify: `frontend/src/admin/pages/hotels/hotels-bulk-bar.tsx` (nối nút `Chạy embedding`)
- Reference: `backend/src/airflow/dags/data_pipeline/embed_supabase_dag.py` (`TABLE_COLUMNS`)

## Implementation Steps

1. `GET /embedding/summary` — 3 cặp count.
2. `GET /embedding/missing`.
3. `POST /hotels/reembed` — bước 1 (clear) trước, bước 2 (trigger) bọc try/except.
4. Test.
5. C4 + B7, tái dùng bảng của Phase 7.

## Success Criteria

- [x] `summary` khớp `SELECT count(*) FILTER (WHERE embedding IS NULL) FROM rooms` cho cả 3 bảng
- [x] `room_prices` **không** xuất hiện ở bất kỳ đâu trong màn (grep xác nhận + test tự động)
- [x] `POST /hotels/reembed` khi Airflow chết → vẫn `200`, `embedding` đã NULL, `queued:false`
- [x] Sau reembed, C4 tăng đúng số `missing` (tính lại từ DB thật ở lần fetch kế tiếp)
- [x] B7 mặc định lọc `embedding=incomplete` (**không phải** `missing`), đổi filter cho ra cùng kết quả như B1 — lệch có chủ đích: B1's `missing` chỉ bắt `hotel_embedded=false`, bỏ sót khách sạn đã embed nhưng còn phòng chưa nhúng (`partial`), đúng thứ B7 phải hiện. Thêm giá trị filter mới `incomplete` = `hotel_embedded=false OR rooms_missing_embedding>0` vào `hotels.py`, không đổi ngữ nghĩa `missing`/`embedded` sẵn có của B1
- [x] Mọi thứ đã nhúng → B7 hiện trạng thái rỗng tích cực, không phải `Chưa có dữ liệu` (chỉ khi không lọc theo nguồn — lọc `source` mà rỗng thì dùng `EmptyState` trung tính, không khẳng định "toàn bộ dữ liệu" cho một lát cắt)
- [x] Nút `Chạy embedding` ở thanh hàng loạt B1 gọi đúng endpoint này (không tạo endpoint thứ hai) — qua hộp thoại xác nhận dùng chung `reembed-confirm-dialog.tsx`, `include_rooms` mặc định `false`, admin phải bật rõ ràng (đúng bảng rủi ro của phase này)
- [x] `summary` chạy dưới 500ms với 1.500 bản ghi (chỉ count, không tải dòng — `range(0,0)` + `count="exact"`, không `.select("*")`)

## Risk Assessment

| Rủi ro | Mức | Giảm thiểu |
|--------|-----|-----------|
| Nút reembed vô hiệu hoàn toàn khi Airflow chưa nối → Phase 9/10 bị chặn | Cao | Tách 2 bước; bước clear luôn chạy; trả 200 |
| Đưa `room_prices` vào ô đếm → admin tưởng giá cũng cần nhúng | Trung bình | Ghi rõ ở đầu file; có mục grep trong Success Criteria |
| Tạo 4 endpoint reembed cho 4 chỗ gọi | Trung bình | Một endpoint nhận `hotel_ids[]`; ghi rõ ở Architecture |
| Đếm bằng cách tải hết dòng về rồi `len()` | Trung bình | Dùng `count="exact"` của PostgREST; có mục đo thời gian |
| Clear `rooms.embedding` hàng loạt gây chạy lại tốn tiền API ngoài dự kiến | Trung bình | `include_rooms` mặc định `false`; UI hỏi rõ trước khi bật |
