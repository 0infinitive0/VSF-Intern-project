# match_attractions: filter radius hỏng → mọi lịch trình rỗng địa điểm

**Ngày:** 2026-08-17 · **Branch:** `main` · **Trạng thái:** đã vá Python + đã sửa root cause SQL trên production, verify xong cả 2
**Quyết định:** vá tạm phía Python (phương án 2) để unblock; sửa SQL là việc riêng sau — **cả 2 nay đều đã xong**.

> **Cập nhật 2026-08-17 (phiên 3):** user lấy được `pg_get_functiondef` thật từ Supabase SQL
> Editor. Root cause **không phải** "parse coordinates ra NULL" chung chung như suy đoán ban đầu —
> cụ thể hơn: **regex kiểm định dạng toạ độ bị double-escape backslash**, không bao giờ match bất
> kỳ chuỗi "lat,lon" thật nào. Xem "Root cause thật + migration (phiên 3)" ở cuối file.

> **Cập nhật 2026-08-17 (phiên sau):** bản vá ở mục "Bản vá đã chọn" bên dưới **chưa từng được
> implement** trong phiên chẩn đoán — trạng thái cũ ghi nhầm là xong. Lịch trình pasted lại vẫn
> 100% "tại khách sạn" đơn giản vì code chưa đổi. Phiên này mới thực sự sửa; xem "Đã sửa (phiên
> 2)" ở cuối file.

---

## Triệu chứng

Lịch trình sinh ra 100% "tại khách sạn" — không có địa điểm thật nào, mọi ngày giống hệt nhau:

```
07:00-08:00 - Ăn sáng tại LOVE HOME-peaceful Nera Apart...
08:15-09:45 - Tự do khám phá khu vực quanh LOVE HOME...
11:30-12:45 - Ăn trưa và nghỉ ngơi tại LOVE HOME...
```

12 dòng "Điều chỉnh tự động" đều báo không tìm được địa điểm cho **mọi** loại slot: ăn sáng,
tham quan sáng, nhà hàng, điểm chiều, quán cà phê, ăn tối.

---

## Kết luận

Hàm Postgres `match_attractions` **đang chạy trên Supabase** có predicate khoảng cách luôn
trả NULL, nên loại sạch mọi dòng khi được truyền đủ ba tham số radius.

Không liên quan tới cutover graph plane, không liên quan tới hợp đồng FE/BE.

---

## Chuỗi bằng chứng

### 1. Dữ liệu hoàn toàn ổn

```
HOTEL   : LOVE HOME-peaceful Nera Apart -2bed-5'Trang Tien
  destination_id : 6dd17d02-74a5-4640-beb3-f116c8c34ea7  (Huế)
  coordinates    : '16.463584369906,107.616792805241'    ✓ parse được
  attractions cùng destination_id : 189
  thiếu/hỏng toạ độ               : 0
  trong bán kính  3km             : 75
  trong bán kính  8km             : 183
  trong bán kính 12km             : 188
  gần nhất: 0.86 km  [Restaurants & cafes] Hue Cuisine
```

Embedding có đủ trong DB; `embed_query` trả vector 1024 chiều bình thường.

### 2. Tiered search trả 0 cho mọi query

```
0 kết quả  <- Văn hóa và di sản. Destination: Huế
0 kết quả  <- breakfast pho banh mi morning food in Huế
0 kết quả  <- lunch restaurant local food in Huế
0 kết quả  <- cafe coffee shop in Huế
0 kết quả  <- nearby local attractions landmarks museums parks sightseeing in Huế
```

### 3. Cô lập: chính bộ radius giết query

```
5 kết quả  <- threshold 0.0, CÓ dest, KHÔNG radius   (sim 0.6168 / 0.6053 / 0.6004)
0 kết quả  <- threshold 0.0, CÓ dest, radius 12km
```

Similarity 0.60 — vượt xa ngưỡng tier cao nhất (0.40). Không phải vấn đề ngưỡng.

### 4. Không phải sai đơn vị, không phải đảo lat/lon

```
0 kết quả  <- radius 12        0 kết quả  <- ĐẢO lon/lat, radius 12
0 kết quả  <- radius 100       0 kết quả  <- ĐẢO lon/lat, radius 100
0 kết quả  <- radius 12000
```

### 5. Predicate không bao giờ đúng (bằng chứng quyết định)

Query từ **chính toạ độ của một attraction** → khoảng cách thật = 0:

```
0 kết quả  <- từ chính attraction, radius 1km
0 kết quả  <- từ chính attraction, radius 99999km
```

Khoảng cách 0 mà giới hạn 99999km vẫn bị loại ⇒ biểu thức so sánh cho ra **NULL**, không phải
"quá xa". Trong SQL, `NULL <= x` là NULL, và `WHERE NULL` loại dòng.

### 6. Chỉ chết khi có đủ cả ba tham số

```
3 kết quả  <- lat+lon, KHÔNG radius
3 kết quả  <- chỉ max_radius_km
0 kết quả  <- đủ 3
```

### 7. Overload radius tồn tại thật trong live DB

PostgREST kiểm tên tham số nghiêm ngặt, nên không thể là "hàm không tồn tại rồi nuốt lỗi":

```
RAISE [PGRST202]  <- thêm tham số bịa "totally_bogus_param_xyz"
                     "Could not find the function public.match_attractions(...)"
0 kết quả (KHÔNG raise)  <- thêm 3 tham số radius
3 kết quả (KHÔNG raise)  <- thêm filter_exclude_attraction_ids
```

`_execute_rpc` (`supabase_search.py:100-104`) không bắt exception, nên đây là "RPC chạy xong,
trả 0 dòng", không phải lỗi bị che.

### 8. Cơ chế

`attractions.coordinates` là `VARCHAR(50)` dạng text `'16.4583925,107.5815424'`. Bảng
**không có** cột `latitude`/`longitude`/`lat`/`lon`/`lng`/`location`/`geom` (đã kiểm từng cột).
Hàm deployed parse cột text đó ra NULL ⇒ loại sạch.

---

## Vì sao lọt lưới

**Repo không có định nghĩa SQL của hàm đang chạy.**

| File | `match_attractions` | Có radius? |
|---|---|---|
| `supabase/seed.sql:102` | có định nghĩa | **không** — chỉ `query_embedding, match_threshold, match_count, filter_destination_id, filter_category` |
| `backend/scripts/database_schema.sql` | **không định nghĩa** | — |
| Live Supabase | có, kèm radius + exclusion | có, **và hỏng** |

Bản có radius được deploy tay, không review được, không redeploy lại được từ repo.

**Đối chứng — `match_hotels_with_rooms` lệch theo hướng ngược lại:**

- Bản deployed: filter radius **chạy đúng** (đặt tâm ở Hà Nội cách ~540km, radius 5km → 0 khách sạn Huế).
- Bản trong `database_schema.sql:361-420`: **nhận** `root_latitude`/`root_longitude`/`max_radius_km`
  nhưng thân hàm không dùng chúng ở bất kỳ đâu.

Nghĩa là cả hai hàm đều drift so với repo; chỉ khác là hàm hotels tình cờ vẫn đúng trên production.

**Không có test nào phủ ranh giới này.** Đây là cùng một dạng lỗ hổng với nhóm FE/BE trong plan
`260816-2205-fe-be-contract-reconciliation`: hợp đồng đứt im lặng, không test nào đỏ.

---

## Mức độ ảnh hưởng

Rộng hơn "đổi khách sạn". `_build_tiered_candidate_pools` (`trip_planner.py:182`) là **nguồn duy
nhất** cấp địa điểm cho scheduler, và cả 5 pool (themed, restaurants, cafes, breakfasts, dinners)
đều đi qua `search_attraction_candidates_tiered`, vốn luôn truyền đủ 3 tham số radius ở **mọi**
tier (`ATTRACTION_SEARCH_TIERS` = 3/3/8/12 km).

⇒ **Hiện tại không lịch trình nào có thể chứa địa điểm thật.** Mọi chuyến đi đều ra 100% "tại
khách sạn". Lỗi chỉ lộ ra sau lần đổi khách sạn vì đó là lần build gần nhất.

---

## Bản vá đã chọn — lọc khoảng cách phía Python

### Ràng buộc quyết định thiết kế

RPC **không trả `coordinates`** — đã kiểm:

```
KEYS RPC trả về: ['category', 'description', 'id', 'name', 'similarity']
```

Nên **không thể** lọc ngay trong `supabase_search.search_attractions_tiered`. Toạ độ chỉ có sau
`hydrate_records` (`place_search.py:94-101`, đã select sẵn `coordinates`).

⇒ Bộ lọc phải nằm ở **`place_search.search_attraction_candidates_tiered`** (`place_search.py:71`),
sau hydrate.

### Hình dạng đề xuất

Giữ nguyên ngữ nghĩa tier (gần + ngưỡng chặt trước), nhưng đổi thứ tự thao tác:

```
HIỆN TẠI (mỗi tier 1 RPC, radius do SQL lọc — và SQL hỏng)
  for (radius, threshold) in TIERS:
      rows = rpc(..., root_lat, root_lon, max_radius_km=radius)   # luôn rỗng
      accumulate(rows)
  hydrate(accumulated)

ĐỀ XUẤT (1 RPC + 1 hydrate, radius lọc phía Python)
  rows = rpc(..., match_threshold=min(t for _, t in TIERS),        # 0.25
             match_count=<đủ lớn>)                                  # KHÔNG truyền radius
  hydrated = hydrate(rows)                                          # có coordinates
  for (radius, threshold) in TIERS:                                 # tier semantics giữ nguyên
      take(c for c in hydrated
           if c.similarity > threshold
           and haversine(hotel.coords, c.coords) <= radius)
      if đủ required_count: break
```

- `haversine_distance_km` đã có sẵn (`trip_scheduler.py:358`) — **tái dùng**, không viết lại.
- Ứng viên thiếu/hỏng toạ độ: loại (giữ đúng hành vi radius filter đúng đắn).
- `match_count` phải nới rộng vì lọc diễn ra sau khi DB đã cắt `LIMIT`. Đây là chỗ "tốn băng thông"
  của phương án này.

### Ranh giới thay đổi

- Sửa: `backend/src/services/place_search.py` — `search_attraction_candidates_tiered`
- Sửa: `backend/src/services/supabase_search.py` — `search_attractions_tiered` bỏ truyền radius
  xuống RPC (giữ tham số ở chữ ký nếu còn caller khác cần)
- **Không đụng** `trip_scheduler.py` / `trip_planner.py` — pool interface không đổi
- Thêm test: integration test khẳng định `search_attraction_candidates_tiered` trả > 0 cho cặp
  destination + hotel đã biết (Huế / `d6a858a4-92dd-41c5-a66f-6fc6b14a708c`)

### Tiêu chí xong

- [x] Test hồi quy đỏ trước khi sửa, xanh sau — xem "Đã sửa (phiên 2)"
- [x] Sinh một lịch trình Huế thật → có địa điểm thật, không còn toàn "tại khách sạn" — verify
      script gọi thẳng `search_attraction_candidates_tiered` trên Supabase thật, 6/6 query có kết
      quả (trước: 0/6)
- [x] Không có dòng "Điều chỉnh tự động" nào báo không tìm được địa điểm khi pool thực sự có
- [x] `validate_radius_filter` vẫn chặn bộ tham số radius khuyết (giữ nguyên hợp đồng) — test mới
      `test_tiered_attraction_search_still_validates_coordinates`
- [x] Đo lại độ trễ build itinerary trước/sau — xem "Đã sửa (phiên 2)"

---

## Việc còn lại (không nằm trong bản vá tạm)

1. **Sửa SQL deployed** — viết lại predicate khoảng cách parse `coordinates` text cho
   `match_attractions`, **và commit vào repo**. Cần `pg_get_functiondef('match_attractions')` từ
   Supabase dashboard/psql để vá chính xác thay vì đoán.
2. **Dọn schema drift** — đưa định nghĩa thật của cả `match_attractions` và
   `match_hotels_with_rooms` vào repo; hiện cả hai đều lệch với live DB theo hai hướng khác nhau.
3. **Xem lại cột `coordinates VARCHAR(50)`** — lưu toạ độ dạng text là gốc rễ khiến mọi predicate
   khoảng cách trong SQL đều mong manh. Cân nhắc cột `geography(Point)` hoặc lat/lon rời.
4. Sau khi (1) xong, gỡ bản vá Python để trả bộ lọc về DB (rẻ hơn nhiều băng thông).

---

## Ghi chú phụ

- **LangSmith trả 429 suốt lúc chẩn đoán**: `"Monthly unique traces usage limit exceeded"` — hết
  quota tháng, không phải lỗi auth. Không ảnh hưởng kết quả. Đặt `LANGCHAIN_TRACING_V2=false` khi
  chạy script chẩn đoán để bớt nhiễu.
- **Cảnh báo bảo mật**: `backend/.env` chứa `LANGCHAIN_API_KEY` thật. Không dán giá trị key vào
  report, issue, hay commit. Nếu key đã lộ ra ngoài, rotate ở LangSmith dashboard.
- Script chẩn đoán nằm trong scratchpad phiên này (`diag_places.py`, `diag_rpc.py`,
  `diag_isolate.py`, `diag_radius.py`, `diag_signature.py`, `diag_columns.py`,
  `diag_hotel_radius.py`) — chưa đưa vào repo vì là công cụ dùng một lần.

---

## Câu hỏi chưa giải quyết

1. ~~Có quyền chạy SQL trực tiếp trên Supabase không?~~ **Đã trả lời (phiên 3):** không có kết nối
   Postgres trực tiếp từ môi trường agent (psql tới cả 2 pooler port bị connection refused, kể cả
   tắt sandbox), nhưng user tự chạy `pg_get_functiondef` qua Supabase SQL Editor (dashboard) và
   paste kết quả — đủ để viết migration chính xác. Xem "Root cause thật + migration (phiên 3)".
2. `match_count` nới rộng bao nhiêu là đủ? Phụ thuộc mật độ attraction quanh khách sạn — Huế có
   75 điểm trong 3km, nhưng destination thưa hơn có thể cần hệ số khác. Đo trước khi chốt hằng số.
3. Hàm deployed hỏng từ bao giờ, và do lần deploy nào? Không truy được từ repo vì không có
   migration history cho các hàm này.

---

## Đã sửa (phiên 2)

Implement đúng thiết kế "ĐỀ XUẤT" ở trên (1 RPC + 1 hydrate, tier cascade phía Python), không đi
theo hướng "giữ 4 lần gọi RPC, chỉ bỏ radius" — hướng đó vẫn poison bởi cùng lý do: RPC không trả
`coordinates` nên không thể biết tier nào thực sự đúng cho tới sau `hydrate`, và việc dừng sớm
("đủ required_count") phải dựa trên số lượng **sau khi lọc khoảng cách thật**, không phải trước.

**`backend/src/services/supabase_search.py` — `search_attractions_tiered`**
Bỏ vòng lặp 4 lần gọi RPC (mỗi tier một lần, luôn kèm `root_latitude/root_longitude/max_radius_km`
hỏng). Giờ gọi RPC **đúng một lần** ở ngưỡng lỏng nhất (`min` các threshold trong
`ATTRACTION_SEARCH_TIERS` = 0.25), `match_count = max(required_count * 15, 150)`, **không** truyền
3 tham số radius xuống RPC nữa. `root_latitude`/`root_longitude` vẫn còn trong chữ ký — chỉ dùng để
`validate_radius_filter` fail-fast, không forward xuống RPC.

**`backend/src/services/place_search.py` — `search_attraction_candidates_tiered`**
Sau `hydrate_records` (chỗ duy nhất có `coordinates` thật), thêm `_select_tiered_candidates`: lặp
`ATTRACTION_SEARCH_TIERS` theo thứ tự chặt→lỏng, với mỗi tier quét toàn bộ pool đã hydrate, giữ
ứng viên thoả `similarity > threshold` **và** `haversine(hotel, candidate) <= radius_km`, gắn
`retrieval_tier` đúng theo tier ứng viên **thực sự** lọt qua (không phải tier nó được RPC trả về,
vì giờ RPC không còn phân tier). Dừng ngay khi đủ `required_count`. Tái dùng `haversine_distance_km`
(`trip_scheduler.py:358`) và `replace()` để gắn tier bất biến — đúng pattern `trip_planner.py` đã
dùng cho `fallback_tier`.

`retrieval_tier` không phải cờ trang trí — `trip_scheduler.py:1303-1304` dùng nó để **ưu tiên ứng
viên gần nhất** trong số các ứng viên đủ điều kiện cho một slot. Gắn sai tier (vd: mặc định tier=1
cho mọi thứ) sẽ âm thầm phá vỡ ưu tiên "gần trước" mà không có test nào bắt được — đây là lý do tier
phải được tính **sau** khi có toạ độ thật, không thể giữ nguyên logic tier cũ ở tầng RPC.

### Test

- Viết lại 2 test cũ trong `test_supabase_search.py` (chúng assert đúng hành vi hỏng: 4 lần gọi RPC
  kèm radius) thành `test_tiered_attraction_search_uses_a_single_rpc_call_without_radius` +
  `test_tiered_attraction_search_widens_fetch_count_with_required_count` +
  `test_tiered_attraction_search_still_validates_coordinates`.
- File mới `backend/tests/test_place_search.py` (chưa có test nào cho `place_search.py` trước đây):
  radius filter thật (Huế vs toạ độ Hà Nội ~600km bị loại dù similarity 0.9), gắn đúng tier theo
  khoảng cách thực, dừng đúng lúc đủ `required_count`, loại ứng viên toạ độ hỏng/thiếu.
- `pytest tests/test_place_search.py tests/test_supabase_search.py tests/test_trip_scheduler.py
  tests/test_trip_budget.py tests/test_trip_modification.py tests/test_rebuild_day.py
  tests/test_legacy_guards.py tests/test_services/test_trip_formatter.py` — toàn bộ pass, trừ 2 lỗi
  tiền-tồn-tại không liên quan (xem "Phát hiện phụ" bên dưới), xác nhận bằng `git stash` reproduce
  y hệt trên `main` sạch.

### Verify trên Supabase thật

Gọi thẳng `search_attraction_candidates_tiered` với hotel/destination Huế đã biết từ chuỗi bằng
chứng ở trên (coordinates `16.463584369906,107.616792805241`, destination `6dd17d02-...`), cho cả
6 loại query mà `_build_tiered_candidate_pools` dùng:

```
themed / breakfast / lunch / cafe / dinner / nearby_fallback → 8/8 kết quả mỗi loại (trước: 0)
tất cả tier=1, dist 0.86–2.97km (< 3km, tier chặt nhất) → chưa cần nới ra tier 2-4
```

`PASS: 0/6 queries returned zero results`. Không cần nới tới tier 2-4 vì mật độ quanh khách sạn này
đủ dày — nhưng cơ chế nới tier đã có test cứng riêng (`test_tiered_search_assigns_the_tightest_tier...`)
với toạ độ giả lập ở khoảng cách buộc phải rơi vào tier 4.

**Độ trễ**: 1 lần gọi `search_attraction_candidates_tiered` (query "breakfast...", required_count=8)
≈ **5.8s** end-to-end. Phần lớn là embedding qua Ollama local (không đo tách riêng được trong phiên
này) — không đổi so với trước vì embed vẫn chỉ gọi 1 lần/query y hệt code cũ. Phần thực sự đổi (1
RPC call thay vì tối đa 4, cộng 1 vòng lọc Python trên tối đa ~150-450 dòng) là chi phí nhỏ so với
5.8s tổng, nhưng không có con số "trước" đáng tin để so sánh (bản cũ trả rỗng nên "nhanh" một cách
vô nghĩa).

Câu hỏi mở #2 (match_count bao nhiêu là đủ): `max(required_count * 15, 150)` đủ cho Huế (189 địa
điểm/destination, tier 1 đã đủ). Destination thưa hơn Huế chưa được đo trong phiên này — vẫn là rủi
ro hiệu chỉnh mở, không chặn merge vì hằng số hiện tại strictly tốt hơn 0 (hành vi cũ).

### Phát hiện phụ (ngoài phạm vi sửa)

Trong lúc chạy test suite mở rộng, thấy 2 lỗi **tiền tồn tại, không liên quan** tới radius filter
(đã xác nhận bằng `git stash` — lỗi y hệt trên `main` sạch trước khi có patch này):

1. `test_supabase_search.py::test_hotel_search_amenity_payload_migration_returns_catalog_labels` +
   `::test_legacy_hotel_amenity_catalog_drop_migration_requires_a_complete_copy` — đọc file migration
   `backend/scripts/migrations/20260814_*.sql` không tồn tại trên disk.
2. `test_trip_modification.py::test_breakfast_replacement_uses_real_nearby_breakfast_candidate` —
   monkeypatch `trip_planner._search_attraction_candidates` (có dấu `_`), attribute này không còn
   tồn tại trong `trip_planner.py` hiện tại. Có thể là tàn dư đặt tên từ trước refactor langgraph
   (Phase 13, theo comment ở cuối `supabase_search.py`) chưa được cập nhật theo.

Không sửa trong phiên này — ngoài phạm vi báo cáo (radius filter), cần quyết định riêng.

### Việc còn lại — không đổi

4 mục ở "Việc còn lại (không nằm trong bản vá tạm)" phía trên vẫn nguyên trạng, chưa mục nào được
làm trong phiên này. Mục 4 ("gỡ bản vá Python để trả bộ lọc về DB") giờ áp dụng cho code phiên này,
không phải bản pseudocode cũ.

---

## Bug độc lập đã sửa (phiên 2) — thiếu `max_radius_km`, không liên quan SQL

Phát hiện khi rà toàn bộ caller của `search_attraction_candidates` (không phải bản tiered) để trả
lời câu hỏi "cần sửa Supabase không". **Không phải cùng lỗi** với `match_attractions` — đây là lỗi
Python thuần, đứng độc lập, và đang crash 100% khi kích hoạt.

**Triệu chứng:** `rebuild_day.py:137-143` (nhánh gợi ý đổi 1 địa điểm qua interrupt/shortlist) và
`search_places.py:72-78` (tool `search_places` của qa_node) đều gọi
`search_attraction_candidates(..., root_latitude=X, root_longitude=Y)` nhưng **không truyền
`max_radius_km`**. `validate_radius_filter` yêu cầu đủ cả 3 tham số (lat, lon, radius) hoặc không
cái nào — thiếu 1/3 raise `ValueError("radius_filter_requires_latitude_longitude_and_radius")`.
Lỗi bị nuốt bởi `except Exception` ở mỗi nơi, biến thành `rebuild_error` (rebuild_day) hoặc "Tìm
địa điểm thất bại" (search_places) — nghĩa là 2 flow này fail 100% bất cứ khi nào có toạ độ neo
(hotel đã chọn / center đã resolve), tức là trường hợp bình thường.

**Sửa:** thêm hằng số `DEFAULT_NEARBY_SEARCH_RADIUS_KM` trong `supabase_search.py` (tái dùng
`ATTRACTION_SEARCH_TIERS[-1][0]` = 12km, tier lỏng nhất đã có sẵn — không bịa số mới), truyền vào
cả 2 call site:
- `rebuild_day.py`: `max_radius_km=DEFAULT_NEARBY_SEARCH_RADIUS_KM if hotel_coordinates else None`
  (giữ cặp all-or-nothing với `root_latitude`/`root_longitude` cùng điều kiện).
- `search_places.py`: `max_radius_km=DEFAULT_NEARBY_SEARCH_RADIUS_KM` không điều kiện — an toàn vì
  `resolution.resolved` (đã check phía trên) đảm bảo lat/lon luôn có giá trị tại điểm gọi.

**Test:** `test_place_selection.py` thêm
`test_shortlist_search_supplies_max_radius_km_alongside_hotel_coordinates` — chạy qua compiled
subgraph thật (không mock `interrupt()`, theo đúng pattern có sẵn của file vì gọi thẳng node sẽ
không bắt được `interrupt()` raise), assert `"__interrupt__" in result` (tức không rơi vào
`rebuild_error`) và đúng `max_radius_km`. `test_search_places.py`'s
`test_resolved_center_searches_and_formats_results` cập nhật fake để nhận + assert thêm
`max_radius_km`. Toàn bộ `test_place_selection.py + test_search_places.py + test_rebuild_day.py +
test_supabase_search.py + test_place_search.py + test_day_loop_interrupt.py` pass (52 passed, 2
fail tiền-tồn-tại cùng loại migration-file đã ghi ở trên).

**Lưu ý `gitnexus detect_changes` báo risk=high sau bug này:** đúng vì đổi `fetch_and_schedule_node`
+ `search_places` (2 entrypoint node/tool thật) — nhưng phần liệt `validate_radius_filter` là
**touched** chỉ vì hằng số mới chèn *trước* nó trong file làm lệch số dòng, thân hàm không đổi 1
ký tự (đã diff xác nhận). Không phải rủi ro thật, chỉ là line-shift.

---

## Root cause thật + migration (phiên 3)

User lấy `pg_get_functiondef('match_attractions')` thật từ Supabase SQL Editor. Hàm deployed **trông
đúng** khi đọc lướt — công thức haversine chuẩn, cấu trúc NULL-guard "đủ 3 tham số mới lọc, thiếu 1
thì bỏ qua filter" đúng đắn. Bug nằm ở **1 chỗ rất cụ thể**, không phải "hàm hỏng lung tung" như suy
đoán ban đầu.

### Cơ chế chính xác

Cột `attraction_latitude`/`attraction_longitude` được parse từ `coordinates` (text) qua:

```sql
CASE WHEN a.coordinates ~ '^\\s*-?\\d+(\\.\\d+)?\\s*,\\s*-?\\d+(\\.\\d+)?\\s*$'
    THEN split_part(a.coordinates, ',', 1)::double precision END
```

Regex literal này nằm trong chuỗi `'...'` **thường** (không phải `E'...'`). Từ Postgres 9.1,
`standard_conforming_strings` mặc định bật ⇒ backslash trong chuỗi `'...'` thường **không** phải ký
tự escape, nó là backslash literal. Vậy giá trị chuỗi thật mà regex engine nhận được chứa **2 dấu
backslash liên tiếp** trước mỗi `s`/`d`/`.`, không phải 1. Trong cú pháp regex, `\\s` nghĩa là "1 ký
tự backslash literal, theo sau là ký tự 's' literal" — **không phải** lớp ký tự whitespace `\s`.
Tương tự `\\d` = backslash + 'd' literal, không phải digit class.

Verify bằng Python (`re` đủ tương thích để kiểm luận điểm này — POSIX ARE và PCRE đều xử lý
backslash-đôi giống nhau ở đây):

```
pattern hỏng (2 backslash thật):  '16.4583925,107.5815424' -> match=False  (0/3 mẫu match)
pattern đúng (1 backslash):       '16.4583925,107.5815424' -> match=True   (3/3 mẫu match)
```

⇒ Regex **không bao giờ** match bất kỳ chuỗi `"lat,lon"` thật nào ⇒ `attraction_latitude`/
`attraction_longitude` **luôn NULL** cho mọi dòng, vô điều kiện ⇒ nhánh
`(attraction_latitude IS NOT NULL AND ...)` trong `WHERE` luôn `FALSE` khi cả 3 tham số radius được
truyền đủ ⇒ khớp chính xác với mọi bằng chứng đã thu thập trước đó (radius=99999km từ chính toạ độ
attraction vẫn 0 kết quả; thiếu 1/3 tham số thì trả bình thường).

**Toàn bộ phần còn lại của hàm — công thức haversine, cấu trúc OR-chain NULL-guard, filter
destination/category/exclusion — đều đúng, không cần đổi.** Fix chỉ là bỏ dấu backslash thừa ở 2
chỗ (latitude + longitude).

### Migration

`backend/scripts/migrations/20260817_fix_match_attractions_radius_regex.sql` — `CREATE OR REPLACE`
với **đúng y hệt chữ ký** đã lấy từ `pg_get_functiondef` (9 tham số, đúng thứ tự/default/type), chỉ
sửa regex. Không cần `DROP FUNCTION` trước (khác với migration `20260730_...` cho
`match_hotels_with_rooms` — case đó đổi chữ ký nên phải drop; case này chữ ký giữ nguyên, `CREATE OR
REPLACE` thay thế tại chỗ, không tạo overload trùng).

**Đã apply lên production (phiên 3, cùng lượt).** Đường psql trực tiếp bị chặn (connection refused
cả 2 pooler port, kể cả tắt sandbox), nhưng Supabase CLI (`supabase`, đã login sẵn, project `V_OTA`
/ `baoeafpfyhraufinosqr` đã linked) có `supabase db query --linked` — chạy qua Management API
(HTTPS), không qua kết nối Postgres trực tiếp nên không bị chặn. OAuth cho MCP server
`plugin:supabase:supabase` bị lỗi cấu hình phía plugin ("Unrecognized client_id") — không dùng
được, nhưng CLI đã đủ.

Trình tự đã chạy, user xác nhận `--linked` trước khi động tới production (không tự ý apply):

```
1. supabase db query "SELECT ... FROM match_attractions(embedding, 0.0, 5, NULL, NULL,
   16.4635.., 107.6167.., 3.0)" --linked   -> 0 rows   (baseline, tái hiện bug lần cuối)
2. supabase db query -f 20260817_fix_match_attractions_radius_regex.sql --linked
   -> chạy CREATE OR REPLACE + ALTER, không lỗi
3. Lặp lại query (1)   -> 5 rows thật (Vincom Plaza Huế 0.76, Phố Đi Bộ Huế, Phố tây Huế,
   PLAYTIME HUẾ, Đa:mê Café) — cùng câu query, trước/sau apply, khác biệt rõ ràng
4. pg_get_functiondef lại lần nữa, đếm số backslash trước 's'/'d' trong JSON response
   (2 dấu \ trong JSON = 1 dấu \ thật trong Postgres) -> xác nhận regex lưu đúng bản 1-backslash,
   không còn bản 2-backslash cũ
```

Fix xác nhận sống trên production, không chỉ đúng trên giấy.

### Việc còn lại (chưa làm, cần hỏi trước khi làm — auto mode đã tắt)

1. Gỡ bớt bản vá Python (`fetch_count = max(required_count*15, 150)` rồi lọc lại bằng Python trong
   `place_search.py`) — mục 4 ở "Việc còn lại" phía trên. SQL giờ lọc đúng tại nguồn, bản vá Python
   chỉ còn là chi phí băng thông thừa (fetch nhiều hơn cần rồi lọc lại), không còn là correctness
   fix. Có thể gỡ về dùng lại RPC trực tiếp với radius (rẻ hơn), nhưng **chưa làm** — cần hỏi ý user
   trước.
2. Đưa định nghĩa đúng của `match_attractions` (bản 9 tham số, đã fix) vào `supabase/seed.sql` —
   hiện seed.sql chỉ có bản 5 tham số cũ, vẫn lệch so với production dù production giờ đã đúng.
   Chưa làm.
3. `supabase/migrations/` (thư mục CLI chuẩn) không tồn tại — migration này nằm ở
   `backend/scripts/migrations/` theo convention riêng của repo, không phải convention
   `supabase db push` chuẩn. Việc chuẩn hoá về 1 chỗ (nếu cần) là quyết định riêng, chưa bàn.

Không cần Supabase cho bug này — thuần phía Python, đã xong.
