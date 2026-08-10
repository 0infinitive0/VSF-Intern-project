---
title: "Phase 4: Tiêu chí B — vector search + filter"
status: todo
priority: P1
effort: "1-1.5d"
dependencies: [1, 2, 3]
---

# Phase 4: Tiêu chí B — vector search + filter

# Phase quyết định

## Overview

Đây là phase sinh ra con số thật sự quyết định. Tiêu chí A gần như chắc chắn hòa
(xem Phase 3); filter là nơi kiến trúc hai hệ thống khác nhau về bản chất.

Ba cách xử lý filter đang so:

| Nhánh | Cơ chế | Điểm gãy dự kiến |
|---|---|---|
| `S-current` | ANN lấy `k×3` rồi lọc trong Python (`supabase_search.py:202`, `:214-225`) | Chọn lọc thấp: nếu chỉ 1% corpus thỏa filter thì trong 30 ứng viên gần nhất trung bình chỉ ~0.3 cái hợp lệ |
| `S-sql` | WHERE trước ANN trong Postgres | Không có điểm gãy về đúng đắn; có thể chậm nếu planner chọn sai |
| `Q-native` | Payload index + filtered HNSW | Qdrant tự chuyển sang brute force khi filter quá chặt; ở corpus 1K thì luôn exact |

Giả thuyết đăng ký trước: **`S-current` sụt recall mạnh từ T2 trở đi và gần như
vô dụng ở T4, trong khi `S-sql` và `Q-native` giữ recall ≈ 1.0.** Nếu đúng, kết
luận đúng đắn **không phải** "migrate sang Qdrant" mà là "sửa RPC Supabase" —
rẻ hơn nhiều lần. Phase này tồn tại để chứng minh hoặc bác bỏ điều đó bằng số.

## Requirements

**Functional**
- [ ] Viết RPC `S-sql` đẩy toàn bộ filter vào SQL
- [ ] Chạy 42 query T1-T4 trên cả ba nhánh
- [ ] Filtered Recall@10 tách theo tầng chọn lọc
- [ ] Shortfall rate
- [ ] Constraint-violation rate
- [ ] Empty-result rate
- [ ] Latency có filter vs không filter, cho từng nhánh

**Non-functional**
- [ ] Predicate của ba nhánh sinh từ **một** khai báo trong `queries.yaml`
- [ ] RPC mới không đụng vào RPC đang phục vụ production

## Architecture

### Bốn thước đo, ba trong đó là về tính đúng đắn chứ không phải hiệu năng

**1. Filtered Recall@10** — headline.
```
recall = |trả_về ∩ exact_filtered_topk| / min(k, n_eligible)
```
Mẫu số dùng `min(k, n_eligible)` để query chỉ có 3 ứng viên hợp lệ không bị phạt
oan vì trả 3 thay vì 10.

**2. Shortfall rate** — thước đo riêng cho chế độ hỏng của post-filter.
```
shortfall = P(len(trả_về) < min(k, n_eligible))
```
Người dùng hỏi "khách sạn 5 sao ở Huế dưới 2 triệu", hệ thống có 8 khách sạn
thỏa, nhưng chỉ trả 2 vì 8 cái kia không lọt vào 30 ứng viên gần nhất. Đây không
phải vấn đề xếp hạng — đây là **kết quả bị mất hẳn**. Đo riêng vì recall trung
bình có thể che giấu nó.

**3. Constraint-violation rate** — bug tính đúng đắn có thật trong code hiện tại.

Đo hai lỗi riêng biệt, cùng dạng "trả về thứ người dùng đã loại trừ":

*3a — Fallback im lặng.* `supabase_search.py:226-228` và `:287-288`: khi filter
chặt không ra gì, code trả về **kết quả chưa lọc**. Người dùng nói "dưới 1
triệu", hệ thống trả khách sạn 5 triệu, không cảnh báo gì.

*3b — Truncation nửa sao.* `hotels.star_rating` là `DECIMAL(2,1)`
(`database_schema.sql:36`) nhưng `supabase_search.py:218` so bằng
`int(star) < int(min_star_rating)`. Query "từ 4.5 sao" thành "từ 4 sao", và
khách sạn 4.0 lọt vào kết quả. Nhóm ≥ 5 query nửa sao ở Phase 2 tồn tại để đo
đúng cái này.

```
violation = P(tồn tại kết quả trả về vi phạm filter đã nêu)
```
Báo cáo tách 3a và 3b, đừng gộp — nguyên nhân khác nhau nên cách sửa cũng khác.

Cả hai đều là lỗi sản phẩm, không phải chuyện chọn vector DB, và benchmark này
định lượng được miễn phí. Trong ma trận quyết định chúng chỉ chiếm 5%, vì sửa
được ở cả hai hệ thống; nhưng phải nêu tách bạch trong report.

**4. Latency penalty của filter.**
```
penalty = server_ms(có filter) − server_ms(không filter)
```
Ở `S-current` penalty *âm hoặc bằng 0* về phía server (over-fetch 3× tốn hơn
chút) nhưng chi phí thật nằm ở chỗ khác: kết quả sai. Chỉ nhìn latency sẽ kết
luận ngược. Trong report, latency của `S-current` **phải** đặt cạnh recall của
nó, không đứng riêng.

### RPC `S-sql`

<!-- Updated: Validation Session 1 - rooms.price không tồn tại; dùng snapshot; star_rating là numeric(2,1) -->

```sql
create or replace function match_hotels_filtered(
  query_embedding       vector(1024),
  match_threshold       float,
  match_count           int,
  filter_destination_id uuid         default null,
  filter_min_star       numeric(2,1) default null,   -- KHÔNG phải smallint: có nửa sao
  filter_max_price      numeric      default null
) returns table (...) language sql stable as $$
  with eligible as (
    select h.id, h.embedding, s.lowest_price
    from hotels h
    -- Giá KHÔNG ở rooms. Nó ở room_prices, theo cửa sổ ngày + cờ sold_out.
    -- Snapshot của Phase 1 đóng băng nó thành một cột để cả 3 nhánh cùng lọc.
    left join bench_hotel_price_snapshot s on s.hotel_id = h.id
    where h.embedding is not null
      and (filter_destination_id is null or h.destination_id = filter_destination_id)
      and (filter_min_star  is null or h.star_rating   >= filter_min_star)
      and (filter_max_price is null or s.lowest_price  <= filter_max_price)
  )
  select ..., 1 - (e.embedding <=> query_embedding) as similarity
  from eligible e
  where 1 - (e.embedding <=> query_embedding) >= match_threshold
  order by e.embedding <=> query_embedding
  limit match_count;
$$;
```

Hai chi tiết không được đơn giản hóa:

- **`filter_min_star numeric(2,1)`**, không phải `smallint`. `hotels.star_rating`
  là `DECIMAL(2,1)` (`database_schema.sql:36`). Ép về số nguyên ở đây sẽ tái tạo
  đúng cái bug đang đo — `S-sql` phải làm **đúng**, chỉ `S-current` mới giữ
  `int()` truncation.
- **`left join` chứ không `join`** với snapshot: hotel không có giá trong cửa sổ
  ngày vẫn phải lọt qua khi query không nêu `max_price`. Dùng `join` sẽ âm thầm
  loại chúng khỏi *mọi* query, kể cả query không liên quan giá.

Hai điều phải kiểm bằng `EXPLAIN ANALYZE`, không giả định:

- Với **filter chặt**, planner nên lọc trước rồi seq-scan phần còn lại. Ở corpus
  1.1K dòng thì đây là cách nhanh nhất và cho kết quả exact.
- Với **filter lỏng**, planner có thể muốn dùng vector index. Kiểm xem nó có làm
  vậy không, và nếu có thì recall còn = 1.0 không.

Nếu planner chọn sai ở một tầng nào đó, ghi lại — đó là đặc tính thật của
pgvector ở scale này và thuộc về kết luận.

**Ranh giới an toàn:** RPC mới đặt tên khác, không sửa `match_hotels_with_rooms`
đang phục vụ production. Tương tự cho `match_attractions_filtered`.

### Ánh xạ predicate

Từ một khai báo YAML sinh ra ba dạng:

| Đích | Sinh ra |
|---|---|
| Ground truth | biểu thức boolean trên pandas DataFrame |
| `S-sql` | tham số RPC |
| `Q-native` | `Filter(must=[FieldCondition(key="metadata.star_rating", range=Range(gte=4)), ...])` |

Nhớ prefix `metadata.` cho Qdrant — `qdrant_schema.py:35-46` cảnh báo rõ rằng
thiếu prefix thì filter **khớp không gì cả một cách âm thầm**, và ghi chú luôn
rằng `poc_trip_planner.py` / `routes.py` hiện vẫn query key phẳng. Viết một
assertion: mỗi filter Qdrant phải trả `> 0` kết quả với query vector ngẫu nhiên,
nếu không thì fail ngay thay vì lặng lẽ báo cáo recall = 0 và đổ lỗi cho Qdrant.

## Related Code Files

- Create: `scripts/migrations/20260730_match_filtered_rpc.sql`
- Depends on: `bench_hotel_price_snapshot` (Phase 1) và định nghĩa RPC production đã dump (Phase 1 bước 0)
- Modify: `eval/vector_bench/adapters.py` — hoàn thiện nhánh filter
- Modify: `eval/vector_bench/metrics.py` — thêm shortfall, violation, empty rate
- Create: `eval/results/vector_bench/raw/phase04-*.jsonl`
- Read-only: `src/services/supabase_search.py:202-230`, `:265-290`

## Implementation Steps

1. **Ghi giả thuyết trước khi chạy** vào report: `S-current` sụt từ T2, sụp ở T4;
   `S-sql` và `Q-native` giữ ≈ 1.0.
2. Viết + deploy `match_hotels_filtered` và `match_attractions_filtered` lên
   Supabase (schema riêng hoặc tên riêng, không đụng RPC production).
3. Chạy `EXPLAIN (ANALYZE, BUFFERS)` cho mỗi tầng T1-T4, lưu plan vào report.
4. Bổ sung `adapters.py` cho cả ba nhánh có filter; thêm assertion sanity cho
   filter Qdrant (`> 0` kết quả).
5. Bổ sung `metrics.py`: shortfall, violation, empty rate.
6. Chạy 42 query T1-T4 × 3 nhánh, ghi JSONL.
7. Đo latency có filter theo đúng giao thức Phase 3 (warm-up, round-robin, 3 khung giờ).
8. Vẽ **biểu đồ chính**: trục X = độ chọn lọc (log), trục Y = filtered recall@10,
   ba đường. Đây là hình sẽ đưa vào slide VSF.
9. Trích 3 ví dụ cụ thể của lỗi shortfall và violation (query gì, đáng ra trả gì,
   thực tế trả gì). Số thuyết phục kỹ sư; ví dụ cụ thể thuyết phục người ra quyết định.
10. Đối chiếu kết quả với giả thuyết bước 1.

## Todo

- [ ] Ghi giả thuyết vào report trước khi chạy
- [ ] Viết + deploy 2 RPC filtered
- [ ] `EXPLAIN ANALYZE` từng tầng, lưu plan
- [ ] Adapter filter cho ba nhánh + assertion sanity Qdrant
- [ ] Metric shortfall / violation (3a + 3b tách riêng) / empty
- [ ] Chạy 42 query × 3 nhánh
- [ ] Latency có filter, 3 khung giờ
- [ ] Biểu đồ recall vs độ chọn lọc
- [ ] Trích 3 ví dụ shortfall/violation cụ thể
- [ ] Đối chiếu với giả thuyết

## Success Criteria

- [ ] Filtered Recall@10 cho 3 nhánh × 4 tầng, có khoảng tin cậy
- [ ] Shortfall rate cho 3 nhánh × 4 tầng
- [ ] Constraint-violation rate cho 3 nhánh, **tách riêng** 3a (fallback im lặng) và 3b (truncation nửa sao)
- [ ] Empty-result rate cho 3 nhánh
- [ ] Bảng latency có filter vs không, wall + server-side
- [ ] `EXPLAIN` plan lưu cho từng tầng
- [ ] Biểu đồ recall-vs-selectivity xuất ra `charts/`
- [ ] Định lượng rõ **hai khoảng cách**: `S-current`→`S-sql` (chi phí sửa) và `S-sql`→`Q-native` (lợi ích migrate)
- [ ] 3 ví dụ lỗi cụ thể, có query và kết quả thật

## Risk Assessment

| Rủi ro | Giảm thiểu |
|---|---|
| `S-sql` cũng đạt ≈ 1.0 → Qdrant không có lợi thế nào | Đó là kết quả hợp lệ và có khả năng cao nhất. Kết luận sẽ là "sửa Supabase, bỏ Qdrant". Không được thêm tiêu chí sau khi thấy số để cứu Qdrant |
| Filter Qdrant khớp rỗng do sai `metadata.` prefix → Qdrant "thua" oan | Assertion sanity bắt buộc ở bước 4; đã có cảnh báo sẵn tại `qdrant_schema.py:35-46` |
| T4 `n_eligible` quá nhỏ, recall nhiễu | Dùng `min(k, n_eligible)` làm mẫu số; báo khoảng tin cậy; ghi rõ cỡ mẫu |
| Deploy RPC mới ảnh hưởng production | Tên khác hoàn toàn; production RPC không bị sửa; rollback = `drop function` |
| Chỉ nhìn latency và kết luận `S-current` ổn | Report bắt buộc đặt latency cạnh recall trong cùng một bảng |
| Qdrant `hnsw_ef` / `exact` mặc định làm lệch so sánh | Ghi rõ tham số search dùng; chạy thêm một lượt `exact=True` làm mốc trần |
| Viết `S-sql` lặp lại bug `int()` của `S-current` → hai nhánh hòa giả tạo | `filter_min_star numeric(2,1)`; kiểm bằng chính nhóm query nửa sao |
| `join` thay vì `left join` với snapshot loại nhầm hotel không có giá | Nêu rõ trong draft; assertion: query không nêu `max_price` phải trả đúng số lượng như `S-current` |
| Snapshot giá đóng băng làm Qdrant trông tốt hơn thực tế | Chú thích ở mọi bảng số; chi phí denormalize tính riêng ở Phase 5.3 |
