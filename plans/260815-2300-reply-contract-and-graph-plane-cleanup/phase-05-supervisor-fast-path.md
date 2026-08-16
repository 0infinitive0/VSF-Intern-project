---
phase: 5
title: "Supervisor fast path"
status: completed
priority: P3
effort: "0.5d"
dependencies: [4]
---

# Phase 5: Supervisor fast path

## Overview

`supervisor` gọi LLM để chọn thứ tự worker trong khi `WORKER_ORDER` đã quy định thứ tự
đó, với lý do sản phẩm rõ ràng. Mở rộng fast path để bỏ LLM call thừa, giảm độ trễ và
loại một nguồn không xác định khỏi đường xử lý phổ biến nhất.

Chạy sau Phase 4 vì Phase 4 thêm nhánh `needs_trip_first` vào cùng hàm.

## Requirements

**Functional**

- Turn không có worker nào thất bại trước đó không gọi LLM để quyết định delegation.
- LLM path vẫn giữ nguyên cho recovery sau khi một worker báo lỗi.
- Thứ tự delegation không đổi so với hiện tại trong mọi trường hợp fast path xử lý.

**Non-functional**

- Đo được: số LLM call/turn ở supervisor, trước và sau.
- Không giảm chất lượng routing — nếu có case LLM chọn tốt hơn `WORKER_ORDER`, phải
  chứng minh bằng test, không phải bằng phỏng đoán.

## Architecture

### Hiện trạng

```python
# supervisor.py:111-113
# Fast path: exactly one possible worker and no prior failure -> no LLM needed.
if len(workers) == 1 and not state.get("task_results"):
    return _delegate(workers[0], "impact_map", state)
```

Docstring node nói *"~90% of turns hit this"*. Vậy 10% còn lại — turn multi-workflow —
gọi LLM.

### Vì sao LLM call đó thừa

`workers` đến từ `_eligible_workers`:

```python
def _eligible_workers(state):
    pending = state.get("pending_tasks") or []
    return [w for w in WORKER_ORDER if w in pending and not is_impossible(w, state)]
```

Nó lọc `WORKER_ORDER` — **đã sắp thứ tự**. `routing.py:20-22` ghi rõ lý do:

> *"Fixed order when several workflows are impacted: the hotel anchors the itinerary,
> so rebuilding the itinerary first would schedule around a hotel about to change."*

Đây là ràng buộc nhân quả của miền bài toán, không phải sở thích. Không có thứ tự nào
khác đúng.

Và LLM bị ràng buộc phải chọn trong chính list đó:

```python
# supervisor.py:131-132
if workers and decision.next_worker not in workers:
    raise ValueError(...)   # → fallback về workers[0]
```

Nên đầu ra khả dĩ của LLM path khi `workers` có 2 phần tử `["hotel_node",
"itinerary_node"]`:

| LLM chọn | Kết quả thực tế |
|---|---|
| `hotel_node` | = `workers[0]` — giống fast path |
| `itinerary_node` | Sai thứ tự nhân quả: xếp lịch quanh khách sạn sắp bị đổi |
| Ngoài list | Raise → fallback `workers[0]` — giống fast path |

Hai trong ba nhánh trùng `workers[0]`. Nhánh còn lại là **lỗi**. Đây chính là bug đã ghi
trong `routing.py:41-46`:

> *"the LLM sometimes picked `itinerary_node` first, which bailed immediately with nothing
> to show, forcing the user to resend the identical message."*

Bug đó được vá bằng cách thêm điều kiện `trip_data` vào `_IMPOSSIBLE`. Nhưng nguyên nhân
gốc — hỏi LLM một câu bảng đã trả lời — vẫn còn.

### Thay đổi

```python
    # Fast path: WORKER_ORDER đã quy định thứ tự delegation với lý do nhân quả
    # (hotel anchors itinerary — routing.py). Hỏi LLM chọn giữa các worker mà
    # bảng đã xếp hạng chỉ tạo cơ hội chọn sai thứ tự; kết quả đúng duy nhất
    # là workers[0]. LLM path giữ lại cho recovery sau khi một worker báo lỗi,
    # nơi thứ tự tĩnh không còn đủ thông tin.
    if workers and not state.get("task_results"):
        return _delegate(workers[0], "impact_map", state)
```

Chỉ đổi `len(workers) == 1` → `workers`. Điều kiện `not task_results` giữ nguyên: đó là
ranh giới giữa "delegation lần đầu" (bảng đủ) và "recovery sau thất bại" (cần suy luận).

### Cái gì KHÔNG đổi

- LLM path (`supervisor.py:115-133`) giữ nguyên hoàn toàn — vẫn chạy khi `task_results`
  không rỗng.
- Nhánh `rebuild_day_queue` (dòng 74-104) và `max_iterations` (106) không đụng.
- Nhánh `needs_trip_first` từ Phase 4 nằm trước, không ảnh hưởng.
- Fallback `except Exception` giữ nguyên.

### `booking_node` — giữ nguyên, đã quyết

<!-- Updated: Validation Session 1 - booking sẽ mở, không gỡ booking_node -->

`booking_node` có `_IMPOSSIBLE = True` vô điều kiện (`routing.py:50`), nên nó **không bao
giờ** lọt vào `workers`. Nó vẫn nằm trong `WORKER_ORDER` (`routing.py:23`) và trong
`Literal` của `SupervisorDecision` (`supervisor.py:45`).

Tôi từng đề xuất gỡ nó khỏi cả hai để prompt supervisor bớt một nhãn nhiễu ở recovery
path. **Người dùng xác nhận sản phẩm sẽ mở booking** (Validation Session 1), nên
đề xuất đó bị rút: giữ nguyên `WORKER_ORDER` và `Literal`, phase này không đụng gì tới
`booking_node`.

Hệ quả còn lại, chấp nhận được: ở recovery path, model vẫn có thể chọn `booking_node`,
`is_impossible` bắt được (`supervisor.py:121-122`), raise `ValueError`, rơi fallback
`workers[0]`. Một vòng lãng phí hiếm gặp, và sẽ tự biến mất khi booking được mở và
`_IMPOSSIBLE["booking_node"]` không còn là `True` vô điều kiện.

## Related Code Files

- Modify: `backend/src/agents/graph/nodes/supervisor.py` — điều kiện fast path + comment lý do
- Modify: `backend/tests/test_supervisor_routing.py` — test multi-worker fast path
- Create: `backend/tests/test_supervisor_llm_budget.py` — đếm LLM call/turn (hoặc gộp vào file trên)
- Read-only: `backend/src/agents/graph/routing.py` — `WORKER_ORDER` và lý do thứ tự

## Implementation Steps

1. **Đo trước.** Viết test đếm số lần `get_fast_llm` được gọi trong một turn
   multi-workflow (message set cả destination + dates + people + budget cùng lúc, đúng
   case `routing.py:41-46` mô tả). Ghi lại con số. Dùng `monkeypatch` trên
   `src.services.llm.get_fast_llm` như `test_respond.py` đã làm cho suggestions.

2. **Viết test đỏ**: `workers = ["hotel_node", "itinerary_node"]`, `task_results = []`
   → phải trả `hotel_node`, `routing_source="impact_map"`, và **không** gọi LLM.

3. **Đổi điều kiện** `len(workers) == 1` → `workers`, kèm comment giải thích lý do
   (không chỉ "tối ưu" — ghi rõ nhánh nào của LLM là sai).

4. **Chạy `test_supervisor_routing.py`.** Test nào đỏ vì giờ không còn gọi LLM ở turn
   multi-worker là test đang khẳng định hành vi cũ — đọc kỹ từng cái trước khi sửa. Nếu
   có test khẳng định LLM **phải** được hỏi ở case nào đó, đó là tín hiệu ta bỏ sót một
   yêu cầu; dừng lại và xem lại.

5. **Chạy `test_legacy_guards.py`** — file này test anti-loop qua
   `MAX_SUPERVISOR_ITERATIONS`, không được ảnh hưởng.

6. **Đo lại.** So sánh với bước 1, ghi con số vào phần kết quả của phase.

7. **`booking_node`: không đụng.** Đã quyết ở Validation Session 1 — sản phẩm sẽ mở
   booking, nên giữ nguyên trong `WORKER_ORDER` và `Literal`. Không có việc phải làm ở
   bước này ngoài việc **xác nhận** thay đổi ở bước 3 không vô tình đổi hành vi của
   `booking_node` (nó vốn không bao giờ lọt vào `workers`, nên không thể).

8. **Test thủ công**: message compound "đi Đà Nẵng 3 ngày 2 người ngân sách 3 triệu" →
   xác nhận route đúng `hotel_node` và độ trễ giảm.

## Success Criteria

- [x] Turn multi-workflow lần đầu không gọi LLM ở supervisor
- [x] Thứ tự delegation giống hệt trước thay đổi (luôn `WORKER_ORDER[0]` trong tập eligible)
- [x] LLM path vẫn chạy khi `task_results` không rỗng (recovery)
- [x] Số LLM call/turn đo được trước và sau, ghi vào phase
- [x] `test_supervisor_routing.py` và `test_legacy_guards.py` xanh
- [x] Không test nào bị sửa để "làm cho xanh" mà không hiểu lý do
- [x] `booking_node` vẫn nguyên trong `WORKER_ORDER` và `Literal` — phase này không đụng

## Risk Assessment

| Rủi ro | Mức | Giảm thiểu |
|---|---|---|
| Có case thật mà LLM chọn tốt hơn `WORKER_ORDER` | Trung bình | Bước 4 dùng test suite làm bằng chứng. Nếu tìm được case như vậy, **dừng phase** — nghĩa là `WORKER_ORDER` sai và cần sửa bảng, không phải giữ LLM call. |
| Mất khả năng quan sát quyết định routing | Thấp | `routing_source="impact_map"` đã phân biệt rõ với `"supervisor"`. Observability không giảm. |
| Recovery path (LLM) ít được test hơn vì ít chạy hơn | Trung bình | Giữ nguyên mọi test hiện có cho nhánh `task_results` không rỗng. Không giảm coverage nhánh đó. |
| Gỡ `booking_node` khi sản phẩm định mở booking | — | **Đã loại bỏ.** Validation Session 1 xác nhận booking sẽ mở; đề xuất gỡ bị rút, phase không đụng `booking_node`. |

**Rollback:** đổi lại điều kiện thành `len(workers) == 1`. Một dòng, không state,
không migration.

## Execution Log — 2026-08-15

### Measurement (steps 1 and 6)

`tests/test_supervisor_llm_budget.py` counts every `get_fast_llm` call and every
`invoke` on a multi-workflow first delegation (`pending_tasks=["hotel_node",
"itinerary_node"]`, `task_results=[]`, trip already in place so both are eligible).

| Turn | Before | After |
|---|---|---|
| Multi-worker, first delegation | `["get_fast_llm", "invoke"]` — **1 LLM call** | `[]` — **0** |
| Single-worker, first delegation | 0 | 0 (unchanged) |
| Recovery (`task_results` non-empty) | 1 | 1 (unchanged) |

The change is one condition: `len(workers) == 1` → `workers`.

### The one test that went red (step 4)

`test_multi_workflow_turn_uses_the_llm_and_honors_its_choice` — exactly the test this
phase predicted would fail, and it was asserting the behaviour being removed. Its
*intent* (the LLM's choice is honored) is still valid on the recovery branch, so it was
**relocated, not deleted**: `test_recovery_turn_uses_the_llm_and_honors_its_choice`
makes the same assertions with `task_results` non-empty, and
`test_multi_workflow_first_delegation_uses_the_table_not_the_llm` replaces it for the
first-delegation case. No test was made green without understanding why it failed, and
no test asserted the LLM *must* be consulted on a first delegation — which the phase
flagged as the signal to stop.

Recovery-path coverage is unchanged: `test_llm_failure_falls_back_to_impact_map…`,
`test_supervisor_rejects_an_impossible_proposal…`, and
`test_supervisor_rejects_a_proposal_outside_this_turns_pending_tasks` all run with
non-empty `task_results` and were untouched.

Step 7 confirmed by grep: `booking_node` still in `WORKER_ORDER` (`routing.py:23`) and
in `SupervisorDecision.next_worker`'s `Literal` (`supervisor.py:45`). It never entered
`workers` before or after, so the condition change cannot affect it.

Suite: 628 passed, same 5 pre-existing unrelated failures.

**Not done — step 8, the manual latency check** ("đi Đà Nẵng 3 ngày 2 người ngân sách
3 triệu"). Needs a live stack; the call-count reduction is measured above instead.