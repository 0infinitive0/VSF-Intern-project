# Probe: Responses API — payload defaults, usage, và hình dạng chunk

Ngày: 2026-08-19 · Plan: `260819-0931-responses-api-migration-opt-in-with-reasoning-summary` Phase 2 bước 1
Model: `gpt-5-mini-2025-08-07` · Key thật, gọi live · Script: scratchpad, không commit

## Kết luận ngắn

**Hai giả định của plan đều sai. Cả hai sai theo hướng có lợi.**

1. `stream_options` **không** làm Responses API lỗi. Suy luận từ source
   (`_construct_responses_api_payload` không pop key này) là đúng về mặt code nhưng
   sai về mặt hậu quả — request chạy bình thường.
2. `usage_metadata` **vẫn tới** `usage_recorder` ở mọi cấu hình, kể cả
   `stream_usage=False`. Không có cổng chặn nào phải kích hoạt.

→ **Bỏ `stream_usage=False` khỏi thiết kế Phase 2.** Nó được thêm vào để chữa một
căn bệnh không tồn tại, và cái giá của nó (mất token usage) là thật.

## 1. Ma trận đo

Prompt: `"Trả lời trong đúng một câu ngắn: thủ đô Việt Nam là gì?"`

| # | Cấu hình | Kết quả | `usage_metadata` | `model` ghi nhận |
|---|---|---|---|---|
| A | Chat Completions (đối chứng) | OK, 13 chunk | in 23 / out 82 (reasoning 64) | `gpt-5-mini-2025-08-07` |
| B | Responses + `stream_usage` mặc định (`True`) | **OK, không lỗi** | in 23 / out 123 (reasoning 64) | `gpt-5-mini-2025-08-07` |
| C | Responses + `stream_usage=False` | OK, 14 chunk | in 23 / out 139 (reasoning 64) | `gpt-5-mini-2025-08-07` |
| D | Responses + `reasoning={"effort":"low","summary":"auto"}` | OK | in 23 / out 81 (reasoning 64) | `gpt-5-mini-2025-08-07` |

`output_tokens` dao động 81–139 giữa các lần chạy cùng một prompt — đọc theo bậc độ
lớn, không theo số lẻ.

### Chi tiết `usage_metadata`

Chat Completions:
```
{'input_tokens': 23, 'output_tokens': 82, 'total_tokens': 105,
 'input_token_details': {'audio': 0, 'cache_read': 0},
 'output_token_details': {'audio': 0, 'reasoning': 64}}
```

Responses API:
```
{'input_tokens': 23, 'output_tokens': 123, 'total_tokens': 146,
 'input_token_details': {'cache_creation': 0, 'cache_read': 0},
 'output_token_details': {'reasoning': 64}}
```

Khác biệt: Responses API thêm `input_token_details.cache_creation`, bỏ `audio`.
Cả hai field mà `eval/harness/cost.py` cần — `input_token_details.cache_read` và
`output_token_details.reasoning` — đều có mặt ở cả hai đường.

## 2. Hình dạng chunk thật

Đây là phần quan trọng nhất, và nó **xác nhận fix của Phase 1 trên dây thật** chứ
không chỉ trên fake.

```
[00] raw=[]                                                    -> ''
[01] raw=[{"type":"reasoning","summary":[],"encrypted_con...}] -> ''
[02] raw=[]                                                    -> ''
[03] raw=[{"type":"text","text":"Th","index":1}]               -> 'Th'
[04] raw=[{"type":"text","text":"ủ","index":1}]                -> 'ủ'
...
[13] raw=[{"type":"text","text":"","id":"msg_...","index":1}]  -> ''
[14] raw=[]                                                    -> ''

>>> _streamed_text ghép lại: 'Thủ đô của Việt Nam là Hà Nội.'
```

Ba điều đọc ra được:

- **Chunk đầu tiên rỗng, và chunk thứ hai là reasoning.** Bất kỳ phép kiểm tra nào
  chỉ nhìn chunk đầu sẽ kết luận sai rằng stream không có chữ.
- `_streamed_text` (Phase 1) khôi phục đúng và đủ, giữ nguyên khoảng trắng đầu token
  (`' đô'`, `' của'`).
- Block reasoning trả `''` — không rò vào delta, đúng như Phase 1 yêu cầu.

### Với `summary: "auto"`

```
[03] blocks=[{"type":"reasoning","reasoning":"**Responding to the user**\n\nThe"}]
[04] blocks=[{"type":"reasoning","reasoning":" user"}]
[05] blocks=[{"type":"reasoning","reasoning":" asked"}]
```

Khoá là `reasoning` trên block đã chuẩn hoá — khớp đúng với thiết kế
`_reasoning_from` của Phase 4, và khớp với spike §Q4. Nội dung tiếng Anh, đúng như
spike §Q2 đã đo.

## 3. Ảnh hưởng lên plan

| Mục Phase 2 | Trước probe | Sau probe |
|---|---|---|
| `stream_usage=False` khi bật Responses API | Bắt buộc, để tránh 400 | **Bỏ.** Không có 400 nào |
| Cổng chặn "usage không tới thì dừng" | Rủi ro Cao | **Không kích hoạt.** Usage tới đủ ở mọi ca |
| `model_name` cho `cost.py` | Chưa biết | **Đọc được**, đúng dated snapshot id |
| Rủi ro `stream_options` | Cao | **Loại bỏ** |

Phase 2 nhờ đó nhỏ hơn: chỉ còn cờ + guard họ model, không có nhánh xử lý usage.

## 4. Giới hạn của phép đo

- Một prompt, một model (`gpt-5-mini`). Chưa đo `gpt-5.1` (model của `get_reasoning_llm`).
- Mỗi ô chạy **một lần**. Latency ở đây không dùng để kết luận gì — Phase 3 mới đo latency.
- Chưa đo qua graph, chỉ đo model trực tiếp. `extract_patch` (structured output) và
  `qa_node` (ReAct + tool) vẫn chưa được chạm — đó là việc của Phase 3.
- Chưa đo với `bind_tools`. Spike 2026-08-18 §Q5 đã xác nhận tool-calling còn sống,
  nhưng đó là phép đo riêng, không phải phép đo này.
