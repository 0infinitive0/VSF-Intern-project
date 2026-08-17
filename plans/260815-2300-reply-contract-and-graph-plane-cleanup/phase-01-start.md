---
phase: 1
title: "Reply contract"
status: completed
priority: P1
effort: "1d"
dependencies: []
---

# Phase 1: Reply contract

## Overview

Biến "worker phải phát ngôn" từ một quy ước ngầm (mà `itinerary_node` đang vi phạm)
thành một contract cưỡng chế ở biên node, rồi sửa chỗ vi phạm. Kết quả: turn build
itinerary thành công trả reply thật, và mọi vi phạm tương lai là lỗi test-time.

## Requirements

**Functional**

- Turn build/rebuild itinerary thành công phải trả reply mô tả lịch trình vừa dựng,
  không phải `_ACK_VI`.
- `enforce_contract` raise `ContractViolation` khi node khai `emits_reply=True` mà
  `task_results` không tăng thêm entry có `reply` khác rỗng.
- `_ACK_VI`/`_ACK_EN` vẫn tồn tại làm lưới an toàn cuối, nhưng log ERROR khi bị chạm.
- Message lỗi dev-facing không lọt ra reply người dùng.

**Non-functional**

- Không thêm LLM call nào. Reply lấy từ `format_trip_response_from_json` — hàm đã tồn
  tại, đã i18n qua `t()`, đã đọc dữ liệu thật từ `trip_data`.
- Không đổi shape của `PlannerChatResponse`. Frontend không cần sửa.

## Architecture

### Vấn đề chính xác

`itinerary_node` có bốn đường trả về. Chỉ hai đường đầu append `task_results` entry:

| Đường về | Dòng | Append entry có `reply`? |
|---|---|---|
| `_ok(...)` — lock_days, edit_item, all-days-locked | 218-229 | Có |
| `_err(...)` — mọi lỗi | 231-238 | Có (nhưng text là dev string) |
| Multi-day intermediate (còn ngày trong queue) | 352-360 | **Không** — trả `task_results` nguyên xi |
| **All days done** | 362-370 | **Không** — trả `task_results` nguyên xi |

Đường "All days done" là đường mà mọi lần build thành công đi qua. Nó trả
`"task_results": task_results` — biến local chưa hề được append gì.

Đường intermediate không append là **đúng** (chưa xong, chưa có gì để nói). Chỉ đường
cuối cùng là sai.

### Chuỗi dẫn tới `_ACK_VI`

```
itinerary_node (all days done)   task_results = []           ← không append
        │  pending_tasks rỗng → all_tasks_done = True
        ▼
budget_check                     return {}                    ← budget_check.py:329
        │  budget.trip_total chưa SET (mặc định)               (pass-through)
        ▼
respond                          _compose(None, None)          → None
                                 _reply_from_task_results()    → None (list rỗng)
                                 _reply_from_messages()        → None (không AI msg)
                                 → _ACK_VI
```

### Cơ chế cưỡng chế

Mở rộng `NodeContract` (`contracts.py:25`) thêm một field:

```python
@dataclass(frozen=True)
class NodeContract:
    reads: frozenset[str]
    writes: frozenset[str]
    tools: frozenset[str] = frozenset()
    emits_reply: bool = False   # worker này có nghĩa vụ phát ngôn mỗi lần chạy?
```

`enforce_contract` (`contracts.py:117`) hiện chỉ diff `travel_state`. Thêm một check
thứ hai trên `task_results`:

```python
def _wrapped(state):
    before_state = state.get("travel_state") or {}
    before_results = len(state.get("task_results") or [])
    update = node_fn(state)

    # ... check travel_state paths (giữ nguyên) ...

    if contract.emits_reply:
        after_results = update.get("task_results", state.get("task_results") or [])
        new_entries = after_results[before_results:]
        if not any(str(e.get("reply") or "").strip() for e in new_entries):
            # `_violate` chứ không phải `raise` trực tiếp — xem "Chế độ cưỡng chế"
            # bên dưới: raise ở mode `strict`, log ERROR ở mode `log`. Cả hai check
            # (travel_state paths lẫn emits_reply) đều đi qua nó.
            _violate(
                f"{node_name} khai emits_reply nhưng không để lại reply nào "
                f"(task_results tăng {len(new_entries)} entry, không entry nào có reply)"
            )
    return update
```

**Ngoại lệ bắt buộc phải xử lý — đây là chỗ dễ làm sai nhất của phase này:**

`itinerary_node` đường intermediate (multi-day, còn ngày trong queue) **đúng khi không
phát ngôn**. Nếu bật `emits_reply=True` cho `itinerary_node` mà không loại trừ đường
này, mọi trip nhiều hơn 1 ngày sẽ raise `ContractViolation` ngay lượt đầu.

Cách phân biệt: đường intermediate re-queue chính nó (`pending_tasks` chứa
`_WORKER_NAME`) và trả `rebuild_day_queue` không rỗng. Check trở thành:

```python
    if contract.emits_reply and not _is_continuation(node_name, update):
        ...

def _is_continuation(node_name: str, update: dict) -> bool:
    """Worker tự re-queue để chạy tiếp — chưa xong việc, chưa phải lúc phát ngôn."""
    return node_name in (update.get("pending_tasks") or [])
```

Tương tự, `hotel_node` đường `center_unresolved` (dòng 272-281) cố tình trả
`reply: ""` vì `_run_turn_via_graph` vứt bỏ response đó và chạy lại như turn mới.
Đường này set `unresolved_resume_text` — dùng làm dấu hiệu loại trừ thứ hai.

### Chế độ cưỡng chế — raise ở dev, log ở prod

<!-- Updated: Validation Session 1 - contract enforcement mode -->

Raise `ContractViolation` ở production nghĩa là một worker im lặng biến thành **HTTP 500**
— người dùng mất cả turn thay vì nhận một reply tệ. Đó là đánh đổi tệ hơn chính bug đang
sửa.

Env-gated theo đúng khuôn `JAILBREAK_GUARD_MODE` (`config.py:100`, `Literal[...]` +
`Field`) mà `scope_guard.py:48` đã dùng:

```python
# config.py
contract_enforcement_mode: Literal["strict", "log"] = Field(default="strict", ...)
```

| Mode | Hành vi | Dùng ở |
|---|---|---|
| `strict` (mặc định) | Raise `ContractViolation` | dev, test, CI |
| `log` | `logger.error(...)` rồi trả `update` như thường | production |

```python
def _violate(message: str) -> None:
    if getattr(get_settings(), "contract_enforcement_mode", "strict") == "log":
        logger.error("ContractViolation (mode=log, không raise): %s", message)
        return
    raise ContractViolation(message)
```

Mặc định `strict` là cố ý: CI chạy với mặc định, nên một vi phạm mới **không merge được**.
Production đặt `CONTRACT_ENFORCEMENT_MODE=log` trong env — ở đó vi phạm rơi về
`_ACK_VI` kèm canary log (mục dưới), tức hành vi hôm nay cộng thêm khả năng quan sát.

Áp dụng cho **cả hai** check của `enforce_contract` (`travel_state` paths lẫn
`emits_reply`) — cùng một cơ chế, cùng một lý do.

### `_ACK_VI` thành canary

Giữ hằng số, nhưng khi rơi vào nó thì log ERROR đủ context để debug:

```python
reply = _compose(...) or _reply_from_task_results(state) or _reply_from_messages(state)
if reply is None:
    logger.error(
        "respond fell through to the generic ack — no node produced a reply. "
        "routing_source=%s next_worker=%s task_results=%s stage_inputs=%s",
        state.get("routing_source"), state.get("next_worker"),
        state.get("task_results"), bool(state.get("trip_data")),
    )
    reply = _ACK_EN if state.get("language") == "en" else _ACK_VI
```

### Dev string vs user string

`_err()` của `itinerary_node` trộn hai loại:

| Dòng | Text | Loại |
|---|---|---|
| 244 | `"lock_days: days_to_lock is empty"` | Dev assert — supervisor gửi task sai |
| 254 | `"edit_item: user_request is empty"` | Dev assert |
| 305 | `"itinerary_node: unknown action 'x'"` | Dev assert |
| 246 | `"lock_days: không có lịch trình nào để khoá ngày."` | User-facing, nhưng dính prefix |
| 256 | `"edit_item: không có lịch trình nào để chỉnh sửa."` | User-facing, dính prefix |
| 310 | `"itinerary_node: không có lịch trình nào để xây dựng..."` | User-facing, dính prefix |

Tách: dev assert → `logger.error` + reply chung qua `t()`; user-facing → bỏ prefix,
bọc `t()`.

## Related Code Files

- Modify: `backend/src/agents/graph/contracts.py` — thêm `emits_reply`, mở rộng `enforce_contract`, thêm `_is_continuation`, đọc `contract_enforcement_mode`
- Modify: `backend/src/config.py` — thêm `contract_enforcement_mode` (mặc định `strict`)
- Modify: `backend/src/agents/graph/nodes/itinerary_node.py` — đường all-days-done trả reply; tách dev/user string trong `_err`
- Modify: `backend/src/agents/graph/nodes/respond.py` — log ERROR trước khi fallback `_ACK_VI`
- Modify: `backend/tests/test_respond.py` — regression test
- Create: `backend/tests/test_reply_contract.py` — test cho `emits_reply`
- Read-only tham chiếu: `backend/src/services/trip_formatter.py::format_trip_response_from_json` (dòng 88)

## Implementation Steps

1. **Thêm `emits_reply` vào `NodeContract`**, mặc định `False`. Chưa bật cho node nào.
   Chạy full test suite — phải xanh, đây là thay đổi thuần cộng thêm.

2. **Mở rộng `enforce_contract`** với check reply + hàm `_is_continuation`. Vẫn chưa
   bật cho node nào. Test suite phải vẫn xanh.

2b. **Thêm `contract_enforcement_mode`** vào `config.py`, mặc định `"strict"`; đọc nó
   trong `enforce_contract` và áp dụng cho cả hai check. Test suite vẫn xanh (mặc định
   giữ hành vi raise).

3. **Viết test đỏ trước** (`test_reply_contract.py`):
   - Một node giả khai `emits_reply=True` trả `task_results` không đổi → raise (mode `strict`).
   - Node giả đó trả entry có `reply` non-empty → không raise.
   - Node giả re-queue chính nó trong `pending_tasks` → không raise dù không có reply.
   - Mode `log`: node im lặng → **không** raise, có log ERROR, `update` trả về nguyên vẹn.
   - Mode `log` áp dụng cả cho vi phạm `travel_state` path, không chỉ `emits_reply`.

4. **Sửa `itinerary_node` đường all-days-done** (dòng 362-370): append entry
   ```python
   {"worker": _WORKER_NAME, "status": "ok",
    "reply": format_trip_response_from_json(trip_data, language)}
   ```
   Import `format_trip_response_from_json` từ `src.services.trip_formatter`.
   Lưu ý `language` đã có sẵn ở dòng 186.

5. **Bật `emits_reply=True`** cho `itinerary_node`, `hotel_node`, `booking_node` trong
   `CONTRACTS`. Xử lý ngoại lệ `hotel_node` đường `center_unresolved` (loại trừ khi
   `update` có `unresolved_resume_text`). `qa_node` **không** bật — nó không đi qua
   `enforce_contract` (`graph.py:104`) và phát ngôn qua channel `messages`.

6. **Chạy test suite.** Mọi `ContractViolation` xuất hiện là một đường im lặng thật —
   sửa từng cái, đừng nới contract.

7. **Thêm log ERROR** trong `respond` trước khi fallback `_ACK_VI`.

8. **Regression test trong `test_respond.py`**: dựng state có `trip_data` đầy đủ +
   `task_results` có reply từ itinerary_node → assert `response["reply"] != _ACK_VI`
   và chứa tên khách sạn.

9. **Tách dev/user string trong `_err`** của `itinerary_node`.

10. **Test end-to-end thủ công**: `chọn khách sạn → build lịch trình`, xác nhận reply
    chứa tên khách sạn + các ngày.

## Success Criteria

- [x] `NodeContract.emits_reply` tồn tại, mặc định `False`
- [x] `enforce_contract` raise `ContractViolation` khi node khai `emits_reply` mà im lặng (mode `strict`)
- [x] `contract_enforcement_mode` mặc định `strict`; mode `log` không raise, chỉ log ERROR
- [x] Mode áp dụng cho **cả** check `travel_state` path lẫn check `emits_reply`
- [x] `_is_continuation` cho phép `itinerary_node` im lặng ở lượt multi-day intermediate
- [x] `hotel_node` đường `center_unresolved` không bị contract chặn
- [x] `itinerary_node` all-days-done trả reply từ `format_trip_response_from_json`
- [x] `respond` log ERROR kèm `routing_source`/`next_worker`/`task_results` trước mọi fallback `_ACK_VI`
- [x] Test: build itinerary → `reply != _ACK_VI`, reply chứa tên khách sạn
- [x] Không reply nào lộ prefix `itinerary_node:`/`lock_days:`/`edit_item:`
- [ ] `backend/tests/` xanh toàn bộ

## Risk Assessment

| Rủi ro | Mức | Giảm thiểu |
|---|---|---|
| Bật `emits_reply` làm vỡ đường multi-day intermediate | **Cao** | Bước 3 viết test cho `_is_continuation` **trước** bước 5. Đây là ngoại lệ dễ bỏ sót nhất. |
| Còn đường im lặng khác chưa biết (ví dụ `hotel_node` nhánh lạ) | Trung bình | Bước 6 dùng chính test suite làm máy dò. Mỗi `ContractViolation` là một phát hiện, không phải một phiền toái — sửa node, không nới contract. |
| Một đường im lặng chưa biết lọt lên production và làm hỏng turn | Trung bình | Đã xử lý bằng `contract_enforcement_mode=log` ở production (quyết định Validation Session 1): vi phạm rơi về `_ACK_VI` + canary log, không thành HTTP 500. `strict` chỉ chặn ở CI. |
| Production quên set `CONTRACT_ENFORCEMENT_MODE=log` → chạy `strict` | Trung bình | Ghi vào doc deploy/env example ở bước 2b. Cân nhắc: nếu rủi ro quên là cao hơn rủi ro merge nhầm, đảo mặc định thành `log` và set `strict` tường minh trong CI — nhưng mặc định-an-toàn-cho-prod làm CI mất tác dụng chặn nếu CI cũng quên. Giữ `strict` mặc định. |
| `format_trip_response_from_json` trả chuỗi rỗng khi `trip_data` thiếu field | Trung bình | Test với `trip_data` tối thiểu. Nếu rỗng, contract sẽ raise ngay — đúng hành vi mong muốn, và lộ ra bug thật ở tầng dưới. |
| Log ERROR gây noise nếu `_ACK_VI` vẫn còn đường hợp lệ | Thấp | Đó chính là mục đích. Nếu noise nhiều, nghĩa là còn đường im lặng chưa đóng — điều tra, đừng hạ log level. |
| Reply dài (5 ngày) làm vỡ layout frontend | Thấp | Legacy plane đã trả đúng chuỗi này trước cutover; frontend đã render được. |

**Rollback:** đặt `emits_reply=False` cho mọi node trong `CONTRACTS` — check tự tắt,
hành vi về nguyên trạng. Fix ở bước 4 độc lập và giữ lại được.

## Execution Log — 2026-08-15

Steps 1-9 done. `backend/tests/`: **618 passed, 5 failed** — the same 5 failures
present on this branch before any change here, all in areas this phase does not
touch: `test_room_availability_schema.py` (2) and `test_supabase_search.py` (2)
read migration `.sql` files that do not exist in the repo;
`test_trip_modification.py` (1) patches `trip_planner._search_attraction_candidates`,
a private helper that no longer exists under that name. 18 new tests added, all green.

`tests/test_graph_v2_skeleton.py::test_enforce_contract_allows_a_write_within_the_declared_contract`
needed its test double updated: it stands in for `hotel_node`, which now declares
`emits_reply`, so a faithful stand-in has to leave a reply. The contract was not
loosened to accommodate it — `test_reply_contract.py` covers the obligation directly.

`CONTRACT_ENFORCEMENT_MODE` documented in `backend/.env.example` with the
prod-sets-`log` instruction (risk row "Production quên set").

**Not done — step 10, the manual end-to-end run** (`chọn khách sạn → build lịch
trình`, confirming the reply names the hotel and the days). It needs a live
backend + frontend + LLM/Supabase, which this session could not run. The
equivalent assertions are covered at the unit level by
`test_respond.py::TestRespondNeverSpeaksForASilentWorker`, but a real turn has
not been observed.