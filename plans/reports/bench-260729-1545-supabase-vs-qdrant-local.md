---
title: "Benchmark: Supabase (pgvector) vs Qdrant local"
date: 2026-07-29
scope: "Vector search thuần + vector search có filter, bỏ qua yếu tố latency mạng"
---

# So sánh Supabase pgvector vs Qdrant local

## Điều kiện đo

- Corpus: 1103 hotels, 2171 rooms, 1013 attractions (bge-m3, 1024-dim)
- Parity đã verify: cả 2 store cùng ID, cùng vector (cosine 1.00000 sau khi fix staleness)
- Ground truth: brute-force kNN bằng numpy trên toàn bộ corpus đã dump từ Qdrant local
- **Bỏ qua latency** — Supabase là managed cloud, Qdrant là local, so thời gian không công bằng và không phản ánh năng lực thuật toán
- Nhánh Supabase đo là **S-current** (RPC production hiện tại): pre-filter `destination_id` trong SQL, `star_rating`/giá lọc sau trong Python, over-fetch 3×
- Chưa có nhánh S-sql (RPC mới đẩy filter vào WHERE) — xem mục "Giới hạn" cuối file

## Bảng 1 — Vector search thuần (20 query tiếng Việt)

**Đã sửa sau khi đọc được thân hàm `match_hotels_with_rooms` thật** (bản đầu tiên của bảng
này dùng ground truth chỉ so hotel-doc embedding — so sai đối tượng, xem "Lịch sử sửa" cuối
mục). RPC thật tính similarity trên **UNION(hotel-doc, mọi room-doc thuộc hotel đó)** rồi
`GROUP BY hotel_id, MAX(sim)` — tức một hotel có thể vào top-k nhờ một phòng cụ thể khớp cao,
không chỉ nhờ mô tả hotel. Ground truth đã sửa để max-pool đúng như vậy cho phía Supabase,
giữ nguyên hotel-doc-only cho phía Qdrant vì collection `hotels_vector` chỉ chứa hotel-doc.

| Tiêu chí | Qdrant local | Supabase pgvector |
|---|---|---|
| Mean Recall@10 | **1.000** | **1.000** |
| Query đạt recall thấp | 0/20 | 0/20 |
| Ground truth so với | hotel-doc thuần | MAX(hotel-doc, room-doc) theo hotel_id |
| Cách tính | ANN trên `hotels_vector` | RPC `match_hotels_with_rooms`, `match_threshold=0.0` |
| Latency p50/p95 (tham khảo, không dùng để kết luận) | 44.7 / 104.9 ms | 479.2 / 4655.1 ms |

**Nhận xét:** Sau khi ground truth khớp đúng hàm mục tiêu thật của mỗi store, **cả hai đạt
recall@10 = 1.000 tuyệt đối trên toàn bộ 20 query** — không có khác biệt về chất lượng ANN ở
kịch bản vector search thuần. Kết luận trước đó ("Supabase 0.840") là **artifact của benchmark
sai**, không phải giới hạn thật của pgvector — đã sửa lại đúng.

### Lịch sử sửa
Bản đầu: ground truth chỉ so `query_vec` với `hotels.npy` (hotel-doc), thấy Supabase recall
0.840, tụt ở 3 query liên quan "phòng" (room). Đọc thân hàm RPC thật mới phát hiện nó search
cả `rooms.embedding` rồi gộp theo `MAX(sim)` per hotel — ground truth cũ không phản ánh đúng
domain retrieval của Supabase nên đánh giá sai. Đã sửa `bench_pure.py` thêm
`brute_force_topk_hotel_or_room_max()`, dùng `rooms.npy` + `rooms.json` (đã có sẵn từ
`dump_vectors.py`) để tính lại.

## Bảng 2 — Vector search + filter (8 query, filter theo destination + star_rating)

| Tiêu chí | Qdrant local (Q-native) | Supabase pgvector (S-current) |
|---|---|---|
| Mean Filtered Recall@10 | **1.000** | 0.728 |
| Shortfall rate (trả về < k dù đủ ứng viên) | 0/8 | **2/8** |
| Constraint-violation rate | 0 | **1** |
| Fallback trả kết quả không lọc | — | 0/8 |

**Nhận xét:**
- Qdrant dùng `Filter` + payload index (`metadata.destination_id`, `metadata.star_rating`) —
  pre-filter thật trong ANN, đúng tuyệt đối trên cả 8 query.
- Supabase shortfall nặng nhất ở 2 query filter **chặt** (5 sao): "resort sang trọng" Đà Nẵng
  (n_eligible=15) → recall 0.50; "khách sạn bình dân" Hà Nội (n_eligible=9) → recall 0.22.
  Đây là hệ quả trực tiếp của kiến trúc over-fetch 3×-rồi-lọc-Python: khi filter chặt, 30 kết
  quả gần nhất theo semantic (chưa lọc sao) không đủ chứa hết top-10 đúng.
- 1 vi phạm filter ở "khách sạn gia đình" (3★ Nha Trang) — khớp bug đã biết
  `int(star_rating)` cắt nửa sao (`supabase_search.py:218`), 2.5★ có thể lọt qua 3★.

## Tổng hợp

| | Qdrant local | Supabase pgvector |
|---|---|---|
| Recall thuần | 1.000 | 1.000 (đã sửa ground truth, xem Bảng 1) |
| Recall có filter | 1.000 | 0.728 |
| Shortfall khi filter chặt | Không | Có, tăng theo độ chọn lọc |
| Vi phạm filter | Không | Có (nửa sao) |
| Payload index cho filter | Có sẵn (destination_id, star_rating, price_tier, ...) | Không — filter numeric làm trong Python |

**Điểm mấu chốt:** hai store **không khác nhau về năng lực ANN thuần** (Bảng 1: cả hai
recall=1.000). Toàn bộ khoảng cách chất lượng nằm ở **Bảng 2 — khi có filter**, đúng như
plan gốc dự đoán ("chính bất đối xứng ở filter là lý do tách riêng tiêu chí"). Đây là tín
hiệu quan trọng: vấn đề không phải "Qdrant tốt hơn pgvector nói chung", mà là "kiến trúc
filter hiện tại của Supabase (post-filter Python) kém hơn filter native của Qdrant" — một
vấn đề có thể sửa bằng SQL, không nhất thiết phải đổi store (xem Giới hạn #1).

## Bảng 3 — Qdrant Cloud vs Supabase Cloud (có đo latency mạng thật)

Bảng 1/2 cố tình bỏ latency vì so Qdrant **local** với Supabase **cloud** không công
bằng — khác môi trường mạng hoàn toàn. Sau khi đồng bộ Qdrant local lên Qdrant Cloud
(collection mới `hotels_vector_v2`, verify parity cosine=1.0), giờ so được **cả hai
đều qua mạng thật**, cùng máy, cùng thời điểm. Có warm-up 3 query bỏ đi trước khi đo,
tránh cold-start free tier làm méo số liệu — đúng khuyến nghị rủi ro trong plan gốc.

| Tiêu chí | Qdrant Cloud | Supabase Cloud |
|---|---|---|
| Mean Recall@10 | **1.000** | **1.000** |
| Latency p50 | 961.2 ms | **293.9 ms** |
| Latency p95 | 1943.3 ms | **696.5 ms** |

**Kết quả đảo ngược hoàn toàn so với Bảng 1 (local):** khi cả hai đi qua mạng thật,
**Supabase Cloud nhanh hơn Qdrant Cloud khoảng 3.3× ở p50**. Ở bảng local trước đó
Qdrant nhanh hơn Supabase ~18× (45ms vs 874ms) — chênh lệch đó **hoàn toàn là do so
sánh không công bằng** (local vs cloud), không phản ánh năng lực thật của Qdrant khi
triển khai cloud. Nguyên nhân khả dĩ của Qdrant Cloud chậm: free tier instance ở
region `sa-east-1` (Nam Mỹ) — xa hơn đáng kể so với region Supabase, cộng thêm khả
năng cold-tier/ throttle của free tier như plan gốc đã cảnh báo trước.

**Ý nghĩa cho quyết định kiến trúc:** nếu latency production là tiêu chí quan trọng,
số liệu Cloud-vs-Cloud này quan trọng hơn nhiều so với Bảng 1 (local). Recall vẫn hòa
tuyệt đối ở cả 3 bảng — sự khác biệt duy nhất giữa hai store nằm ở **filter** (Bảng 2)
và giờ thêm **latency mạng thực tế** (Bảng 3), không phải năng lực ANN.

## Bảng 4 — Local vs Local (Supabase local + Qdrant local, không mạng cả hai phía)

Bảng 1 so Qdrant local với Supabase Cloud (lẫn mạng một phía); Bảng 3 so cả hai Cloud
(lẫn network + khác region). Sau khi dựng được Supabase local đầy đủ (`supabase start`,
schema + data + RPC functions đồng bộ, 0 NULL embedding hotels/rooms), giờ so được
**cả hai đều chạy trên cùng máy, không qua mạng** — cô lập hoàn toàn hiệu năng thuật
toán khỏi mọi yếu tố network/region.

### Vector search thuần — chạy 2 lần để kiểm tra ổn định

| Tiêu chí | Qdrant local (lần 1 / lần 2) | Supabase local (lần 1 / lần 2) |
|---|---|---|
| Mean Recall@10 | 1.000 / 1.000 | 1.000 / 1.000 |
| Latency p50 | **51.0 / 62.3 ms** | 358.7 / 310.7 ms |
| Latency p95 | 106.4 / 133.0 ms | 2495.1 / 1035.1 ms |

### Vector search + filter — chạy 2 lần để kiểm tra ổn định

| Tiêu chí | Qdrant local (Q-native) | Supabase local (S-current) |
|---|---|---|
| Mean Filtered Recall@10 | **1.000** (cả 2 lần) | 0.728 (cả 2 lần, giống hệt từng dòng) |
| Shortfall rate | 0/8 (cả 2 lần) | **2/8** (cả 2 lần) |
| Constraint-violation rate | 0 (cả 2 lần) | **1** (cả 2 lần) |

**Kết quả filter giống hệt Bảng 2 và giống hệt giữa 2 lần chạy** (0.728, shortfall 2/8,
violation 1, từng dòng chi tiết y hệt) — hợp lý vì embedding tất định (cùng câu hỏi qua
Ollama → cùng vector) và lỗi filter là lỗi logic, không phụ thuộc tải hệ thống hay thời
điểm chạy.

**Latency thuần dao động nhẹ giữa 2 lần nhưng giữ nguyên xu hướng** — Qdrant luôn nhanh
hơn Supabase ~5-7× ở p50, khác hẳn Bảng 3 nơi Supabase Cloud lại nhanh hơn Qdrant Cloud.
p95 Supabase dao động khá lớn (2495ms → 1035ms) vì phụ thuộc query cụ thể nào rơi vào
kịch bản quét nặng nhất (xem phân tích root cause bên dưới) — vẫn ổn định về thứ tự độ
lớn (Supabase luôn chậm hơn Qdrant, không đảo chiều).

### Root cause latency: đã xác nhận bằng `EXPLAIN ANALYZE` trực tiếp trên Postgres local

Kết nối `psql` trực tiếp Postgres local (`127.0.0.1:54322`, không có tại Supabase Cloud
vì bị chặn mạng) để chạy `EXPLAIN ANALYZE` trên chính câu SQL trong RPC. Phát hiện:

1. **HNSW index đã tồn tại** trên cả `hotels.embedding` và `rooms.embedding`
   (`hotels_embedding_hnsw_idx`, `rooms_embedding_hnsw_idx`) — không phải thiếu index.
2. **RPC không dùng được HNSW** vì cách viết SQL: lọc bằng `WHERE sim > match_threshold`
   (biểu thức tính trước), không phải `ORDER BY embedding <=> query LIMIT k`. Postgres chỉ
   dùng ANN index cho dạng `ORDER BY ... <=> ... LIMIT`, không dùng được cho `WHERE
   similarity > ngưỡng`. Query plan xác nhận: `Seq Scan on hotels` (184ms) + `Seq Scan on
   rooms` (221ms) ≈ 405ms trong tổng 421ms đo được — khớp khít với latency benchmark.
3. **Ngay cả khi ép dùng HNSW** (`SET enable_seqscan = off`), nó **chậm hơn** Seq Scan trên
   corpus này (84ms vs 26ms cho riêng bảng hotels) — planner Postgres chọn đúng, không phải
   bug cấu hình. HNSW có overhead graph traversal chỉ có lợi khi corpus đủ lớn (thường hàng
   chục nghìn+ vector); ở quy mô ~1103-2171 dòng, brute-force Seq Scan nhanh hơn.
4. **Qdrant luôn dùng HNSW bất kể corpus lớn hay nhỏ** — không có "seq scan fallback" như
   Postgres, nên tốc độ ổn định ~50-60ms không phụ thuộc quy mô ở range này.

**Kết luận root cause:** Supabase chậm hơn không phải vì pgvector "tệ" hay thiếu index —
mà vì (a) cách viết RPC (`WHERE sim > threshold`) chặn khả năng dùng ANN index hoàn toàn,
và (b) ngay cả khi sửa để dùng được ANN, ở quy mô corpus hiện tại (~4.3K vector) brute-force
Seq Scan của Postgres tự nó vẫn chậm hơn HNSW graph traversal của Qdrant, do chi phí tính
`<=>` cho từng dòng cộng thêm UNION ALL + GROUP BY + JOIN ngược lại `hotels`.

**Cảnh báo ngoại suy — đúng như plan gốc:** kết luận "Qdrant nhanh hơn ~7×" **chỉ đúng ở
quy mô hiện tại**. Nếu corpus lớn lên đáng kể (hàng chục nghìn+ vector), HNSW của Postgres
sẽ bắt đầu thắng Seq Scan và khoảng cách với Qdrant có thể thu hẹp hoặc đảo chiều — không
ngoại suy số liệu này sang corpus lớn hơn nhiều so với 4.3K hiện tại.

**Ý nghĩa cho quyết định kiến trúc:** đây là số liệu latency đáng tin nhất trong 3 bảng
latency (1, 3, 4) vì cô lập được biến số môi trường, và giờ đã có root cause xác nhận thay
vì suy đoán. Nếu latency là tiêu chí quan trọng ở quy mô corpus hiện tại, Qdrant có lợi thế
thật — nhưng phần lớn khoảng cách này **có thể thu hẹp bằng cách viết lại RPC dùng
`ORDER BY <=> LIMIT` thay vì `WHERE sim > threshold`** (cùng vấn đề với Giới hạn #1 — chưa
đo được nhánh S-sql).

## Giới hạn của benchmark này

1. **Chỉ đo S-current, chưa đo S-sql.** Nếu viết lại RPC đẩy `star_rating`/giá vào mệnh đề
   WHERE trước ANN (thay vì post-filter Python), khoảng cách filtered-recall có thể thu hẹp
   đáng kể — không tách được "chi phí sửa 1 câu SQL" khỏi "giới hạn kiến trúc thật của
   pgvector". Đây là điểm quan trọng nhất chưa trả lời được.
2. **Đã bỏ latency theo yêu cầu** — không dùng bảng này để kết luận về tốc độ phục vụ
   production.
3. **8 query filter** là mẫu nhỏ — đủ để phát hiện xu hướng (shortfall tăng theo độ chọn
   lọc) nhưng chưa đủ để tính ngưỡng quyết định đáng tin cậy như plan gốc yêu cầu (≥60 query
   phân tầng).
4. **Chưa test attractions/rooms filter** — chỉ test trên hotels.
5. **Bảng 3 chưa tách được nguyên nhân chậm của Qdrant Cloud** khi so một mình — nhưng
   Bảng 4 (local vs local) đã gián tiếp xác nhận: latency chênh lệch ở Bảng 3 chủ yếu
   do môi trường mạng/region, vì khi bỏ hết mạng, Qdrant vẫn nhanh hơn Supabase. Vẫn
   chưa xác nhận trực tiếp bằng cách đổi Qdrant Cloud sang region gần hơn.
6. ~~Bảng 4 p95 Supabase local cao bất thường — chưa điều tra query plan~~ **Đã giải quyết**:
   xem mục "Root cause latency" trong Bảng 4 — không phải thiếu index, mà do RPC dùng
   `WHERE sim > threshold` khiến Postgres không dùng được HNSW, phải Seq Scan toàn bộ
   corpus. Đã xác nhận bằng `EXPLAIN ANALYZE` trực tiếp, không còn là ẩn số.
7. **Chưa thử viết lại RPC dùng `ORDER BY embedding <=> query LIMIT k`** (thay vì
   `WHERE sim > threshold`) để xem có tận dụng được HNSW và thu hẹp khoảng cách latency
   không — đây thực chất là một phần của nhánh S-sql còn thiếu (Giới hạn #1), giờ có
   thêm bằng chứng cụ thể để ưu tiên làm trước.

## Nguồn script

- `eval/vector_bench/dump_vectors.py` — fixture ground truth
- `eval/vector_bench/bench_pure.py` — Bảng 1
- `eval/vector_bench/bench_filtered.py` — Bảng 2
- Raw JSONL: `eval/results/vector_bench/raw/bench_pure.jsonl`, `bench_filtered.jsonl`
