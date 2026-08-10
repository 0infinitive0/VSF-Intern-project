---
title: "Phase 3: Tiêu chí A — vector search thuần"
status: todo
priority: P1
effort: "0.5-1d"
dependencies: [1, 2]
---

# Phase 3: Tiêu chí A — vector search thuần

## Overview

Đo vector search **không có filter**: đưa cùng một query vector cho cả hai store,
so top-k trả về với exact kNN.

Dự đoán trung thực trước khi chạy: ở corpus ~1-2K vector, **cả hai gần như chắc
chắn đạt recall ≈ 1.0**. pgvector với ivfflat/hnsw và Qdrant với HNSW đều thừa
sức ở scale này; Postgres thậm chí có thể chọn seq scan và cho kết quả exact.
Nếu đúng vậy thì tiêu chí A **không phân biệt được hai hệ thống**, và đó chính
là một kết quả có giá trị: nó đẩy toàn bộ sức nặng quyết định sang tiêu chí B và
nhóm ops.

Ghi dự đoán này vào report **trước khi** chạy. Nếu kết quả khác dự đoán, đó là
tín hiệu có bug cấu hình (sai index, sai distance metric, vector chưa normalize)
chứ không phải phát hiện khoa học — phải điều tra trước khi ăn mừng.

## Requirements

**Functional**
- [ ] Ba nhánh (`S-current`, `S-sql`, `Q-native`) chạy toàn bộ 20 query T0
- [ ] Recall@{5,10,20} vs exact kNN
- [ ] Score fidelity: lệch tuyệt đối giữa điểm store báo và cosine exact
- [ ] nDCG@10 vs `labels.csv`
- [ ] Latency wall-clock **và** server-side, p50/p95, ở concurrency 1 và 8
- [ ] Kiểm tra tính tất định: mỗi query chạy 5 lần, so tập kết quả

**Non-functional**
- [ ] Không lời gọi Ollama hay OpenAI nào trong vòng đo
- [ ] Raw run ghi ra JSONL, mọi số tổng hợp đều truy ngược được về raw

## Architecture

### Giao diện adapter

```python
@dataclass
class SearchResult:
    ids: list[str]
    scores: list[float]
    wall_ms: float
    server_ms: float | None    # None nếu store không báo

class SearchAdapter(Protocol):
    name: str
    def search(self, qvec: np.ndarray, k: int,
               filters: dict | None = None) -> SearchResult: ...
```

Ba cài đặt:

| Adapter | Đường đi | Ghi chú |
|---|---|---|
| `SCurrent` | RPC `match_hotels_with_rooms` hiện có + post-filter Python sao chép từ `supabase_search.py:214-225` | Ở Phase 3 `filters=None` nên bằng RPC thuần |
| `SSql` | RPC mới `match_hotels_filtered` (viết ở Phase 4) | Ở Phase 3 gọi không filter |
| `QNative` | `QdrantClient.query_points()` | `with_payload=False` để không tính thời gian tải payload |

### Đo server-side time — cách vô hiệu hóa nhiễu mạng nhà

Đây là kỹ thuật giúp latency vẫn có chút giá trị dù đo từ laptop:

- **Qdrant**: response có field `time` (giây, server-side). Lấy trực tiếp.
- **Postgres**: chạy `EXPLAIN (ANALYZE, FORMAT JSON)` trên đúng câu truy vấn, lấy
  `Execution Time`. Vì Supabase RPC đi qua PostgREST nên cần một RPC phụ
  `explain_match_hotels(...)` trả về plan dạng text, hoặc kết nối trực tiếp qua
  connection string Postgres. **Ưu tiên kết nối trực tiếp** — đơn giản hơn và
  không thêm hàm vào production schema.

`wall_ms - server_ms` chính là chi phí mạng + serialize. Báo cáo cả ba số. Nếu
phần mạng chiếm > 80% wall-clock ở cả hai bên (rất có thể, đo từ nhà), thì nói
thẳng: **latency wall-clock không phân biệt được hai hệ thống trong thiết lập này.**

### Score fidelity — bẫy dễ bỏ sót

Supabase RPC thường trả `similarity` tính bằng `1 - (embedding <=> query)`.
Qdrant với `Distance.COSINE` trả cosine similarity trực tiếp. Hai số này *nên*
bằng nhau khi vector đã normalize — và nếu không bằng thì có bug ở đâu đó
(chưa normalize, sai metric, sai chiều).

So `|score_store − cosine_exact|` cho từng kết quả. Ngưỡng: max lệch < 1e-4.
Vượt ngưỡng thì dừng Phase 3 và quay lại điều tra, đừng báo cáo recall của một
hệ thống đang tính sai khoảng cách.

### Giao thức đo latency

1. **Warm-up**: 50 query bỏ kết quả, cho mỗi nhánh. Free tier Qdrant có thể ngủ;
   không warm-up thì query đầu tiên đội p95 lên vô nghĩa.
2. **Đo**: mỗi query 10 lần lặp, xen kẽ nhánh (round-robin) chứ không chạy hết
   nhánh này rồi tới nhánh kia — để trôi dạt mạng theo thời gian ảnh hưởng đều.
3. **Concurrency**: lặp lại ở 1 và 8 luồng.
4. **Ghi kèm ngữ cảnh mạng**: ping/traceroute tới cả hai endpoint trước và sau
   mỗi lần chạy, ghi vào JSONL. Không có số này thì latency không diễn giải được.
5. **Lặp toàn bộ ở 3 thời điểm khác nhau trong ngày**, ghi cả ba. Chênh lệch
   giữa ba lần chính là thước đo độ nhiễu — nếu nó lớn hơn chênh lệch giữa hai
   hệ thống, kết luận latency là vô nghĩa và phải nói ra.

## Related Code Files

- Create: `eval/vector_bench/adapters.py`
- Create: `eval/vector_bench/metrics.py`
- Create: `eval/vector_bench/run_bench.py`
- Create: `eval/results/vector_bench/raw/phase03-*.jsonl`
- Read-only: `src/services/supabase_search.py`, `src/services/vector_store.py`

## Implementation Steps

1. **Ghi dự đoán trước khi chạy** vào `report.md`: kỳ vọng recall ≈ 1.0 cả hai,
   kỳ vọng latency bị mạng chi phối. Có mốc này thì mới phân biệt được xác nhận
   giả thuyết với hợp lý hóa sau khi thấy số.
2. Viết `adapters.py` với ba cài đặt. `SCurrent` phải sao chép **chính xác** logic
   `supabase_search.py`, kể cả nhánh fallback dòng 226-228 — đo cái đang chạy
   thật, không phải cái nên chạy.
3. Viết `metrics.py`: `recall_at_k`, `ndcg_at_k`, `score_fidelity`, `percentiles`.
4. Viết `run_bench.py` chạy T0 theo giao thức đo ở trên, ghi JSONL raw.
5. Chạy score fidelity trước, độc lập. **Gate**: max lệch < 1e-4 mới chạy tiếp.
6. Chạy recall + nDCG.
7. Chạy latency 3 lần trong ngày, kèm ping/traceroute.
8. Kiểm tra tính tất định: 5 lần cùng query, so tập ID.
9. Tổng hợp, đối chiếu với dự đoán bước 1, ghi rõ chỗ nào khớp chỗ nào lệch.

## Todo

- [ ] Ghi dự đoán vào report trước khi chạy
- [ ] `adapters.py` ba nhánh
- [ ] `metrics.py`
- [ ] `run_bench.py`
- [ ] Gate score fidelity < 1e-4
- [ ] Recall@{5,10,20} + nDCG@10
- [ ] Latency 3 khung giờ × concurrency {1,8} + ping/traceroute
- [ ] Kiểm tra tất định 5×
- [ ] Đối chiếu kết quả với dự đoán

## Success Criteria

- [ ] Score fidelity: max `|score_store − cosine_exact| < 1e-4` ở cả ba nhánh
- [ ] Có Recall@{5,10,20} cho ba nhánh × 20 query T0
- [ ] Có nDCG@10 dựa trên `labels.csv`
- [ ] Có bảng latency: wall p50/p95, server p50/p95, phần mạng, ở concurrency {1,8}, 3 khung giờ
- [ ] Tất định: 5 lần cùng query cho cùng tập ID (hoặc ghi rõ nhánh nào không tất định)
- [ ] Raw JSONL đủ để tính lại mọi số tổng hợp
- [ ] Report ghi rõ tiêu chí A **có** hay **không** phân biệt được hai hệ thống

## Risk Assessment

| Rủi ro | Giảm thiểu |
|---|---|
| Cả hai recall = 1.0, phase "không ra kết quả gì" | Đó **là** kết quả hợp lệ và đã dự đoán trước; nó chuyển sức nặng sang Phase 4 + ops. Không được ép tìm khác biệt bằng cách đổi tiêu chí |
| Free tier throttle giữa chừng làm p95 dựng đứng | Warm-up + 3 khung giờ + báo cáo server-side time; ghi rõ nếu bắt gặp throttle |
| Postgres chọn seq scan → exact nhưng chậm | Đây là phát hiện đáng giá, không phải lỗi. Ghi lại plan từ `EXPLAIN` vào report |
| `SCurrent` bị viết "sạch hơn" bản production | Review chéo giữa `adapters.py` và `supabase_search.py:169-230` từng dòng |
| Round-robin làm connection pool nóng lạnh thất thường | Giữ kết nối bền cho cả hai client, tạo trước warm-up |
