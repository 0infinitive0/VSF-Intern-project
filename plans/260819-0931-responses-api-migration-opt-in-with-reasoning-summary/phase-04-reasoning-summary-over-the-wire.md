---
phase: 4
title: "Reasoning summary qua dây"
status: completed
priority: P2
effort: "1d"
dependencies: [2]
---

# Phase 4: Reasoning summary qua dây

## Overview

Yêu cầu `reasoning={"summary": "auto"}` khi cờ bật, rồi phát block reasoning ra client
bằng một event SSE mới tên `reasoning` — tách hẳn khỏi `delta`. Phase này chỉ làm phía
backend + hợp đồng; render là Phase 5.

## Requirements

**Functional**
- `LLM_REASONING_SUMMARY=auto` (default `off`) → thêm `reasoning={"summary": "auto"}`
  vào kwargs của nhánh `openai`, chỉ khi `use_responses_api` đã bật.
- Vòng drain phát `event: reasoning` với `{"text": "..."}` cho mỗi block
  `type == "reasoning"` từ `.content_blocks`.
- Chỉ node trong `STREAMING_NODES` phát reasoning — cùng ranh giới với `delta`.
  `supervisor` và `extract_patch` không được rò suy luận về client.
- Stream vẫn kết thúc bằng **đúng một** frame terminal (`final` hoặc `error`).
  Event `reasoning` không phải terminal.
- `reasoning` không bao giờ xuất hiện trong `final.reply`.

**Non-functional**
- **Không nhét reasoning vào `delta`.** Hợp đồng ghi rõ `delta` là "real LLM tokens"
  và "prefix của `final.reply`" (`chat_api_contract.md:193,207`). Reasoning không phải
  prefix của reply; trộn vào sẽ phá một bất biến mà client đang dựa vào.
- `emit_reasoning` theo đúng khuôn `emit_delta` (`streaming.py:170`): no-op khi không
  có emitter, **không bao giờ raise**, guard chuỗi rỗng.
- Effort giữ `low` như default hiện tại của `config.py:30`. Spike khuyến nghị `medium`
  cho độ phủ summary, nhưng đó là đánh đổi chi phí — Phase 6 quyết dựa trên số Phase 3,
  không đổi lén ở đây.

## Architecture

### Vì sao là event mới, không phải field trên `phase`

`phase` mang khoá đục + số liệu, FE dựng câu (`deepdive/phase-03:26-27`). Reasoning là
văn xuôi tiếng Anh do model sinh — nó **vi phạm** nguyên tắc đó. Nhét vào `phase` sẽ
làm nhoè ranh giới "BE không gửi câu chữ" mà cả hai plan đang dựa vào.

Event riêng làm ngoại lệ trở nên tường minh và có kiểu: client thấy `reasoning` thì biết
ngay đây là chữ của model, không phải chữ của sản phẩm, và xử lý khác đi (không dịch,
không i18n, đánh dấu thị giác riêng).

### Vòng drain sau khi sửa

Xây trực tiếp trên `_text_from` của Phase 1:

```python
if metadata.get("langgraph_node") in STREAMING_NODES:
    emit_delta(_text_from(message_chunk))
    emit_reasoning(_reasoning_from(message_chunk))
```

```python
def _reasoning_from(message_chunk) -> str:
    """Chữ suy luận model tự tóm tắt, rỗng khi không có.

    Rỗng là trường hợp thường gặp, không phải lỗi: spike 2026-08-18 đo được model
    chỉ phát summary khi nó thực sự suy luận, và bước gọi tool thì luôn rỗng.
    """
    blocks = getattr(message_chunk, "content_blocks", None) or []
    return "".join(b.get("reasoning", "") for b in blocks if b.get("type") == "reasoning")
```

### Hợp đồng

`docs/chat_api_contract.md` §Streaming thêm:

```
event: reasoning
data: {"text": "..."}
```

- Nguồn: OpenAI reasoning summary, chỉ từ node trong `STREAMING_NODES`.
- **Luôn tiếng Anh**, kể cả khi hội thoại là tiếng Việt. Không kiểm soát được qua prompt
  (spike §Q2). Client không được dịch hay giả định ngôn ngữ.
- **Có thể vắng hoàn toàn.** Một lượt hợp lệ có thể có 0 frame `reasoning`. Client không
  được đợi nó, và không được dùng nó làm điều kiện hiển thị.
- Không phải prefix của `final.reply`. Không bao giờ có mặt trong `final`.
- Không phải terminal frame.

## Related Code Files

- Modify: `backend/src/services/llm.py` (nhánh `openai`, thêm kwarg `reasoning`)
- Modify: `backend/src/config.py` (`llm_reasoning_summary`)
- Modify: `backend/src/api/streaming.py` (`emit_reasoning`, docstring event names)
- Modify: `backend/src/api/routes.py` (vòng drain)
- Modify: `docs/chat_api_contract.md` (§Streaming)
- Modify: `backend/.env.example`
- Modify: `backend/tests/`

## Implementation Steps

1. Thêm `llm_reasoning_summary: Literal["off", "auto"] = "off"` vào `config.py`.
2. Nhánh `openai`: khi `use_responses_api` bật **và** cờ này là `auto`, thêm
   `kwargs["reasoning"] = {"summary": "auto", "effort": target_reasoning_effort}`.
   Bỏ `reasoning_effort` rời khi đã set `reasoning` — `base.py:4300` chỉ chuyển đổi khi
   `"reasoning" not in payload`, hai key cùng lúc là mơ hồ.
3. `emit_reasoning` trong `streaming.py`, sao khuôn `emit_delta` từng dòng gồm cả
   try/except và guard rỗng. Cập nhật docstring module (danh sách event names ở đầu file
   liệt kê `phase | delta | final | error` — thêm `reasoning`).
4. `_reasoning_from` + nối vào vòng drain.
5. Cập nhật `docs/chat_api_contract.md` §Streaming với đủ 5 ràng buộc ở trên.
6. Tests:
   - chunk có block reasoning → `emit_reasoning` nhận đúng chữ
   - chunk chỉ có text → `emit_reasoning` không phát gì
   - node ngoài `STREAMING_NODES` → không phát reasoning
   - `final.reply` không chứa chữ reasoning
   - cờ `off` → kwargs không có `reasoning`
7. Chạy tay một lượt streaming với cờ bật, xem frame thật bằng `curl -N`, dán mẫu vào
   báo cáo Phase 3.

## Success Criteria

- [x] `event: reasoning` xuất hiện trên dây — 203 frame / 1017 ký tự trên prompt khó
- [x] 0 frame reasoning là trường hợp hợp lệ, có test — và quan sát được trên prompt dễ
- [x] `delta` và `final.reply` không bị ô nhiễm — 2 test riêng
- [x] Đúng một frame terminal mỗi stream, không đổi
- [x] Hợp đồng ghi rõ 4 thuộc tính client phải tôn trọng
- [x] Cờ `off` → 0 frame, xác nhận live

## Risk Assessment

| Rủi ro | Mức | Giảm thiểu |
|---|---|---|
| Frame reasoning làm phình băng thông SSE | Trung bình | Spike đo 2086 ký tự / lượt ở effort `medium`, ~406 chunk. Ở `low` là 405 ký tự. Giữ `low` cho tới khi Phase 6 quyết |
| Reasoning rò vào `final.reply` | Cao | Test riêng. `final` dựng từ graph state, không từ chunk — nhưng phải khoá lại bằng test, không bằng lập luận |
| Client cũ không biết event `reasoning` | Thấp | SSE: event lạ bị bỏ qua. `stream-client.ts:163` có `switch` — nhánh `default` không làm gì |
| Đặt cả `reasoning` và `reasoning_effort` gây 400 | Trung bình | Bước 2 loại bỏ key rời; test khẳng định chỉ một trong hai có mặt |
| Suy luận nội bộ lộ thông tin không nên hiện | Trung bình | Chỉ `STREAMING_NODES` phát. `supervisor` (routing JSON) và `extract_patch` bị loại theo cấu trúc, không theo lọc chuỗi |

## Kết quả đo live

`gpt-5-mini` qua graph thật, `LLM_USE_RESPONSES_API=true`:

| prompt | `LLM_REASONING_SUMMARY` | frame reasoning | ký tự |
|---|---|---|---|
| "Đà Nẵng tháng 7 thời tiết thế nào?" | `off` | 0 | 0 |
| "Đà Nẵng tháng 7 thời tiết thế nào?" | `auto` | **0** | 0 |
| lịch trình 5 ngày, 3 ràng buộc, yêu cầu giải thích cách cân nhắc | `auto` | **203** | 1017 |

Mẫu thật (stream từng token, tiếng Anh dù hội thoại tiếng Việt):

```
**Planning itinerary considerations**

I know the user's destination, dates, and budget, which is 8 million VN...
```

**Dòng giữa là dòng quan trọng nhất.** Cùng cấu hình, prompt dễ cho 0 frame. Đây chính
xác là giới hạn spike 2026-08-18 đã đo và là lý do kiến trúc phase này đặt reasoning làm
lớp phụ chồng lên dữ kiện graph, không bao giờ là nguồn duy nhất lấp khối UI.

## Một dự đoán sai, đã sửa

Trước khi làm, tôi dự đoán reasoning từ `qa_node` sẽ **không** tới được client vì nó là
subgraph. **Sai.** Thông điệp đầu ra của subgraph phát ở biên node có mang theo cả block
reasoning, nên chữ không mất — nó chỉ tới trong **một** frame thay vì tích luỹ dần.

`intake_qa` (node thường) stream nhiều frame; `qa_node` cho một cục. Cùng chữ, cùng thứ
tự, khác nhịp. Đã khoá bằng `TestReasoningFromQaNodeArrivesInOnePiece` và ghi vào hợp
đồng — UI của Phase 5 phải chịu được cả hai nhịp.
