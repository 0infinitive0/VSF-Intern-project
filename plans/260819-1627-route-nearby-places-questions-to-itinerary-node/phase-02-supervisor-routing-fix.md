---
phase: 2
title: "Supervisor routing fix"
status: pending
priority: P1
effort: "2h"
dependencies: [1]
---

# Phase 2: Supervisor routing fix

## Overview

Đọc `asks_nearby_places` (Phase 1) ở nhánh read-only của `supervisor` và
delegate `itinerary_node` với `task_description` JSON dựng **deterministic**,
`action` hardcode `"list_nearby"`. Không LLM call, không keyword, không
`SupervisorDecision`.

## Requirements

- Functional: `intent == general_question` + `workers` rỗng +
  `asks_nearby_places is True` → `next_worker="itinerary_node"`,
  `task_description` = JSON `{"action": "list_nearby", "user_request": <text
  tin nhắn>}`.
- Functional: mọi trường hợp còn lại của nhánh này → `qa_node`,
  `routing_source="read_only_intent"` — **byte-for-byte** hành vi hôm nay.
- Non-functional: 0 LLM call phát sinh trong `supervisor` cho toàn bộ nhánh
  read-only (cả hai chiều).
- Non-functional: `action` phải là hằng số trong code, không phải giá trị do
  model trả về — không tồn tại đường code nào từ nhánh này tới
  `rebuild_days`/`edit_item`/`lock_days`.

## Architecture

`supervisor.py:218-219` hiện tại:

```python
    if not workers and state.get("intent") == _READ_ONLY_INTENT:
        return _delegate("qa_node", "read_only_intent", state)
```

Thành:

```python
    if not workers and state.get("intent") == _READ_ONLY_INTENT:
        # `list_nearby` is the ONE itinerary_node action that writes nothing
        # (pure search + `_ok()` passthrough -- no `_invoke_rebuild_day`, no
        # patch), so it is the one worker branch a read-only turn may take.
        # It is also the only path that can put places on the map at all:
        # `qa_node`'s tools reach `messages` and nothing else, so
        # `suggested_places` is structurally unreachable from there (see
        # qa_node.py's QAState docstring).
        #
        # The action is a CONSTANT here, never a model's pick. That is what
        # keeps the day-recap incident closed (see the note below): with no
        # choice offered, there is no route from a read-only turn to
        # `rebuild_days` for a model to take by mistake. `radius_km` is left
        # out on purpose -- `itinerary_node._resolve_radius_km` re-reads it
        # from the user's own words deterministically when it is absent.
        if state.get("asks_nearby_places"):
            task = {"action": "list_nearby", "user_request": _last_user_text(state)}
            return {
                **_delegate("itinerary_node", "read_only_intent_nearby", state),
                "task_description": json.dumps(task),
            }
        return _delegate("qa_node", "read_only_intent", state)
```

Giữ nguyên toàn bộ block comment dòng 201-217 phía trên (lý do lịch sử của
shortcut) — nó vẫn đúng và vẫn cần thiết cho người đọc sau.

`_last_user_text(state)`: lấy nội dung human message cuối. `extract_patch.py`
đã có `_last_human_message(state)` làm đúng việc này — **import và tái dùng**,
không viết bản thứ hai (DRY). Nếu import chéo node-sang-node bị coi là sai
tầng trong repo này, chuyển hàm đó lên module dùng chung và cập nhật cả hai
call site trong cùng commit; kiểm tra convention hiện có trước khi quyết định.

Ghi chú implementation:

- `json` đã import sẵn (`supervisor.py:22`) — không cần import mới.
- **Không** đi qua `_task_description_for`: hàm đó yêu cầu một
  `SupervisorDecision`, mà nhánh này không có (và không nên có). Override
  `task_description` sau `_delegate` như trên là đường ngắn nhất giữ nguyên
  `supervisor_iterations`/`routing_source` bookkeeping của `_delegate`.
- `routing_source="read_only_intent_nearby"` để phân biệt trên
  LangSmith/log; tên có thể đổi miễn khớp với test ở Phase 3.

## Related Code Files

- Modify: `backend/src/agents/graph/nodes/supervisor.py`

## Implementation Steps

1. **Bắt buộc trước khi sửa (CLAUDE.md):**
   `impact({target: "supervisor", direction: "upstream"})`. Báo cáo blast
   radius + risk level; dừng xin xác nhận nếu HIGH/CRITICAL.
2. Kiểm tra convention import giữa các node module để quyết định cách tái
   dùng `_last_human_message` (import trực tiếp vs nâng lên module chung).
3. Sửa nhánh dòng 218-219 theo Architecture ở trên.
4. Chạy `pytest backend/tests/test_supervisor_routing.py
   backend/tests/test_supervisor_llm_budget.py -q` — phải xanh trước khi
   thêm test mới ở Phase 3.

## Success Criteria

- [ ] `impact()` đã chạy trên `supervisor`, risk level báo cáo cho user.
- [ ] `asks_nearby_places=True` → `itinerary_node` + JSON task đúng shape
      `itinerary_node._parse_task` mong đợi.
- [ ] `asks_nearby_places` False/thiếu → `qa_node` y hệt hôm nay.
- [ ] Đọc diff xác nhận `"list_nearby"` là string literal trong code, không
      đến từ bất kỳ giá trị model nào.
- [ ] Test cũ trong `test_supervisor_routing.py` +
      `test_supervisor_llm_budget.py` xanh nguyên.

## Risk Assessment

Core routing, chạy mọi turn không có `pending_tasks`. Nhưng thay đổi net-new
nhỏ và hoàn toàn có gate: chỉ kích hoạt khi `asks_nearby_places is True`, và
mọi đường còn lại rơi về đúng dòng code cũ. Không có LLM call mới, không có
state mới ghi ra. Rủi ro thực tế cao nhất là `_last_user_text` lấy sai nội
dung (rỗng, hoặc lấy nhầm AI message) → `user_request` rỗng →
`search_attraction_candidates` query kém; chặn bằng test dựng state có
`messages` thật ở Phase 3, không chỉ set `task_description`.
