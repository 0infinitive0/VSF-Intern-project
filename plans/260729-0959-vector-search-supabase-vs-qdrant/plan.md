---
title: "Vector search: Supabase pgvector vs Qdrant Cloud"
description: "Benchmark có tiền đăng ký quyết định, so sánh Supabase pgvector và Qdrant Cloud trên 2 tiêu chí lõi: vector search thuần và vector search kèm filter."
status: pending
priority: P1
effort: "4-5d"
tags: [benchmark, vector-search, supabase, qdrant, decision]
blockedBy: [260806-1754-codebase-cleanup-and-quality-gates]
created: 2026-07-29
updated: 2026-08-06
---

# Vector search: Supabase pgvector vs Qdrant Cloud

> **Sắp bị huỷ — đừng bắt đầu plan này.** Ngày 2026-08-06 quyết định gỡ hẳn
> Qdrant mà **không chạy benchmark**. Plan `260806-1754-codebase-cleanup-and-quality-gates`
> phase 2 sẽ xoá code/dependency/dữ liệu Qdrant và chuyển plan này sang
> `status: cancelled`. Toàn bộ phân tích dưới đây được giữ lại làm hồ sơ, nhưng
> **chưa có số liệu đo nào được sinh ra** — đừng đọc nó như một kết luận có bằng chứng.

## Overview

Chọn **một** vector store cho serving path của V-OTA. Hiện repo có cả hai nhưng
chỉ Supabase nằm trên đường phục vụ (`src/api/routes.py` →
`match_hotels_with_rooms` / `match_attractions`); Qdrant chỉ được ghi bởi
`scripts/sync_*.py` và Airflow DAG. Duy trì hai hệ thống là chi phí thật trên
t3.micro 908Mi RAM.

Plan này không phải "đo cho biết". Nó là quyết định có tiêu chí và ngưỡng được
**đăng ký trước khi chạy** (Phase 5.1 chốt ma trận trước khi Phase 3-4 sinh số),
để tránh nhìn số rồi hợp lý hóa kết luận đã có sẵn trong đầu.

### Bối cảnh kỹ thuật đã xác minh

| Sự kiện | Nguồn |
|---|---|
| Embedding khóa cứng bge-m3 1024-dim ở cả hai phía | `src/services/qdrant_schema.py:23`, `scripts/database_schema.sql:217` |
| Corpus rất nhỏ: ~1103 hotels, ~1013 attractions, ~2171 rooms | Qdrant local; memory `ec2-deployment` |
| Supabase **chỉ** pre-filter `destination_id` trong SQL | `src/services/supabase_search.py:203-211` |
| `star_rating` / `max_price` / `category` bị **post-filter trong Python** sau over-fetch 3× | `supabase_search.py:202`, `:214-225`, `:265` |
| Filter chặt không ra kết quả → code **âm thầm trả về kết quả không lọc** | `supabase_search.py:226-228`, `:287-288` |
| Qdrant có payload index native (prefix `metadata.`) cho `destination_id`, `category`, `star_rating`, `price_tier` | `src/services/qdrant_schema.py:42-81` |
| Qdrant Cloud hiện **thiếu dữ liệu**: 403 hotels, 0 attractions (local: 1103 / 1013) | memory `ec2-deployment` |
| RPC hotels **join sang rooms** — Qdrant không có tương đương | `supabase_search.py:211` |
| **Giá không phải thuộc tính của hotel.** Nằm ở `room_prices.price`, tới được qua 2 cấp join (`room_prices.room_id → rooms.id → rooms.hotel_id`), lại còn theo cửa sổ ngày + cờ `sold_out` | `scripts/database_schema.sql:70-105` |
| `hotels.star_rating` là `DECIMAL(2,1)` (có nửa sao), nhưng code lọc bằng `int(star)` → 3.5 thành 3 | `database_schema.sql:36`, `supabase_search.py:218` |
| Có **hai** nơi sinh payload Qdrant, không phải một | `src/airflow/dags/data_pipeline/hotel_pipeline.py:486`, `scripts/sync_accommodations_to_qdrant.py:54-59` |
| Thân hàm `match_hotels_with_rooms` **không có trong repo** — chỉ tồn tại trên Supabase | grep toàn repo: 0 kết quả định nghĩa |

Chính bất đối xứng ở dòng 3-5 là lý do tách riêng tiêu chí "vector search +
filter". Đó là nơi hai hệ thống thực sự khác nhau.

### Ràng buộc đã chốt với người dùng

- **Mục tiêu:** ra quyết định chọn một store (không phải báo cáo trung lập).
- **Môi trường đo:** laptop local.
- **Qdrant Cloud:** chỉ free tier.

### Hệ quả bắt buộc của ràng buộc đo đạc

Đo wall-clock từ laptop tới hai cloud khác nhau, một trong đó là free tier có
thể bị throttle/cold-start, **không đủ cơ sở quyết định bằng latency**. Plan xử
lý bằng ba việc, không lờ đi:

1. Tách **server-side time** khỏi wall-clock. Qdrant trả field `time` trong
   response; Postgres đo bằng `EXPLAIN (ANALYZE, BUFFERS)`. Số server-side độc
   lập với đường mạng nhà.
2. Hạ trọng số latency xuống **10%**, và cấm dùng wall-clock để suy ra SLA
   production.
3. Dồn trọng số vào **recall** và **hành vi filter** — hoàn toàn tất định, không
   phụ thuộc mạng, đo chính xác được vì corpus đủ nhỏ để brute-force ground truth.

## Goals

| # | Goal | Priority |
|---|------|----------|
| 1 | Đảm bảo hai store chứa **đúng cùng tập vector** trước khi so sánh bất cứ thứ gì | P1 |
| 2 | Tiêu chí A — vector search thuần: recall, độ trung thực điểm số, latency | P1 |
| 3 | Tiêu chí B — vector search + filter: filtered recall theo độ chọn lọc, shortfall, vi phạm ràng buộc | P1 |
| 4 | So sánh **công bằng**: gồm cả nhánh Supabase đẩy filter vào SQL | P1 |
| 5 | Khuyến nghị kiến trúc có ngưỡng đăng ký trước | P1 |
| 6 | Báo cáo + biểu đồ dùng được cho VSF | P2 |

### Non-goals

- Không tinh chỉnh embedding model. bge-m3 1024-dim là bất biến của bài này.
- Không benchmark scale ngoài corpus thật (~4.3K vector). Ngoại suy lên 1M vector
  từ 4K là ngụy biện; nếu cần thì đó là plan khác.
- Không triển khai kết quả. Plan dừng ở khuyến nghị.
- Không so sánh hybrid / BM25 / sparse. Chỉ dense vector search.

## Phases

| # | Phase | Status |
|---|-------|--------|
| 1 | [Phase 1: Parity và fixture](./phase-01-start.md) | Pending |
| 2 | [Phase 2: Query set và exact ground truth](./phase-02-query-set-and-exact-ground-truth.md) | Pending |
| 3 | [Phase 3: Tiêu chí A — vector search thuần](./phase-03-criterion-a-pure-vector-search.md) | Pending |
| 4 | [Phase 4: Tiêu chí B — vector search + filter](./phase-04-criterion-b-filtered-vector-search.md) | Pending |
| 5 | [Phase 5: Ops, chi phí, và quyết định](./phase-05-ops-cost-scoring-and-decision.md) | Pending |

**Thứ tự bắt buộc:** Phase 1 → 2 → **5.1 (đăng ký ma trận)** → 3 → 4 → 5.2-5.5.

## Ba nhánh so sánh

Đây là điểm thiết kế quan trọng nhất của plan. Nếu chỉ so `S-current` với
`Q-native` thì benchmark bị gian lận: nó đo *chất lượng cài đặt hiện tại*, không
đo *năng lực của pgvector*. Kết luận rút ra sẽ sai hướng — có thể khuyến nghị
migrate cả hệ thống trong khi vấn đề chỉ là một mệnh đề WHERE còn thiếu.

| Nhánh | Mô tả | Vai trò |
|---|---|---|
| `S-current` | Đường production hôm nay: RPC pre-filter mỗi `destination_id`, over-fetch 3×, post-filter Python | Baseline thực tế |
| `S-sql` | RPC mới, đẩy `star_rating` / `price` / `category` vào WHERE trước ANN | pgvector ở trạng thái tốt nhất |
| `Q-native` | Qdrant `Filter` + payload index, pre-filter | Qdrant ở trạng thái tốt nhất |

Khoảng cách `S-current` → `S-sql` là **chi phí sửa Supabase**. Khoảng cách
`S-sql` → `Q-native` mới là **lợi ích thật của migrate**. Quyết định phải so hai
khoảng cách này với nhau, không so cái đầu với cái cuối.

## Snapshot giá đóng băng — một nhượng bộ có chủ ý cho Qdrant

Giá không phải thuộc tính tĩnh của hotel: nó ở `room_prices.price`, theo cửa sổ
ngày và có cờ `sold_out`. Supabase lấy được giá live bằng join; Qdrant bắt buộc
phải denormalize giá vào payload, và payload đó **hỏng sau mỗi lần crawl**.

So trực tiếp như vậy sẽ trộn hai biến khác nhau — *năng lực search* và *độ tươi
dữ liệu* — làm không quy được chênh lệch recall về nguyên nhân nào. Vì vậy
benchmark **đóng băng một snapshot `lowest_price`** cho đúng một cửa sổ ngày, và
cả ba nhánh cùng lọc trên đúng con số đó (Phase 1).

Phải nói thẳng điều này ở mọi nơi báo cáo số: **đóng băng là ưu đãi cho Qdrant.**
Production không đóng băng được. Chi phí thật của denormalize — re-sync mỗi lần
giá đổi, và cửa sổ dữ liệu cũ giữa hai lần sync — được tính riêng ở Phase 5.3
dưới dạng ops, không phải dưới dạng recall. Nếu bỏ qua chú thích này, báo cáo sẽ
làm Qdrant trông tốt hơn thực tế.

## Bộ tiêu chí đánh giá

| Nhóm | Tiêu chí | Cách đo | Trọng số |
|---|---|---|---|
| **B. Filter** | Filtered Recall@10 qua 4 mức chọn lọc | vs exact filtered kNN | 20% |
| **B. Filter** | Shortfall rate (trả < k dù còn ứng viên hợp lệ) | đếm | 10% |
| **B. Filter** | Constraint-violation rate (gồm cả fallback im lặng và truncation nửa sao) | đếm | 5% |
| **A. Thuần** | Recall@10 vs exact kNN | brute force numpy | 12% |
| **A. Thuần** | nDCG@10 vs nhãn người | 20 query gán nhãn tay | 5% |
| **A. Thuần** | Score fidelity (lệch cosine tuyệt đối) | so số | 3% |
| **Ops** | RAM footprint trên t3.micro | `docker stats` | 10% |
| **Ops** | Số hệ thống phải vận hành | định tính | 8% |
| **Ops** | Khả năng join hotels↔rooms | định tính | 7% |
| **Latency** | Server-side p50/p95 | Qdrant `time`, PG `EXPLAIN ANALYZE` | 7% |
| **Latency** | Wall-clock p50/p95 (chỉ tham khảo) | client timer | 3% |
| **Chi phí** | Free tier limit, lock-in, backup/restore | định tính | 10% |

Trọng số chốt ở Phase 5.1 **trước khi** có bất kỳ số đo nào. Đổi trọng số sau
khi thấy kết quả phải ghi lý do vào changelog cuối `report.md`.

## Success Criteria

- [ ] Parity gate pass: hai store cùng tập ID, cùng vector (cosine ≥ 0.9999), không NULL embedding
- [ ] Query set ≥ 60 query tiếng Việt thật, phân tầng theo loại filter và độ chọn lọc
- [ ] Ground truth exact kNN (có và không filter) tính bằng brute force, tái lập được
- [ ] Ba nhánh chạy trên **cùng một query vector** đã embed sẵn và cache
- [ ] Có số cho toàn bộ 12 tiêu chí ở bảng trên
- [ ] Ma trận quyết định đăng ký trước Phase 3, kết quả tính đúng theo trọng số đó
- [ ] Khuyến nghị cuối nêu rõ: chọn gì, vì con số nào, điều kiện nào lật ngược kết luận
- [ ] Báo cáo `eval/results/vector_bench/report.md` + biểu đồ

## Rủi ro chính

| Rủi ro | Ảnh hưởng | Giảm thiểu |
|---|---|---|
| Qdrant free tier cold-start/throttle làm latency vô nghĩa | Cao | Warm-up 50 query bỏ đi; báo cáo server-side time; latency chỉ 10% trọng số |
| Hai store lệch dữ liệu → so sánh vô hiệu | Chí mạng | Phase 1 là hard gate, fail thì dừng |
| Re-embed query riêng từng store → đo Ollama chứ không đo store | Cao | Embed một lần, cache `.npy`, dùng chung |
| Corpus 4.3K quá nhỏ để phân biệt ANN | Trung bình | Chấp nhận và ghi rõ; ở scale này khác biệt recall *nếu có* càng đáng chú ý |
| Free tier Qdrant 1GB không đủ chỗ | Thấp | 4.3K × 1024 × 4B ≈ 18MB, thừa sức |
| Nhìn số rồi đổi tiêu chí | Cao | Đăng ký trước ở Phase 5.1 |

## Cấu trúc harness

```
eval/vector_bench/
├── dump_vectors.py      # kéo vector + payload từ Qdrant local (nguồn chuẩn) → .npy + .parquet
├── parity_check.py      # hard gate Phase 1
├── queries.yaml         # query set phân tầng
├── ground_truth.py      # exact kNN brute force, có/không filter
├── adapters.py          # SearchAdapter: SCurrent | SSql | QNative
├── metrics.py           # recall@k, nDCG, shortfall, violation
├── run_bench.py         # driver, ghi raw run ra JSONL
└── report.py            # tổng hợp + biểu đồ

eval/results/vector_bench/
├── raw/                 # JSONL từng lần chạy
├── report.md
└── charts/
```

## Validation Log

### Session 1 — 2026-07-29
**Trigger:** `/ak-plan validate` ngay sau khi viết plan, trước khi triển khai.
**Questions asked:** 4

#### Verification Results
- **Tier:** Full (5 phases, 4 roles)
- **Claims checked:** 47
- **Verified:** 42 | **Failed:** 4 | **Unverified:** 1

##### Failures
1. [Fact Checker] `scripts/database_schema.sql:190` cho `chat_messages` — sai, thực tế `:192`
2. [Fact Checker] **Phase 4 SQL draft dùng `rooms.price` — cột không tồn tại.** Giá ở `room_prices.price` (`database_schema.sql:92-95`), qua 2 cấp join, theo cửa sổ ngày, có cờ `sold_out`
3. [Fact Checker] Phase 1 chỉ liệt kê script sync là nơi sinh payload — thiếu `build_hotel_payload()` tại `src/airflow/dags/data_pipeline/hotel_pipeline.py:486`
4. [Fact Checker] Phase 4 khai `filter_min_star smallint` — `hotels.star_rating` là `DECIMAL(2,1)` (`database_schema.sql:36`)

##### Contract Verifier
- `ensure_collection`: **3** consumers, không phải 2 — `scripts/sync_to_qdrant.py:71`, `scripts/sync_accommodations_to_qdrant.py:104,112`, và `tests/test_qdrant_schema.py:30,42,54`. Thêm payload index nhiều khả năng làm hỏng `test_ensure_collection_creates_only_missing_indexes`

##### Flow Tracer
- VERIFIED: Qdrant **không** nằm trên serving path. `src/api/routes.py:39-40,89-90,110-111` chỉ import `supabase_search`; không có tham chiếu Qdrant nào
- VERIFIED: `get_vector_store` / `get_qdrant_client` chỉ có 2 consumer, đều là script sync

##### Unverified
1. Thân hàm `match_hotels_with_rooms` sống trên Supabase, không có trong repo → không xác minh được cách nó tính `lowest_price` (cửa sổ ngày nào? có loại `sold_out` không?). **Chặn định nghĩa ground truth cho filter `max_price`.** Xử lý bằng Q2 bên dưới

#### Questions & Answers

1. **[Architecture]** "Giá không phải thuộc tính tĩnh của hotel — nó nằm ở room_prices, theo ngày check-in/out và có cờ sold_out. Xử lý filter max_price trong benchmark thế nào?"
   - Options: Đóng băng snapshot giá | Bỏ max_price khỏi query set | Giữ nguyên động, chấp nhận Qdrant thua | Test cả hai
   - **Answer:** Đóng băng snapshot giá
   - **Rationale:** Tách *năng lực search* khỏi *độ tươi dữ liệu*. Không đóng băng thì chênh lệch recall không quy được về nguyên nhân nào. Đánh đổi: đóng băng là ưu đãi cho Qdrant, phải chú thích ở mọi bảng số, và chi phí denormalize tính riêng ở Phase 5.3 dưới dạng ops

2. **[Risks]** "Không đọc được thân hàm match_hotels_with_rooms. Giải quyết sao?"
   - Options: Dump về repo trước Phase 1 | Tự viết lại RPC | Người dùng paste vào
   - **Answer:** Dump về repo trước Phase 1
   - **Rationale:** Không biết RPC tính `lowest_price` thế nào thì ground truth cho `max_price` không định nghĩa được, và nhánh `S-current` không còn là baseline thật. Tiện thể đưa schema production vào version control

3. **[Scope]** "Hai nơi sinh payload Qdrant. Đâu là đường chính thức để Phase 1 sửa?"
   - Options: Kiểm tra rồi quyết định | Sửa cả hai cho đồng bộ | Chỉ sửa script sync
   - **Answer:** Kiểm tra rồi quyết định
   - **Rationale:** Tránh sửa nhánh không ai chạy. Xác định bằng cách so payload thật trên Qdrant Cloud với output của từng producer, rồi mới sửa

4. **[Scope]** "star_rating là DECIMAL(2,1) nhưng code dùng int(star). Đưa vào benchmark không?"
   - Options: Đo như một defect | Ngoài phạm vi | Sửa luôn trước khi bench
   - **Answer:** Đo như một defect
   - **Rationale:** Cùng loại với bug fallback im lặng — lỗi sản phẩm độc lập với việc chọn store, nhưng benchmark định lượng được miễn phí. Không sửa trước, vì `S-current` phải giữ nguyên hiện trạng

#### Confirmed Decisions
- Filter giá dùng snapshot đóng băng dùng chung cho cả 3 nhánh — chú thích rõ đây là ưu đãi cho Qdrant
- Dump định nghĩa RPC production về `scripts/migrations/` là việc **đầu tiên** của Phase 1
- Xác định payload producer thật trước khi sửa bất kỳ file nào
- Truncation nửa sao gộp vào metric constraint-violation của Phase 4

#### Action Items
- [x] Phase 1: thêm bước 0 dump RPC; thêm bước xác định payload producer; sửa bảng ánh xạ giá; thêm snapshot đóng băng; thêm `tests/test_qdrant_schema.py` vào Related Code Files
- [x] Phase 2: sửa `:190` → `:192`; filter giá trỏ snapshot; thêm query nửa sao
- [x] Phase 4: sửa SQL draft dùng `room_prices` / snapshot; `filter_min_star` → `numeric(2,1)`; thêm truncation vào violation metric
- [x] Phase 5: 5.3 tăng nặng khoảng cách join (giá theo ngày); 5.5 câu 4 thêm truncation nửa sao

#### Impact on Phases
- Phase 1: +3 bước, đổi bảng ánh xạ payload, +1 test file phải cập nhật; effort 0.5-1d → 1-1.5d
- Phase 2: sửa citation, +query nửa sao
- Phase 4: sửa SQL draft (bug thật), +1 metric con
- Phase 5: 5.3 nặng hơn về phía Supabase, 5.5 thêm hai action item
- Tổng effort plan: 3-4d → 4-5d

### Whole-Plan Consistency Sweep
- Files reread: `plan.md`, `phase-01-start.md`, `phase-02-*.md`, `phase-03-*.md`, `phase-04-*.md`, `phase-05-*.md`
- Decision deltas checked: 4 (snapshot giá, dump RPC, xác định producer, defect nửa sao)
- Reconciled stale references: 6 (`rooms.price` → `room_prices`/snapshot; `smallint` → `numeric(2,1)`; `:190` → `:192`; bảng ánh xạ payload Phase 1; Related Code Files Phase 1 & 4; effort Phase 1 và plan)
- Unresolved contradictions: **0**

Kiểm chéo bằng grep: mọi lần xuất hiện còn lại của `rooms.price`, `smallint`,
`:190` đều nằm trong Validation Log (ghi lại lỗi đã sửa) hoặc trong chú thích
sửa lỗi, không phải khẳng định còn hiệu lực.

<!-- slug: vector-search-supabase-vs-qdrant -->
