---
phase: 4
title: "Trip data creation path"
status: completed
priority: P2
effort: "1.5d"
dependencies: [1]
---

# Phase 4: Trip data creation path

## Overview

`itinerary_node` khai một action `build_itinerary` mà nó **không bao giờ thực hiện được**:
`_IMPOSSIBLE` chặn node trước khi tới, vì `trip_data` chưa tồn tại. Ràng buộc thật —
"chọn khách sạn là bước tạo chuyến đi" — nằm ẩn trong một lambda, không hiện ở đâu trong
topology, và mâu thuẫn với chính docstring của node.

Phase này làm ràng buộc đó **hiện rõ và đúng**, thay vì xây một đường tạo trip thứ hai.

## Requirements

**Functional**

- Ràng buộc "phải có `trip_data` trước khi `itinerary_node` chạy" hiện rõ ở tầng người
  đọc code thấy được, không chỉ trong một lambda.
- `itinerary_node` không khai action nó không thực hiện được.
- Người dùng yêu cầu lịch trình khi chưa chọn khách sạn nhận được hướng dẫn đúng bước
  tiếp theo, không phải thông báo lỗi.
- Không có đường tạo `trip_data` thứ hai song song với `build_selected_hotel_trip`.

**Non-functional**

- Tuân thủ DRY: `build_selected_hotel_trip` đã dựng trọn bộ hotel + itinerary. Không
  nhân bản logic đó.
- Tuân thủ contract Phase 1: mọi đường về mới phải phát ngôn.

## Architecture

### Hiện trạng chính xác

```
routing.py:47-51
  _IMPOSSIBLE["itinerary_node"] = lambda s:
      not travel_state.destination  OR  not trip_data
```

Ai tạo `trip_data`?

| Đường | Vị trí | Tạo `trip_data`? |
|---|---|---|
| `hotel_node` nhánh `selected_hotel_id` | `hotel_node.py:221-238` | **Có** — `_handle_hotel_selection` → `build_selected_hotel_trip` |
| `hotel_node` nhánh search | `hotel_node.py:302-340` | Không — chỉ trả `hotel_options` |
| `itinerary_node` mọi action | `itinerary_node.py` | Không — mọi action bail khi `trip_data` rỗng |
| `budget_check` | — | Không — chỉ sửa `trip_data` đã có |

Và `build_selected_hotel_trip` (`trip_planner.py:2124`) với `mode="new_trip"` gọi
`_generate_and_save_itinerary` — nó dựng **cả khách sạn lẫn toàn bộ lịch trình** trong
một lần.

### Nhận định: thiết kế này thật ra mạch lạc, chỉ là bị đặt tên sai

Luồng thật của sản phẩm:

```
intake đủ slot → hotel_node search → user chọn khách sạn
                                          │
                                          ▼
                          build_selected_hotel_trip tạo TRỌN BỘ
                          (khách sạn + lịch trình quanh vị trí đó)
                                          │
                                          ▼
                          itinerary_node từ đây chỉ SỬA
                          (rebuild_days, edit_item, lock_days)
```

Điều này **hợp lý**: lịch trình được xếp quanh vị trí khách sạn (`hotel_node.py` docstring:
*"the hotel anchors the itinerary"*; `routing.py:20-22` giải thích `WORKER_ORDER` cùng lý
do). Không thể dựng lịch trình tối ưu khoảng cách khi chưa biết ở đâu.

Vậy `itinerary_node` **là một editor, không phải builder.** Vấn đề không phải thiếu tính
năng — mà là:

1. Node khai action `build_itinerary` (`itinerary_node.py:189`, mặc định của
   `_parse_task`) mà nó không làm được → supervisor có thể route tới, node bail.
2. `_IMPOSSIBLE` lambda là nơi duy nhất ràng buộc được ghi → người đọc `graph.py` không
   thấy.
3. Thông báo `"itinerary_node: không có lịch trình nào để xây dựng. Hãy chọn khách sạn
   trước."` (dòng 310) là thông báo **đúng** nhưng đến quá muộn và mang prefix dev.

### Quyết định: Option A — làm ràng buộc hiện rõ (khuyến nghị)

**Không** xây action `create_trip` trong `itinerary_node`. Lý do: nó sẽ phải gọi lại
`build_selected_hotel_trip` hoặc nhân bản `_generate_and_save_itinerary` — cả hai đều tệ.
Đường tạo trip đã tồn tại và đúng; nó chỉ cần được **gọi tên đúng**.

Bốn thay đổi:

**1. Đổi tên action mặc định.** `_parse_task` trả `{"action": "build_itinerary"}` cho
task rỗng. Đổi thành `rebuild_days` (all days) — đúng thứ nó thực sự làm. Giữ
`build_itinerary` như alias để không vỡ task_description cũ đã lưu trong checkpointer,
nhưng bỏ khỏi docstring như một action riêng.

**2. Đặt tên và tài liệu hoá ràng buộc.** Tách lambda thành hàm có tên trong
`routing.py`:

```python
def _requires_existing_trip(state: TravelGraphState) -> bool:
    """`itinerary_node` là EDITOR, không phải builder: mọi action của nó
    (rebuild_days, edit_item, lock_days) thao tác trên một `trip_data` đã có.
    Chuyến đi được tạo bởi `hotel_node` khi người dùng chọn khách sạn
    (`build_selected_hotel_trip`) — lịch trình xếp quanh vị trí khách sạn,
    nên không thể dựng trước khi biết ở đâu. Xem WORKER_ORDER."""
    return not bool(state.get("trip_data"))

_IMPOSSIBLE = {
    "itinerary_node": lambda s: _no_destination(s) or _requires_existing_trip(s),
    ...
}
```

**3. Hướng dẫn sớm, không báo lỗi muộn.** Khi người dùng yêu cầu lịch trình mà chưa có
`trip_data`, hôm nay `itinerary_node` bị `_IMPOSSIBLE` chặn → supervisor fallback →
có thể rơi vào `respond` im lặng. Sau Phase 1 nó sẽ raise contract violation hoặc rơi
vào canary log.

Đường đúng: `supervisor` khi thấy `itinerary_node` là worker duy nhất được impact nhưng
`is_impossible` → delegate sang `hotel_node` (bước thực sự cần) kèm reply giải thích.
Nếu `hotel_node` cũng không chạy được (thiếu slot), `ask_slot` đã gate trước rồi.

Cụ thể trong `supervisor._eligible_workers`: khi list rỗng vì lý do `_requires_existing_trip`
và `hotel_node` khả thi, trả `hotel_node` với `routing_source="needs_trip_first"`.

**4. Sửa message.** Bỏ prefix dev, bọc `t()`:
`t("Mình cần bạn chọn khách sạn trước — lịch trình sẽ được xếp quanh vị trí đó.", language)`

### Option B (không chọn, ghi lại để không phải tranh luận lại)

Thêm `itinerary_node` action `create_trip` gọi `build_selected_hotel_trip` với khách sạn
xếp hạng cao nhất, bỏ qua bước người dùng chọn.

**Bác bỏ vì:** (a) nó bỏ qua quyền chọn của người dùng — sản phẩm cố tình cho chọn từ
`hotel_options`; (b) `hotel_node` đã làm việc đó, gọi lại từ node khác là DRY violation;
(c) nó tạo đường thứ hai ghi `trip_data`, đúng thứ `state.py:112-121` cảnh báo.

Chỉ mở lại Option B nếu sản phẩm quyết định có chế độ "tự chọn giúp tôi".

## Related Code Files

- Modify: `backend/src/agents/graph/routing.py` — tách `_requires_existing_trip`, đặt tên + docstring
- Modify: `backend/src/agents/graph/nodes/itinerary_node.py` — đổi action mặc định, sửa message, cập nhật docstring
- Modify: `backend/src/agents/graph/nodes/supervisor.py` — nhánh `needs_trip_first`
- Modify: `backend/tests/test_routing.py` — test cho `_requires_existing_trip`
- Modify: `backend/tests/test_supervisor_routing.py` — test nhánh `needs_trip_first`
- Modify: `ARCHITECTURE.md` — bổ sung mục "Trip creation path" (nối tiếp Phase 3)
- Read-only: `backend/src/services/trip_planner.py:2124` `build_selected_hotel_trip`

## Implementation Steps

1. **Viết test đỏ trước** trong `test_supervisor_routing.py`: state có `destination` +
   `dates` + `people` đủ, `pending_tasks=["itinerary_node"]`, `trip_data={}` → supervisor
   phải trả `hotel_node` với `routing_source="needs_trip_first"`, không phải `respond`.

2. **Tách `_requires_existing_trip`** trong `routing.py` với docstring đầy đủ. Hành vi
   không đổi — thuần refactor đặt tên. Test suite phải xanh ngay.

3. **Thêm nhánh `needs_trip_first`** vào `supervisor._eligible_workers`/`supervisor`:
   khi `workers` rỗng vì `itinerary_node` bị chặn bởi `_requires_existing_trip`, và
   `hotel_node` không impossible → delegate `hotel_node`.

4. **Sửa `_parse_task`**: action mặc định `rebuild_days`; `build_itinerary` giữ làm alias
   được chấp nhận (checkpointer cũ có thể còn task_description mang tên đó).

5. **Cập nhật docstring `itinerary_node`**: nói rõ đây là editor. Bỏ `build_itinerary`
   khỏi bảng action vocabulary như một action riêng, ghi nó là alias lịch sử.

6. **Sửa message dòng 310** — bỏ prefix, bọc `t()`. Thêm msgid vào
   `backend/locales/*/LC_MESSAGES/messages.po` và compile lại `.mo` nếu quy trình repo
   yêu cầu.

7. **Verify contract Phase 1**: nhánh `needs_trip_first` là một delegation, không phải
   worker return — nó không tạo `task_results` entry nên không bị `emits_reply` chi phối.
   Xác nhận `hotel_node` chạy sau đó phát ngôn bình thường.

8. **Chạy test suite** + `test_legacy_guards.py`. File này pin hành vi
   `is_impossible("itinerary_node", ...)` ở **bốn** chỗ, không phải một:

   | Dòng | Assert | Ý nghĩa |
   |---|---|---|
   | 37 | `is True` | Không destination → impossible |
   | 159 | `is True` | Không có trip → impossible |
   | 166 | `is True` | Chỉ có destination, chưa có trip → impossible |
   | **172** | **`is False`** | Đã có trip → possible |

   Dòng 172 là lưới an toàn mạnh nhất cho bước 2: nó pin cả chiều dương, nên refactor
   `_requires_existing_trip` không thể âm thầm biến mọi thứ thành impossible. **Không
   sửa file này** — nếu nó đỏ, refactor sai.

9. **Cập nhật `ARCHITECTURE.md`** mục "Trip creation path": chuyến đi tạo bởi
   `hotel_node`; `itinerary_node` là editor; lý do (lịch trình xếp quanh khách sạn).

10. **Test thủ công**: session mới → nói "lên lịch trình 3 ngày Đà Nẵng cho 2 người" →
    phải nhận danh sách khách sạn kèm giải thích, không phải thông báo lỗi.

## Success Criteria

- [x] `_requires_existing_trip` là hàm có tên với docstring giải thích lý do sản phẩm
- [x] `is_impossible("itinerary_node", ...)` cho kết quả **không đổi** so với trước refactor
- [x] `test_legacy_guards.py` vẫn xanh ở cả 4 assert (37, 159, 166, 172), không sửa file
- [x] Yêu cầu lịch trình khi chưa có `trip_data` → delegate `hotel_node`, `routing_source="needs_trip_first"`
- [x] `itinerary_node` không còn khai `build_itinerary` như action thực hiện được
- [x] Không reply nào còn prefix `itinerary_node:`
- [x] Không có đường thứ hai ghi `trip_data` ngoài `hotel_node`
- [x] `ARCHITECTURE.md` có mục "Trip creation path"
- [ ] Test thủ công: yêu cầu lịch trình từ session mới → nhận hotel options, không nhận lỗi

## Risk Assessment

| Rủi ro | Mức | Giảm thiểu |
|---|---|---|
| Nhánh `needs_trip_first` tạo vòng lặp (supervisor → hotel_node → supervisor → hotel_node) | **Cao** | `hotel_node` luôn pop chính nó khỏi `pending_tasks` trên mọi đường về (`hotel_node.py:194`), nên `all_tasks_done` sẽ trip. Vẫn phải viết test riêng cho vòng lặp: chạy turn đầy đủ và assert `supervisor_iterations` ≤ 2. |
| Đổi action mặc định làm vỡ checkpointer state đang lưu `build_itinerary` | Trung bình | Bước 4 giữ alias. Không xoá tên cũ khỏi code xử lý, chỉ khỏi docs. |
| Refactor `_IMPOSSIBLE` vô tình đổi hành vi | Thấp | Bước 2 là refactor thuần; test suite phải xanh **trước khi** làm bước 3. `test_legacy_guards.py` pin cả 4 case (kể cả chiều `is False` ở dòng 172), nên hạ từ Trung bình xuống Thấp sau verification pass. |
| Người dùng thật sự muốn "dựng lịch trình, tôi không quan tâm khách sạn nào" | Thấp | Đó là Option B, đã ghi lý do bác bỏ. Nếu sản phẩm muốn, mở plan riêng — đừng lén thêm vào đây. |
| Sửa `.po` mà quên compile `.mo` → msgid tiếng Việt vẫn hiện (fallback đúng) | Thấp | Fallback của gettext trả msgid, tức tiếng Việt gốc — degrade an toàn, không lộ key. Vẫn nên compile. |

**Rollback:** revert từng bước độc lập. Bước 2 (refactor tên) an toàn giữ lại kể cả khi
revert bước 3.

## Execution Log — 2026-08-15

Option A as planned; no second trip-creation path built.

Named the constraint `requires_existing_trip` (**public**, not `_requires_existing_trip`
as the plan sketched: the supervisor consumes it, and a cross-module import of a
private name is a smell). Step 2 verified as a pure refactor before anything else
changed — `test_legacy_guards.py`, `test_routing.py`, `test_supervisor_routing.py` all
green, and the 4 pinned `is_impossible` asserts (lines 37, 159, 166, 172) untouched.

**Deviation from step 3, and it matters.** The plan put the `needs_trip_first`
*predicate* in `supervisor`. It went into `routing.py` instead, beside
`is_impossible`/`requires_existing_trip` where its siblings live; the supervisor keeps
the *delegation* (`_redirect_to_hotel_node`). Same behaviour, no private-name import
across modules.

**The loop risk was real and needed more than the plan's mitigation.** The plan argued
`hotel_node` always pops itself from `pending_tasks`, so `all_tasks_done` would trip.
That is only true if `pending_tasks` empties — and `hotel_node` removes *only itself*,
while `all_tasks_done` is `not pending_tasks`. Redirecting with `itinerary_node` still
pending would have gone: supervisor → hotel_node → supervisor (trip still missing) →
hotel_node … to the iteration cap, doing a hotel search each pass. So the redirect
**hands the pending slot over** rather than adding to it: `itinerary_node` is replaced
by `hotel_node`. `TestNeedsTripFirst::test_the_redirect_cannot_loop` pins this
explicitly, including `supervisor_iterations == 1`.

Action vocabulary: default is now `rebuild_days`; `build_itinerary` stays an accepted
alias (older checkpointer threads can carry it) but is documented as historical, not a
capability. Note `build_itinerary` also names an unrelated scheduler primitive in
`trip_scheduler.py` — untouched, different thing.

Step 7 verified: `needs_trip_first` is a delegation, appends no `task_results` entry,
and `supervisor` is not wrapped by `enforce_contract` at all, so the Phase 1 contract
does not apply to it. `hotel_node` runs next and replies normally.

Single-writer criterion verified by grep: `hotel_node.py:237` is the only *creation*
site for `trip_data`; `budget_check`, `itinerary_node`, and the `rebuild_day` subgraph
only modify an existing one.

Suite: 623 passed, same 5 pre-existing unrelated failures.

**Not done — step 10, the manual test** ("lên lịch trình 3 ngày Đà Nẵng cho 2 người"
from a fresh session should return hotel options, not an error). Needs a live stack.
`TestNeedsTripFirst` covers the routing decision at unit level.