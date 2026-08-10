---
title: "Phase 2: Query set và exact ground truth"
status: todo
priority: P1
effort: "1d"
dependencies: [1]
---

# Phase 2: Query set và exact ground truth

## Overview

Sinh bộ query và **ground truth chính xác tuyệt đối**. Điểm mấu chốt: corpus chỉ
~1-2K vector mỗi collection, nên top-k đúng tính được bằng brute force trong
numpy trong vài mili-giây. Không cần gán nhãn tay để đo recall — recall trở
thành phép so khách quan giữa "cái store trả về" và "cái đúng theo toán học".

Đây là thứ làm benchmark này đáng tin hơn phần lớn benchmark vector DB công khai:
ở scale nhỏ, ground truth là exact chứ không phải xấp xỉ.

Nhãn người vẫn cần, nhưng cho việc khác: recall đo "store có tìm ra đúng cái
brute force tìm ra không", còn nDCG đo "kết quả có thật sự hữu ích cho người
dùng không". Hai câu hỏi khác nhau, đều phải trả lời.

## Requirements

**Functional**
- [ ] ≥ 60 query tiếng Việt, phân tầng theo loại filter và độ chọn lọc
- [ ] Query vector embed **một lần**, cache ra `.npy`, ba nhánh dùng chung
- [ ] Exact top-k không filter cho mọi query
- [ ] Exact top-k **có filter** cho mọi query có filter, tính trên tập con thỏa filter
- [ ] Nhãn người 0/1/2 cho 20 query × top-10 hợp nhất

**Non-functional**
- [ ] Ground truth tái lập được: chạy 2 lần ra kết quả giống hệt
- [ ] Query set là file khai báo (`queries.yaml`), không hardcode trong code

## Architecture

### Nguồn query

Ưu tiên theo thứ tự:

1. **Log thật.** Kiểm bảng `chat_messages` (`scripts/database_schema.sql:192`)
   xem có truy vấn người dùng thật không. Query thật luôn tốt hơn query bịa.
2. **Bổ sung tay** cho các ô còn trống trong ma trận phân tầng.

Query phải là tiếng Việt tự nhiên, gồm cả dạng **không dấu** — `supabase_search.py:17-30`
có nguyên một hàm `_fold()` để xử lý "Ho Chi Minh" vs "Hồ Chí Minh", chứng tỏ
người dùng thật gõ không dấu. Bỏ dạng này ra khỏi query set là bỏ sót một lớp
lỗi có thật.

### Ma trận phân tầng

| Tầng | Số query | Filter | Mục đích |
|---|---|---|---|
| T0 | 20 | không | Tiêu chí A |
| T1 | 12 | 1 filter, chọn lọc ~50% | Tiêu chí B, dễ |
| T2 | 12 | 1-2 filter, ~20% | Tiêu chí B, vừa |
| T3 | 10 | 2-3 filter, ~5% | Tiêu chí B, khó |
| T4 | 8 | 3+ filter, ~1% | Tiêu chí B, điểm gãy |

**Độ chọn lọc là biến độc lập quan trọng nhất của Phase 4.** Post-filter sau
over-fetch 3× (`supabase_search.py:202`) hoạt động ổn khi filter lỏng và sụp khi
filter chặt — tầng T3/T4 tồn tại chính xác để định vị điểm sụp đó. Chọn lọc được
tính từ `payload.parquet` của Phase 1, không ước lượng bằng mắt.

### Ground truth

```python
# Không filter
sims = M @ q                     # M đã L2-normalize ở Phase 1
gt = np.argsort(-sims)[:k]

# Có filter: lọc trước rồi mới lấy top-k -> đúng định nghĩa của filtered kNN
mask = predicate(payload_df)     # cùng predicate mà 3 nhánh sẽ dùng
idx  = np.where(mask)[0]
gt   = idx[np.argsort(-sims[idx])[:k]]
```

Ghi kèm mỗi query: `n_eligible` = `mask.sum()`. Con số này là mẫu số cho
shortfall rate ở Phase 4 — không có nó thì không phân biệt được "store trả ít vì
kém" với "trả ít vì corpus chỉ có ngần ấy".

### Predicate phải dùng chung một định nghĩa

Predicate ground truth, mệnh đề WHERE của `S-sql`, và `Filter` của `Q-native`
phải sinh ra từ **một khai báo duy nhất** trong `queries.yaml`. Nếu viết tay ba
lần, chênh lệch recall có thể chỉ là do ba định nghĩa lệch nhau — và bug đó rất
khó phát hiện vì kết quả vẫn "trông hợp lý".

```yaml
- id: t3-07
  text: "khách sạn 4 sao ở Đà Nẵng có hồ bơi dưới 1 triệu"
  collection: hotels
  clean_query: "có hồ bơi"          # đã tách sẵn, không gọi LLM lúc bench
  filters:
    destination_id: {op: eq,  value: "<uuid Đà Nẵng>"}
    star_rating:    {op: gte, value: 4}
    lowest_price:   {op: lte, value: 1000000}   # từ bench_hotel_price_snapshot
```

<!-- Updated: Validation Session 1 - giá lấy từ snapshot đóng băng; thêm query nửa sao -->

Mọi predicate `lowest_price` giải ra trên **`bench_hotel_price_snapshot`** của
Phase 1, không phải giá live. Ba nhánh và ground truth cùng đọc một cột.

**Query nửa sao — bắt buộc có.** `hotels.star_rating` là `DECIMAL(2,1)`
(`database_schema.sql:36`) nhưng `supabase_search.py:218` lọc bằng `int(star)`,
biến 3.5 thành 3. Cần ≥ 5 query có ngưỡng nửa sao (`"khách sạn từ 3.5 sao"`,
`"resort 4.5 sao trở lên"`) để Phase 4 định lượng được lỗi này. Không có nhóm
query đó thì defect vô hình.

### Bỏ LLM ra khỏi vòng đo

`extract_search_filters()` gọi OpenAI để tách filter. Giữ nó trong vòng benchmark
sẽ thêm ~500-2000ms nhiễu và tính bất định (nhiệt độ 0 vẫn không đảm bảo cùng
output), làm hỏng cả latency lẫn recall. Vì vậy `queries.yaml` lưu **sẵn**
`clean_query` và `filters` đã tách — chạy `extract_search_filters()` một lần lúc
soạn query set, review tay, rồi đóng băng.

Ghi rõ trong report: benchmark đo tầng retrieval, không đo tầng trích filter.

## Related Code Files

- Create: `eval/vector_bench/queries.yaml`
- Create: `eval/vector_bench/ground_truth.py`
- Create: `eval/vector_bench/embed_queries.py`
- Create: `eval/fixtures/vector_bench/query_vectors.npy`
- Create: `eval/fixtures/vector_bench/ground_truth.json`
- Create: `eval/vector_bench/labels.csv` (nhãn người, 20 query)
- Read-only: `src/services/supabase_search.py` (dùng `extract_search_filters` lúc soạn, không lúc chạy)

## Implementation Steps

1. Truy vấn `chat_messages` gom query người dùng thật; khử trùng lặp, khử PII.
2. Soạn `queries.yaml` phủ đủ ma trận 5 tầng. Với mỗi query, chạy
   `extract_search_filters()` một lần rồi **review tay** `clean_query` và
   `filters`, sửa nếu LLM tách sai, rồi đóng băng.
3. Tính `n_eligible` cho từng query từ `payload.parquet`; xếp lại tầng nếu độ
   chọn lọc thực tế lệch dự kiến. Tầng do dữ liệu quyết định, không do phỏng đoán.
4. `embed_queries.py`: embed mọi `clean_query` bằng cùng `OllamaEmbeddings(bge-m3)`
   mà production dùng, L2-normalize, ghi `query_vectors.npy`.
5. `ground_truth.py`: sinh top-50 exact cho cả hai chế độ, ghi
   `ground_truth.json` kèm `n_eligible` và điểm cosine.
6. Kiểm tra tỉnh táo: với 5 query lấy mẫu, đọc tay top-10 exact và xác nhận nó
   thật sự liên quan. Nếu ground truth trông vô lý thì lỗi ở embedding hoặc ở
   normalize, không phải ở store — phải chặn tại đây.
7. Gán nhãn 20 query × top-10 hợp nhất từ ba nhánh (blind: giấu nhãn nhánh),
   thang 0 = không liên quan, 1 = tạm được, 2 = đúng ý. Ghi `labels.csv`.

## Todo

- [ ] Trích query thật từ `chat_messages`
- [ ] Soạn `queries.yaml` đủ 5 tầng, ≥ 60 query, có dạng không dấu, có ≥ 5 query nửa sao
- [ ] Review tay filter đã tách, đóng băng
- [ ] Tính `n_eligible`, xếp lại tầng theo số thật
- [ ] `embed_queries.py` → `query_vectors.npy`
- [ ] `ground_truth.py` → `ground_truth.json`
- [ ] Kiểm tra tỉnh táo 5 query
- [ ] Gán nhãn 20 query (blind) → `labels.csv`

## Success Criteria

- [ ] `queries.yaml` ≥ 60 query, mỗi tầng đủ số lượng ở bảng ma trận
- [ ] ≥ 10 query dùng tiếng Việt không dấu
- [ ] ≥ 5 query có ngưỡng nửa sao (3.5 / 4.5)
- [ ] Mọi predicate `lowest_price` giải trên `bench_hotel_price_snapshot`, không phải giá live
- [ ] Mọi query có `n_eligible` tính từ dữ liệu thật, và tầng khớp độ chọn lọc thực tế
- [ ] `query_vectors.npy` shape `[N, 1024]`, mọi norm = 1.0 ± 1e-6
- [ ] `ground_truth.json` có cả top-50 không filter và có filter
- [ ] Chạy `ground_truth.py` hai lần cho ra file giống hệt
- [ ] `labels.csv` đủ 200 dòng, blind
- [ ] Không có lời gọi OpenAI nào trong đường chạy benchmark

## Risk Assessment

| Rủi ro | Giảm thiểu |
|---|---|
| `chat_messages` rỗng hoặc toàn query test | Soạn tay toàn bộ, ghi rõ trong report là query tổng hợp — ảnh hưởng độ khái quát, phải nói ra |
| Query bịa thiên vị về phía hệ thống mình muốn thắng | Soạn query **trước** khi xem bất kỳ kết quả nào; đóng băng bằng git commit riêng |
| Nhãn người thiên vị | Blind, không cho biết kết quả đến từ nhánh nào |
| T4 có `n_eligible` < 10 → recall@10 vô nghĩa | Với query có `n_eligible < k`, dùng `recall@n_eligible`; ghi rõ công thức |
| Embedding lúc soạn khác lúc chạy (đổi phiên bản Ollama) | Ghi checksum model + phiên bản Ollama vào fixture metadata |
