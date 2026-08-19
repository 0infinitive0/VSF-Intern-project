---
phase: 3
title: "Regression + coverage tests"
status: pending
priority: P1
effort: "2-3h"
dependencies: [1, 2]
---

# Phase 3: Regression + coverage tests

## Overview

Nhánh `_READ_ONLY_INTENT` hiện có **0 test** (`grep read_only_intent
backend/tests/test_supervisor_routing.py` → rỗng) — chưa từng được khoá lại
trước khi sửa. Phase này phủ cả hai file: khuôn parse non-strict của field
mới (`test_extract_patch.py`) và nhánh routing (`test_supervisor_routing.py`).

## Requirements

### `test_extract_patch.py` — khuôn non-strict (nhóm quan trọng nhất)

- Thiếu key `asks_nearby_places` → `False`, không raise, không retry.
- `null` → `False`. `"true"` (string) → `False`. `1` → `False`. `[]` → `False`.
  Mỗi giá trị một assert riêng, không gộp — mục đích là chứng minh
  "fall open", không phải "chạy được".
- `true` → `True` (happy path).
- Cả hai fallback path (`extraction_failed`, message rỗng) → `False`.
- Assert kèm: các case hỏng ở trên **không** làm tăng `llm.call_count` (tức
  không tiêu retry) — dùng `_FakeLLM`'s call counting đã có trong file
  (xem `test_..._asked the user for dates.start` dòng ~380 làm mẫu).

### `test_supervisor_routing.py` — nhánh routing

- `asks_nearby_places=True`, `intent=general_question`, `pending_tasks=[]` →
  `next_worker="itinerary_node"`; `json.loads(result["task_description"])`
  có `action == "list_nearby"` và `user_request` bằng đúng text tin nhắn.
- Cùng state nhưng `asks_nearby_places=False` → `qa_node`,
  `routing_source="read_only_intent"`.
- `asks_nearby_places` không có trong state (session cũ, chưa có field) →
  `qa_node`, không `KeyError`.
- **Regression guard:** `_unreachable_llm_factory` cho CẢ HAI chiều
  (True và False) — chứng minh nhánh read-only không gọi model nào. Đây là
  test thay thế cho "validation chặt" ở thiết kế cũ: bug "ngày 3 tôi làm gì?"
  không thể tái diễn vì không có model nào được hỏi.
- Dùng câu lỗi thật nguyên văn `"liệt kê các địa điểm nối bật trong vòng bán
  kính 3km"` (giữ luôn lỗi chính tả "nối bật" như user gõ) làm `messages`
  content cho test happy path, để test neo vào bug report gốc.
- State dựng bằng `messages` thật (không chỉ set `task_description`) —
  chặn đúng rủi ro `_last_user_text` đọc sai đã nêu ở Phase 2.

## Architecture

Không có kiến trúc mới. Tái dùng helper sẵn có: `_state(**overrides)`,
`_FakeLLM`, `_unreachable_llm_factory` (`test_supervisor_routing.py:19-46`);
`_FakeLLM`/`_payload` (`test_extract_patch.py`). Thêm section mới phân cách
bằng comment `# --- ... ---` theo đúng convention hai file đang dùng.

## Related Code Files

- Modify: `backend/tests/test_extract_patch.py`
- Modify: `backend/tests/test_supervisor_routing.py`

## Implementation Steps

1. Viết nhóm test non-strict trong `test_extract_patch.py` trước — đây là
   nhóm bảo vệ blast radius lớn nhất.
2. Viết nhóm test routing trong `test_supervisor_routing.py`.
3. Chạy `pytest backend/tests/test_extract_patch.py
   backend/tests/test_supervisor_routing.py
   backend/tests/test_supervisor_llm_budget.py backend/tests/test_routing.py -q`.
4. **Tự-verify test có thật sự bắt lỗi:** tạm sửa `_parse_extraction_payload`
   thành `bool(payload.get("asks_nearby_places"))` (truthiness thay vì
   `is True`) → nhóm test `"true"` string và `1` phải ĐỎ. Khôi phục lại code.
   Tương tự, tạm bỏ gate `if state.get("asks_nearby_places")` ở supervisor →
   test `qa_node` phải ĐỎ.

## Success Criteria

- [ ] Mọi test đặt tên mô tả hành vi (`test_<kịch_bản>_<kỳ_vọng>`), không
      đặt tên theo phase/finding number.
- [ ] Bước tự-verify (step 4) xác nhận test đỏ đúng chỗ khi code bị làm hỏng
      có chủ đích, rồi xanh lại sau khi khôi phục.
- [ ] `pytest backend/tests/test_extract_patch.py
      backend/tests/test_supervisor_routing.py
      backend/tests/test_supervisor_llm_budget.py backend/tests/test_routing.py`
      xanh toàn bộ.

## Risk Assessment

Thấp — chỉ thêm test. Rủi ro duy nhất là test giả (mock sai field, assert
lỏng) → khử bằng bước tự-verify bắt buộc ở step 4.
