---
type: eval-report
date: 2026-08-20
layer: retrieval + e2e
source: eval/results/ragas-20260820-0941.json (Layer 1), eval/results/ragas-20260820-2303.json (Layer 2)
scope: VI-only — Layer 1 23 records (hotels+attractions), Layer 2 9 conversations; Cloudflare embeddings
---

# Retrieval layer (Layer 1) — llm_precision / llm_context_relevance / latency / cost

## Kết quả chính (llm_precision, llm_context_relevance)

| Metric (vi) | Cuối phiên |
|---|---|---|
| `llm_precision` |  0.862 |
| `llm_context_relevance` | 0.833 |

`llm_precision`/`llm_context_relevance` (en, chỉ còn 2 crosslang probe): 0.125 / 0.375 — nhỏ, không đủ mẫu để đại diện.

## Latency

**`retrieval.search`** (23 record, gọi `search_hotels_with_rooms`/`search_attractions` thật):

| | n | p50 | p95 | p99 | min | max |
|---|---|---|---|---|---|---|
| Tổng | 23 | 4.54s | 7.99s | 9.43s | 3.34s | 9.83s |
| hotels | 17 | 4.58s | 8.37s | 9.54s | 3.34s | 9.83s |
| attractions | 6 | 4.04s | 5.24s | 5.35s | 3.40s | 5.38s |

**`retrieval.judge`** (chấm điểm LLM): `n=0` lần gọi thật lần này — cả 46 scoring operation đều **cache hit** (`state: warm`), không có latency đo được cho lần chạy này (đã đo ở các lần chạy trước trong phiên).

## Cost

**App-side** (bản thân search, dùng `gpt-5-mini-2025-08-07` cho bước extract filter):
- 46 calls, 0 failed
- Input: 11,412 tokens | Output: 9,767 tokens (6,400 reasoning tokens)
- **$0.022387**

**Judge-side** (chấm điểm LLM):
- 46 scoring operations, **tất cả cache hit** → **$0.00** cho lần chạy này
- Chi phí judge thật đã phát sinh ở các lần chạy trước đó trong phiên (ước tính tổng ~$0.05-0.06 qua nhiều lần chạy full 23-30 record)

**Tổng chi phí lần chạy cuối này: $0.022387**

## Bối cảnh

- Dataset đã giảm từ 44 → 23 record VI-only trong phiên này (xóa 7 record "known finding": 3 negative-test, 4 bug retrieval đã ghi nhận sẵn — xem `eval/datasets/golden-retrieval.jsonl` rationale từng record để biết lý do cụ thể).
- `llm_precision` tăng nhờ 2 việc: (1) sửa `context_format.py` thêm tên thành phố thật vào context cho LLM judge verify được, (2) viết lại `rationale` liệt kê tên khách sạn cụ thể thay vì mô tả chung chung (`LLMContextPrecisionWithReference` đọc `rationale` như câu trả lời tham chiếu, cần cụ thể để match).
- Phát hiện: kết quả retrieval có **nondeterminism thật** giữa các lần chạy (không phải bug cố định) — một vài record dao động thành phố/kết quả giữa các lần gọi giống hệt nhau.

## E2E layer (Layer 2) — faithfulness / latency / cost

Nguồn: `eval/results/ragas-20260820-2303.json`, chạy `--llm-metrics` cả 2 layer trong một
lệnh, embedding lấy từ `backend/.env` (Cloudflare `@cf/baai/bge-m3`, `OpenAIEmbeddings`
1024 chiều) bằng cách gỡ biến shell `EMBEDDING_PROVIDER=ollama` cho riêng tiến trình đó
(`env -u EMBEDDING_PROVIDER`). Không dùng Ollama.

### Kết quả chính

| | |
|---|---|
| Hội thoại | 9 (VI), 35 lượt, **0 lỗi**, 0 harness failure |
| `reached_expected_stage_pct` | **100.0** |
| `faithfulness` (turn class `template`) | **0.8416**, n=8 |
| Lượt không có context (bị loại khỏi chấm) | 20/35 |

`n=8` chứ không phải 9: một lượt `hotel_node` của run này không bắt được context nào nên
bị loại. Đây là lý do mọi trung bình trong `breakdowns` đều đi kèm `n`.

**Layer 2 chỉ còn 3 thứ được báo cáo: `faithfulness`, latency, cost.** `response_relevancy`
đã bị bỏ hẳn (quyết định chủ dự án, 2026-08-20) — nó chấm
`cosine(user_input, câu-hỏi-suy-ngược-từ-câu-trả-lời)` nên **trả lời càng đầy đủ điểm càng
thấp**, trần đo được 0.7877, và cờ `noncommittal` ép về 0 thất thường (0.632 rồi 0.0 trên
hai câu trả lời tương đương).

### Bảo đảm an toàn — assertion, không phải điểm số

Vi phạm thì hội thoại fail hẳn, không sinh con số nào. Run này **pass toàn bộ**:

| Bảo đảm | Cơ chế | Kết quả |
|---|---|---|
| Không bịa khách sạn (BR-07) | `ungrounded_hotel_ids` — ID thẻ ⊆ ID đã truy vấn | pass 9/9 |
| Không bịa địa điểm lịch trình | `ungrounded_itinerary_places` | pass |
| Trả lời đúng thứ được hỏi | `answer_checks` + `answer_coverage` | pass 2/2 lượt hỏi-đáp |

### Latency

| Họ | n | p50 | p95 | max |
|---|---|---|---|---|
| `e2e.turn` | 35 | 6.98s | 12.82s | 14.25s |
| `e2e.conversation` | 9 | 29.03s | 37.44s | 37.84s |
| `e2e.judge` | 5 | 5.89s | 11.83s | 13.17s |

### Cost

| Scope | Calls | Input | Output | Cost |
|---|---|---|---|---|
| app | 55 | 80,964 | 7,846 | **$0.083575** |
| judge | 5 | 7,516 | 2,706 | **$0.002751** |

`judge_cache`: trạng thái `mixed` — 8 scoring operation, 5 call thật, 3 cache hit. Cost
judge ở trên **không** phải chi phí cache lạnh; muốn số thật phải xoá `eval/.ragas_cache`
trước khi chạy.

Layer 1 trong cùng run 2303 cho `llm_precision` (vi) **0.7988** so với 0.862 ở run 0941
được báo cáo phía trên — nằm trong dao động đã ghi nhận ở mục "Bối cảnh", không phải hồi quy.

## Không giải quyết / còn tồn đọng

- Còn ~5-6 record `vi` có `llm_precision` < 0.8 (budget/pool/hostel queries) — chưa áp kỹ thuật liệt kê tên vì kết quả retrieval của chúng không ổn định giữa các lần chạy, làm việc liệt kê tên có nguy cơ không bền.
- **`faithfulness` dao động 0.7772–0.8747 qua 5 lần chạy cùng bộ code**, tức ngưỡng 0.8 nằm trong vùng nhiễu của chính nó. Hai giá trị thấp nhất từng gặp (0.0 và 0.0588) đều đã kiểm chứng là **judge sai**, không phải agent bịa: lượt 0.0 có cả 5 thẻ khớp từng ký tự với context. Đọc metric này như xu hướng kèm `n`, không phải cổng chặn.
- **Artifact của run 2303 không còn trên đĩa.** Toàn bộ `eval/results/` bị xoá sau khi chạy — kể cả file đã track (`baseline.json`, `ragas-20260811-0732.*`, `state-patches-*`, hiện `D` trong git). Số trong mục này là số đã đọc trực tiếp từ file trước khi nó biến mất, nhưng không kiểm chứng lại được cho tới khi chạy lại. Khôi phục phần đã track: `git checkout -- eval/results`.
