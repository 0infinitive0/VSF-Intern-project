---
phase: 1
title: "extract_patch nearby hint"
status: pending
priority: P1
effort: "3-4h"
dependencies: []
---

# Phase 1: extract_patch nearby hint

## Overview

Cho `extract_patch` — LLM call đã chạy sẵn mỗi turn — trả thêm một field phụ
`asks_nearby_places: bool` bên cạnh `intent`/`changes`/`reason`. Field này
**không** phải intent, **không** chọn worker, và được parse **non-strict** y
hệt khuôn `reason` đã có, nên không đường nào của nó dẫn tới retry hay
`extraction_failed`.

## Requirements

- Functional: message hỏi xem/khám phá địa điểm quanh khách sạn (có hoặc
  không nêu bán kính) → `asks_nearby_places = True`; mọi message khác →
  `False`.
- Non-functional (quan trọng nhất): field mới **không bao giờ** làm
  `_extract_with_llm` retry hoặc rơi vào fallback. Thiếu key, `null`, string,
  số, list — tất cả fall open về `False`.
- Non-functional: không đổi wording của bất kỳ mục nào đang có trong
  `_EXTRACT_PATCH_SYSTEM_PROMPT` — chỉ thêm 1 dòng schema + 1 dòng giải thích.
- Non-functional: turn-scoped — reset mỗi turn bởi `load_context`, cùng nhóm
  với `extraction_failed`/`patch_reason`.

## Architecture

**1. Prompt** (`prompts.py`, `_EXTRACT_PATCH_SYSTEM_PROMPT` dòng 60-105):

Thêm vào schema block (sau `"reason"`, dòng 68):

```
  "asks_nearby_places": true | false
```

Thêm 1 dòng giải thích ngay sau đoạn `"reason"` (dòng 80), giữ đúng giọng văn
mô tả-hành-vi của các dòng xung quanh:

```
"asks_nearby_places" is true ONLY when the user wants to SEE or DISCOVER notable places, attractions, or things to do near their hotel -- a read-only listing with no change to the plan ("liệt kê địa điểm nổi bật trong bán kính 3km", "gần khách sạn có gì hay ho", "gợi ý vài chỗ tham quan gần đây", "what's around the hotel?"). It is false for every other message, including a question about hotels/rooms already shown, a question about what a specific day already contains, and any request to CHANGE something in the plan. It is independent of "intent" and never changes it: a nearby-places question is still general_question with an empty changes list.
```

Ba ví dụ trong ngoặc lấy nguyên từ `SUPERVISOR_SYSTEM_PROMPT`'s `list_nearby`
(`prompts.py:32`) — cùng khái niệm, giữ nguyên câu chữ để hai prompt không
trôi khỏi nhau theo thời gian.

**2. Parse non-strict** (`extract_patch.py`, `_parse_extraction_payload` dòng
493-523):

Đổi return type thành 4-tuple, thêm ngay dưới khối `reason` hiện có (dòng
518-522), tái dùng đúng comment/lý do của nó:

```python
    # Non-strict, same contract as `reason` above (module docstring): this is
    # a routing HINT layered on top of a turn that already completes without
    # it, so a missing key, a null, or a non-bool must fall open to False
    # rather than spend the retry. `is` on the literal, not truthiness --
    # "false" the string and 0 both mean the model did not answer this.
    asks_nearby_places = payload.get("asks_nearby_places") is True
    return intent, changes, reason, asks_nearby_places
```

`_extract_with_llm` (dòng 526-578) truyền tiếp field này; fallback cuối (dòng
578) trả `False`:

```python
    return "general_question", [], "", True, False   # +asks_nearby_places
```

**3. Node return** (`extract_patch.py`, dòng 581-649): thêm key vào cả hai
đường return — early-return message rỗng (dòng 584-590) trả `False`, và
return chính (dòng 643-649) trả giá trị parse được. Ghi **vô điều kiện**,
đúng lý do comment dòng 637-642 đã nêu cho các key khác.

**4. State** (`state.py`): khai báo cạnh `patch_reason`, kèm comment giải
thích nó KHÔNG phải intent:

```python
    # `extract_patch`'s read-only-listing hint: the user wants to SEE places
    # near the hotel, not change anything. Deliberately NOT an `intent`
    # value -- `intent` never selects a worker (see this file's `intent`
    # comment and extract_patch.py's docstring), and widening `_INTENTS`
    # would drag `_INCOMPLETE_EDIT_INTENTS` and the read-only rescue gate
    # in with it. `supervisor` reads this to send the turn to
    # `itinerary_node`'s read-only `list_nearby` action instead of
    # `qa_node`, whose tools cannot write the map's `suggested_places` at
    # all (structurally -- see `qa_node.py`'s QAState docstring).
    # Turn-scoped; reset by `load_context`.
    asks_nearby_places: bool
```

**5. Reset** (`load_context.py`): thêm `"asks_nearby_places": False` vào dict
return, cạnh `"patch_reason": ""`.

## Related Code Files

- Modify: `backend/src/agents/graph/prompts.py`
- Modify: `backend/src/agents/graph/nodes/extract_patch.py`
- Modify: `backend/src/agents/graph/state.py`
- Modify: `backend/src/agents/graph/nodes/load_context.py`

## Implementation Steps

1. **Bắt buộc trước khi sửa (CLAUDE.md):** chạy
   `impact({target: "extract_patch", direction: "upstream"})`. Báo cáo blast
   radius + risk level cho user; dừng xin xác nhận nếu HIGH/CRITICAL.
2. Đọc `backend/tests/test_extract_patch.py` (59 test) để nắm fixture/mock
   pattern. **Đã kiểm tra trước: đổi arity an toàn** — chỉ 3 chỗ gọi thẳng
   `_parse_extraction_payload` (dòng 389, 394, 401) và cả ba đều bọc trong
   `pytest.raises(PatchExtractionError)`, không unpack tuple; không test nào
   gọi `_extract_with_llm` trực tiếp (đều đi qua `extract_patch()` với
   `_FakeLLM`). Nên đổi 3-tuple → 4-tuple không làm đỏ test cũ nào.
3. Sửa `prompts.py` (schema + dòng mô tả).
4. Sửa `_parse_extraction_payload` + `_extract_with_llm` + `extract_patch`.
5. Sửa `state.py` + `load_context.py` cùng lúc (tránh quên reset).
6. Chạy `pytest backend/tests/test_extract_patch.py -q` — sửa các test cũ vỡ
   do đổi arity, KHÔNG nới lỏng assert nào của chúng.

## Success Criteria

- [ ] `impact()` đã chạy trên `extract_patch`, risk level báo cáo cho user.
- [ ] `payload` thiếu key `asks_nearby_places` → `False`, không exception,
      không retry.
- [ ] `payload["asks_nearby_places"]` = `null` / `"true"` / `1` / `[]` →
      `False`, không exception, không retry (test riêng từng giá trị).
- [ ] Cả hai fallback path của `extract_patch` trả `asks_nearby_places=False`.
- [ ] `load_context` reset field này mỗi turn.
- [ ] `pytest backend/tests/test_extract_patch.py` xanh, không assert cũ nào
      bị nới lỏng.

## Risk Assessment

Node có blast radius rộng nhất graph — chạy mọi turn. Giảm thiểu chính là
khuôn parse non-strict: field mới nằm hoàn toàn ngoài đường đi quyết định
tính đúng đắn của turn (`intent`/`changes` vẫn strict như cũ), nên trường hợp
xấu nhất của nó là "hint sai" chứ không phải "turn hỏng". Rủi ro còn lại thật
sự là **prompt drift** — thêm chữ vào prompt có thể làm lệch chất lượng
extract các field cũ; chặn bằng cách chạy đủ `test_extract_patch.py`, không
chỉ test mới.
