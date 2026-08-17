# match_attractions: filter radius hỏng → mọi lịch trình rỗng địa điểm

**Ngày:** 2026-08-17 · **Branch:** `feat/refactor-langgraph` · **Trạng thái:** đã chẩn đoán, chưa sửa
**Quyết định:** vá tạm phía Python (phương án 2) để unblock; sửa SQL là việc riêng sau.

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

- [ ] Test hồi quy đỏ trước khi sửa, xanh sau
- [ ] Sinh một lịch trình Huế thật → có địa điểm thật, không còn toàn "tại khách sạn"
- [ ] Không có dòng "Điều chỉnh tự động" nào báo không tìm được địa điểm khi pool thực sự có
- [ ] `validate_radius_filter` vẫn chặn bộ tham số radius khuyết (giữ nguyên hợp đồng)
- [ ] Đo lại độ trễ build itinerary trước/sau — ghi lại con số, đây là chi phí đã chấp nhận

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
