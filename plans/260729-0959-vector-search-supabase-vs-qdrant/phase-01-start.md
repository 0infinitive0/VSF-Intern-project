---
title: "Phase 1: Parity và fixture"
status: todo
priority: P1
effort: "1-1.5d"
dependencies: []
---

# Phase 1: Parity và fixture

## Overview

Hard gate. Trước khi so sánh bất cứ thứ gì, hai store phải chứa **đúng cùng một
tập vector cho cùng một tập ID**. Hiện tại chúng không như vậy: Qdrant Cloud có
403 hotels và 0 attractions, trong khi Qdrant local có 1103 / 1013. Chạy
benchmark ở trạng thái này sẽ tạo ra số liệu trông hợp lý nhưng vô nghĩa —
Qdrant sẽ "thua" recall chỉ vì thiếu tài liệu, không phải vì thuật toán.

Phase này cũng dump corpus ra file để Phase 2 tính ground truth mà không phải
gọi lại store nào.

## Requirements

**Functional**
- [ ] Xác định nguồn vector chuẩn (authoritative source) và ghi rõ vào report
- [ ] Qdrant Cloud chứa đủ 3 collection với đúng số lượng point như local
- [ ] Cột `embedding` của `hotels` / `attractions` / `rooms` trên Supabase không có NULL
- [ ] Payload cần cho filter tồn tại ở cả hai phía và có cùng giá trị
- [ ] Dump `vectors.npy` + `payload.parquet` cho mỗi collection

**Non-functional**
- [ ] Parity check chạy lại được bằng một lệnh, exit code 0/1 để dùng làm gate
- [ ] Không sửa dữ liệu production Supabase ngoài việc backfill embedding còn thiếu

## Architecture

### Nguồn chuẩn

Theo memory `ec2-deployment`, **Qdrant local là nguồn vector chuẩn**, không phải
Qdrant Cloud. Supabase được nạp từ chính Qdrant local qua
`scripts/migrate_vectors_to_supabase.py`. Vậy luồng là:

```
Qdrant local (authoritative)
   ├──> dump ra .npy / .parquet   (fixture cho ground truth)
   ├──> re-sync lên Qdrant Cloud  (sửa thiếu 700 hotels + 1013 attractions)
   └──> verify khớp Supabase      (đã sync trước đó; chỉ kiểm, không ghi đè)
```

Nếu Qdrant local đã bị dọn hoặc không còn dữ liệu, nguồn chuẩn chuyển thành
Supabase (vì nó đang phục vụ production), và Qdrant Cloud được nạp từ Supabase.
Ghi rõ nhánh nào được dùng — nó ảnh hưởng tới cách diễn giải mọi số sau này.

### Đối chiếu payload cho filter

Hai phía lưu trường filter ở chỗ khác nhau. Bảng ánh xạ này phải đúng, nếu
không Phase 4 sẽ so hai filter không tương đương:

| Ý nghĩa | Supabase | Qdrant | Ghi chú |
|---|---|---|---|
| Thành phố | `hotels.destination_id` (`database_schema.sql:29`) | `metadata.destination_id` | Qdrant schema **đã khai index** nhưng ghi chú ở `qdrant_schema.py:66-71` nói `build_hotel_payload()` chưa sinh field này — phải kiểm thật |
| Hạng sao | `hotels.star_rating` `DECIMAL(2,1)` (`:36`) | `metadata.star_rating` (float) | **Có nửa sao.** `supabase_search.py:218` dùng `int(star)` → 3.5 thành 3. Giữ nguyên ở `S-current`, đo như defect ở Phase 4 |
| Giá thấp nhất | `room_prices.price` qua **2 cấp join** (`:92-95`) | `metadata.lowest_price` (float, phải thêm) | **Không phải thuộc tính tĩnh.** Theo cửa sổ ngày + cờ `sold_out`. Xem "Vấn đề giá" bên dưới |
| Loại attraction | `attractions.category` (`:153`) | `metadata.category` | |
| Giá vé | `attractions.ticket_price_adult` (`:159`) | *chưa có* | Phải bổ sung payload |

### Vấn đề giá — phải xử lý trong phase này

<!-- Updated: Validation Session 1 - giá ở room_prices, không ở rooms; chốt dùng snapshot đóng băng -->

`max_price` là filter dùng nhiều nhất trong query thật, và nó là chỗ khó nhất
của bài này. Ba sự thật xếp chồng:

1. `rooms` **không có** cột `price`. Giá ở `room_prices.price`, tới được qua
   `room_prices.room_id → rooms.id → rooms.hotel_id → hotels.id`.
2. Giá **theo cửa sổ ngày** (`check_in_date` / `check_out_date`) và có cờ
   `sold_out`. Một hotel không có "một giá".
3. Qdrant hiện chỉ có `price_tier` (keyword), lại đang bị hardcode `None` tại
   `scripts/sync_accommodations_to_qdrant.py:59`.

Supabase lấy giá live bằng join. Qdrant bắt buộc denormalize, và payload đó hỏng
sau mỗi lần crawl. So thẳng như vậy sẽ trộn *năng lực search* với *độ tươi dữ
liệu*, làm chênh lệch recall ở Phase 4 không quy được về nguyên nhân nào.

**Quyết định (Validation Session 1):** đóng băng một snapshot `lowest_price` cho
đúng một cửa sổ ngày cố định, cả ba nhánh cùng lọc trên đúng con số đó.

```sql
create materialized view bench_hotel_price_snapshot as
select h.id as hotel_id,
       min(rp.price) as lowest_price
from hotels h
join rooms r        on r.hotel_id = h.id
join room_prices rp on rp.room_id = r.id
where rp.check_in_date  = '<ngày cố định>'
  and rp.check_out_date = '<ngày cố định>'
  and rp.sold_out is not true
group by h.id;
```

Cửa sổ ngày chọn theo mật độ dữ liệu: lấy ngày có nhiều dòng `room_prices` nhất,
để `n_eligible` của tầng T3/T4 không bị teo vì thiếu giá chứ không phải vì filter chặt.

**Nhượng bộ này ưu đãi Qdrant và phải ghi chú ở mọi bảng số.** Production không
đóng băng được; chi phí thật của denormalize tính riêng ở Phase 5.3 dưới dạng
ops, không phải dưới dạng recall.

Việc này sửa `src/services/qdrant_schema.py` và producer payload thật (xác định
ở bước 2). Chạy `impact({target: "ensure_collection", direction: "upstream"})`
trước khi sửa, theo CLAUDE.md.

### Hai producer payload — phải xác định đúng đường trước khi sửa

<!-- Updated: Validation Session 1 - phát hiện producer thứ hai -->

Có **hai** nơi sinh metadata cho Qdrant, và chúng không giống nhau:

| Producer | Vị trí | Sinh gì |
|---|---|---|
| Script sync | `scripts/sync_accommodations_to_qdrant.py:54-59` | `destination_id`, `star_rating`, `price_tier=None` (hardcode) |
| Airflow DAG | `src/airflow/dags/data_pipeline/hotel_pipeline.py:486` `build_hotel_payload()` | Khác — phải đọc để biết |

Sửa nhầm nhánh không ai chạy thì Phase 4 sẽ đo một payload không tồn tại. Cách
xác định: đọc payload thật của vài point trên Qdrant Cloud, so với output của
từng producer, xem cái nào khớp. Chỉ sửa producer thắng, ghi lại kết luận.

## Related Code Files

- Create: `scripts/migrations/20260729_dump_production_rpcs.sql` — định nghĩa RPC production dump từ Supabase
- Create: `scripts/migrations/20260729_bench_price_snapshot.sql` — materialized view snapshot giá
- Create: `eval/vector_bench/dump_vectors.py`
- Create: `eval/vector_bench/parity_check.py`
- Create: `eval/fixtures/vector_bench/{hotels,attractions,rooms}.{npy,parquet}` (gitignore, ~30MB)
- Modify: `src/services/qdrant_schema.py` — thêm index `metadata.lowest_price`, `metadata.ticket_price_adult` (float)
- Modify: producer payload thật (xác định ở bước 2) — `scripts/sync_accommodations_to_qdrant.py:54-59` và/hoặc `src/airflow/dags/data_pipeline/hotel_pipeline.py:486`
- Modify: `scripts/sync_to_qdrant.py:52-58` — thêm `ticket_price_adult` dạng số (hiện chỉ có `ticket_price_range` dạng chuỗi)
- Modify: `tests/test_qdrant_schema.py` — `test_ensure_collection_creates_only_missing_indexes:54` sẽ hỏng khi spec thêm index
- Read-only: `scripts/migrate_vectors_to_supabase.py` (tham khảo cách map ID)

## Implementation Steps

<!-- Updated: Validation Session 1 - thêm bước 0 dump RPC và bước 2 xác định producer -->

0. **Dump định nghĩa RPC production về repo.** Việc đầu tiên, trước mọi thứ khác:
   ```sql
   select pg_get_functiondef(oid) from pg_proc
   where proname in ('match_hotels_with_rooms', 'match_attractions');
   ```
   Lưu vào `scripts/migrations/20260729_dump_production_rpcs.sql`. **Chặn cả
   plan cho tới khi có file này** — không biết RPC tính `lowest_price` thế nào
   (cửa sổ ngày nào, có loại `sold_out` không) thì ground truth cho `max_price`
   không định nghĩa được, và `S-current` không còn là baseline thật.
1. **Kiểm kê trạng thái hiện tại.** Đếm point mỗi collection ở Qdrant local và
   Qdrant Cloud; đếm dòng có `embedding IS NOT NULL` ở 3 bảng Supabase. Ghi bảng
   số vào report — bằng chứng cho tuyên bố "Cloud thiếu dữ liệu".
2. **Xác định producer payload thật.** Đọc payload của ~5 point hotels trên
   Qdrant Cloud, so với output của `sync_accommodations_to_qdrant.py:54-59` và
   của `build_hotel_payload()` (`hotel_pipeline.py:486`). Ghi kết luận. Chỉ sửa
   producer thắng.
3. **Chốt nguồn chuẩn** theo cây quyết định ở phần Architecture, ghi vào report.
4. **Tạo snapshot giá.** Chọn cửa sổ ngày có mật độ `room_prices` cao nhất, tạo
   materialized view `bench_hotel_price_snapshot`. Đây là nguồn giá duy nhất cho
   ground truth, `S-sql`, và payload Qdrant.
5. **Viết `dump_vectors.py`.** Scroll toàn bộ point (`with_vectors=True`,
   `with_payload=True`), ghi `vectors.npy` (float32, `[N, 1024]`, đã
   L2-normalize) + `payload.parquet` (cột: `point_id`, `entity_id`, mọi trường
   filter, và `lowest_price` từ snapshot). Thứ tự hàng hai file phải khớp —
   index hàng là khóa nối.
6. **Bổ sung payload giá.** Sửa `qdrant_schema.py` thêm index float; sửa producer
   thật để sinh `lowest_price` / `ticket_price_adult` **từ chính materialized
   view** ở bước 4, để ba nhánh dùng đúng một con số.
7. **Cập nhật `tests/test_qdrant_schema.py`** cho khớp spec mới. Chạy test trước
   khi sang bước sau.
8. **Re-sync Qdrant Cloud** từ nguồn chuẩn: cả 3 collection, đủ số lượng, đủ
   payload mới. `point_id()` là deterministic nên chạy lại không nhân bản.
9. **Backfill embedding Supabase còn thiếu** nếu bước 1 phát hiện NULL.
10. **Viết `parity_check.py`** với 4 assertion (xem Success Criteria) và exit code.
11. **Chạy gate.** Fail thì dừng plan, không sang Phase 2.

## Todo

- [ ] **Bước 0:** dump định nghĩa RPC production về `scripts/migrations/`
- [ ] Kiểm kê số lượng 3 nơi: Qdrant local / Qdrant Cloud / Supabase
- [ ] Xác định producer payload thật (script sync vs Airflow DAG)
- [ ] Chốt và ghi nguồn chuẩn
- [ ] Tạo materialized view `bench_hotel_price_snapshot`, chọn cửa sổ ngày
- [ ] `dump_vectors.py` + fixture .npy/.parquet
- [ ] Thêm payload index giá dạng float vào `qdrant_schema.py`
- [ ] Sửa producer thật sinh trường giá từ snapshot
- [ ] Cập nhật `tests/test_qdrant_schema.py`, chạy pass
- [ ] Re-sync Qdrant Cloud đủ 3 collection
- [ ] Backfill embedding NULL trên Supabase (nếu có)
- [ ] `parity_check.py` chạy pass

## Success Criteria

- [ ] Định nghĩa RPC production đã ở trong repo, đọc được cách tính `lowest_price`
- [ ] Producer payload thật đã xác định, có bằng chứng so khớp
- [ ] `bench_hotel_price_snapshot` tồn tại, cửa sổ ngày đã chọn và ghi lý do
- [ ] **Count parity**: số point mỗi collection ở Qdrant Cloud = số dòng có embedding ở bảng Supabase tương ứng
- [ ] **ID parity**: tập `entity_id` hai bên giống hệt (symmetric difference rỗng)
- [ ] **Vector parity**: với 100 ID lấy mẫu ngẫu nhiên, `cosine(v_supabase, v_qdrant) ≥ 0.9999`
- [ ] **Payload parity**: với cùng 100 ID, `destination_id` / `star_rating` / `lowest_price` / `category` khớp giá trị; `star_rating` giữ nguyên nửa sao (3.5 không thành 3)
- [ ] `tests/test_qdrant_schema.py` pass sau khi đổi spec
- [ ] `parity_check.py` exit 0
- [ ] Fixture dump lại được và cho ra file byte-identical

## Risk Assessment

| Rủi ro | Giảm thiểu |
|---|---|
| Qdrant local đã bị xóa (memory nói Qdrant "có thể drop để lấy RAM") | Kiểm ngay bước 1; fallback dùng Supabase làm nguồn chuẩn và ghi rõ |
| Sửa `qdrant_schema.py` ảnh hưởng sync script đang chạy Airflow | Chạy `impact` trước; thêm field là thao tác cộng thêm, index vắng mặt vô hại theo comment `qdrant_schema.py:66-68` |
| Re-sync Cloud vượt free tier | 4.3K × 1024 × 4B ≈ 18MB, còn rất xa 1GB |
| `metadata.` prefix gây filter trượt âm thầm | `qdrant_schema.py:35-46` đã cảnh báo đúng vấn đề này; parity check phải query thử một filter và xác nhận trả về > 0 kết quả |
| Backfill embedding làm hỏng dữ liệu production | Chỉ UPDATE dòng có `embedding IS NULL`; snapshot trước khi chạy |
| Không lấy được định nghĩa RPC (thiếu quyền) | Chặn cứng ở bước 0. Không có nó thì `S-current` không phải baseline thật — báo lại người dùng thay vì đoán |
| Cửa sổ ngày snapshot có quá ít dòng `room_prices` → `n_eligible` teo | Chọn ngày theo mật độ dữ liệu ở bước 4, không chọn tùy tiện; ghi số dòng vào report |
| Sửa nhầm producer payload không ai chạy | Bước 2 bắt buộc so payload thật trên Cloud trước khi sửa |
| Đổi spec collection làm hỏng `tests/test_qdrant_schema.py:54` | Bước 7 cập nhật test và chạy pass trước khi re-sync |
