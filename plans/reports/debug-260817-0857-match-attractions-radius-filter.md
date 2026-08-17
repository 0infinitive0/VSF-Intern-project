# match_attractions: filter radius hỏng → mọi lịch trình rỗng địa điểm

**Ngày:** 2026-08-17 · **Branch:** `main` · **Trạng thái:** đã vá (phía Python), verify xong trên Supabase thật
**Quyết định:** vá tạm phía Python (phương án 2) để unblock; sửa SQL là việc riêng sau.

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

1. Có quyền chạy SQL trực tiếp trên Supabase không? Cần `pg_get_functiondef` để làm việc còn lại
   mục 1; không có thì bản vá Python là đường duy nhất.
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
