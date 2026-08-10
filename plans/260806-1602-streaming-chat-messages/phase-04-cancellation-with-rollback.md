---
title: "Phase 4: Cancellation with rollback"
status: todo
phase: 4
priority: P1
effort: "3 ngày"
dependencies: [2, 3]
---

# Phase 4: Huỷ lượt & rollback

## Overview

Huỷ một lượt đang chạy và đưa session về **đúng** trạng thái trước lượt đó — cả
`session.state` trong RAM lẫn message history của LangGraph checkpointer. Kèm một **rào
điểm-không-quay-lại**: sau lần ghi Supabase đầu tiên, huỷ bị từ chối vì không thể hoàn tác
được nữa.

Đây là phase đắt nhất và rủi ro nhất của plan. Người dùng đã chọn nó sau khi thấy rõ chi
phí (06/08/2026).

## Requirements

- Functional:
  - `POST /api/v1/chat/{session_id}/cancel` → `202` (sẽ huỷ) / `409` (qua rào) / `404`
    (không có lượt đang chạy).
  - Huỷ trước rào: sau khi huỷ, lượt kế tiếp cho kết quả **như thể lượt bị huỷ chưa từng
    xảy ra**.
  - Huỷ sau rào: lượt chạy tới hết, `final` về bình thường, DB và session nhất quán.
  - Client đóng kết nối SSE cũng kích hoạt cùng đường huỷ đó.
- Non-functional:
  - Endpoint cancel **không được** lấy `session.lock` — lock đang bị lượt cần huỷ giữ.
  - Đường POST cũ không có khái niệm huỷ, không đổi hành vi.

## Architecture

### Vì sao rollback state khả thi

Toàn bộ business fact sống trong `session.state`, một `TripState` TypedDict serializable
thuần (`agents/state.py:28`); mọi property của `TripSession` chỉ là view xuyên qua nó
(`session.py:101-120`, `:173-260`). Nên:

```python
snapshot = copy.deepcopy(session.state)     # trước lượt
...
session.state.clear()                        # khi huỷ
session.state.update(snapshot)               # sửa tại chỗ, KHÔNG gán lại
```

Gán `session.state = snapshot` cũng chạy, nhưng sửa tại chỗ an toàn hơn nếu có chỗ nào giữ
tham chiếu tới dict cũ (`_run_chat_agent` truyền `{**session.state, ...}` vào agent —
tham chiếu, không phải bản copy).

### Hai thứ nằm ngoài `session.state`

**1. Message history của checkpointer.** `MemorySaver` keyed theo `thread_id`, là store
**tách biệt** với `session.state` — comment `session.py:1110-1116` nói rõ điều này. Rollback
bằng `RemoveMessage`, đúng pattern đã chạy thật ở `_compact_history` (`session.py:1065`):

```python
def _rollback_agent_messages(session, pre_turn_ids: set[str]) -> None:
    """Xoá mọi message agent thêm vào trong lượt này.

    Dùng lại cơ chế RemoveMessage của `_compact_history` (session.py:1065) —
    cơ chế đó đã chạy thật trong production, không phát minh lại.
    """
    state = session.agent.get_state(session.config)
    current = state.values.get("messages", [])
    added = [m for m in current if getattr(m, "id", None) and m.id not in pre_turn_ids]
    if added:
        session.agent.update_state(
            session.config, {"messages": [RemoveMessage(id=m.id) for m in added]}
        )
```

Chụp `pre_turn_ids` trước lượt bằng `get_state`. Dùng tập id thay vì đếm số lượng — an
toàn hơn khi `add_messages` sắp xếp lại.

**2. Ghi Supabase — không hoàn tác được.** Ba chỗ:

| Chỗ ghi | Vị trí |
|---|---|
| `sessions.upsert()` + `persist_itinerary_bundle()` | `trip_planner.py:307-321` |
| `rpc("finalize_itinerary")` | `itinerary_store.py:252` |
| `refresh_embedding` rpc | `itinerary_store.py:266`, `:296` |

Không có transaction bao quanh, không có RPC bù trừ. Plan này **không giả vờ rollback được
chúng** — dựng rào thay vì.

### `TurnCancellation`

```python
# backend/src/agents/cancellation.py  (mới)

class TurnCancelled(Exception):
    """Ném ra tại một checkpoint khi lượt đã bị yêu cầu huỷ."""

class TurnCancellation:
    """Token huỷ cooperative cho một lượt.

    `armed` chuyển False vĩnh viễn ngay trước lần ghi ngoài đầu tiên. Sau đó
    lượt phải chạy tới hết: không có cách nào hoàn tác một RPC Supabase đã gửi,
    nên cho huỷ ở đó sẽ để DB lệch với state trong RAM.

    `_lock` bảo vệ cặp (armed, requested) khỏi race giữa luồng cancel và luồng
    lượt đang chạy — không có nó thì `disarm()` và `request()` chen được vào
    nhau đúng tại ranh giới rào.
    """
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._armed = True
        self._requested = False

    def request(self) -> bool:
        """Luồng cancel gọi. True = đã nhận, False = đã qua rào."""
        with self._lock:
            if not self._armed:
                return False
            self._requested = True
            return True

    def checkpoint(self) -> None:
        """Luồng lượt gọi tại các ranh giới an toàn."""
        with self._lock:
            if self._requested and self._armed:
                raise TurnCancelled()

    @contextmanager
    def no_cancel(self, reason: str):
        """Rào điểm-không-quay-lại. Bọc quanh mọi lần ghi ngoài."""
        with self._lock:
            if self._requested:
                raise TurnCancelled()      # huỷ trước rào — vẫn rollback được
            self._armed = False            # từ đây không quay lại được
        yield
```

Cùng cơ chế `contextvars` như Phase 2 để lấy token hiện tại từ sâu trong pipeline.

### Các checkpoint

Đặt tại đúng những ranh giới mà state đang nhất quán:

| Vị trí | File |
|---|---|
| Sau `_decide_route` | `session.py:702` |
| Trước `tools.recommend_hotels.invoke` | `session.py:981` |
| Trước `_run_finalize` | `session.py:705` |
| Giữa mỗi event của vòng lặp agent | `session.py:1130` |
| Trước mỗi attempt của vòng retry | `session.py:1086` |
| Sau `_run_edit_draft` | `session.py:719` |

Rào `no_cancel("persisting")` bọc quanh `_persist_itinerary_metadata`
(`trip_planner.py:307`) và `finalize_trip_data` (`itinerary_store.py:252`) — cùng chỗ phát
`phase` key `persisting` ở Phase 2, nên UI tắt nút "Dừng" đúng thời điểm rào đóng.

### Registry lượt đang bay

`SessionRegistry` hiện tại không biết gì về lượt. Thêm một map riêng, **không** dùng
`session.lock`:

```python
# backend/src/api/routes.py
_inflight: dict[str, TurnCancellation] = {}
_inflight_lock = threading.Lock()          # bảo vệ chính dict, không phải session
```

Endpoint cancel chỉ chạm `_inflight` + `TurnCancellation._lock`, cả hai đều được giữ trong
micro-giây. Nó **không bao giờ** chờ `session.lock`.

Đăng ký khi bắt đầu lượt stream, gỡ trong `finally`. Registry là process-local — giống hệt
giới hạn một-worker đã ghi ở `session.py:1216-1218`.

### Luồng huỷ đầy đủ

```
1. FE bấm "Dừng" → POST /chat/{id}/cancel
2. tra _inflight → TurnCancellation.request()
   ├─ False (đã qua rào) → 409, FE tắt nút, lượt chạy tiếp
   └─ True → 202, FE hiện "Đang dừng…"
3. Luồng lượt chạy tới checkpoint kế tiếp → raise TurnCancelled
4. Wrapper bắt TurnCancelled:
     session.state.clear(); session.state.update(snapshot)
     _rollback_agent_messages(session, pre_turn_ids)
     emitter.emit("cancelled", rolled_back=True)
5. finally: gỡ khỏi _inflight, nhả session.lock
6. FE nhận `cancelled` → xoá bong bóng đang stream, khôi phục composer
```

Client đóng SSE (`request.is_disconnected()` trong `sse_stream`, Phase 1) đi vào **đúng
bước 2** — cùng đường, không có nhánh thứ hai.

### Điều huỷ **không** làm được

Không cắt ngang được một lời gọi blocking đang bay: query Supabase, HTTP request tới LLM.
Huỷ có hiệu lực tại checkpoint kế tiếp. Độ trễ tệ nhất = bước blocking dài nhất giữa hai
checkpoint — thực tế là `recommend_hotels` (vector search + Supabase), vài giây. Ghi ở
Not-Implemented Register mục 3; UI phải hiện "Đang dừng…" chứ không được biến mất tức thì.

## Related Code Files

- Create: `backend/src/agents/cancellation.py` — `TurnCancelled`, `TurnCancellation`, contextvar
- Create: `backend/tests/test_agents/test_cancellation.py`
- Create: `backend/tests/test_api/test_cancel_endpoint.py`
- Modify: `backend/src/api/routes.py` — `_inflight`, endpoint cancel, snapshot + rollback quanh lượt stream
- Modify: `backend/src/agents/session.py` — 6 checkpoint, `_rollback_agent_messages`
- Modify: `backend/src/services/trip_planner.py` — rào `no_cancel` quanh `_persist_itinerary_metadata`
- Modify: `backend/src/services/itinerary_store.py` — rào `no_cancel` quanh `finalize_trip_data`
- Modify: `docs/chat_api_contract.md` — endpoint cancel + ngữ nghĩa 409

## Implementation Steps

1. Tạo `cancellation.py` + test đơn vị cho `TurnCancellation`: request trước rào, request
   sau rào, request đúng lúc rào đóng (race), double-request.
2. Thêm `_inflight` + endpoint cancel vào `routes.py`. Test: cancel khi không có lượt → 404.
3. Bọc lượt stream: snapshot `deepcopy(session.state)`, chụp `pre_turn_ids`, đăng ký
   `_inflight`, `try/except TurnCancelled/finally`.
4. Viết `_rollback_agent_messages`; test riêng nó bằng một session thật đã chạy vài lượt.
5. Thêm 6 checkpoint vào `session.py`.
6. Thêm rào `no_cancel` vào `trip_planner.py` và `itinerary_store.py`.
7. **Test rollback tương đương** (test quan trọng nhất của phase): chạy lượt A tới hết, ghi
   lại `session.state`. Chạy lại từ session sạch: lượt A, rồi lượt B bị huỷ giữa chừng, rồi
   lượt A lần nữa. Hai `session.state` phải bằng nhau.
8. Test race: ép huỷ đúng lúc `persisting` phát ra; khẳng định hoặc rollback sạch hoặc
   `409` + chạy tới hết — **không có trạng thái thứ ba**.

## Success Criteria

- [ ] Huỷ lượt intake → `session.state` bằng đúng snapshot trước lượt (so sánh dict sâu)
- [ ] Huỷ lượt agent giữa chừng → message history của checkpointer không còn message nào
      của lượt đó
- [ ] **Test tương đương:** A → (B huỷ) → A cho `session.state` giống hệt A → A
- [ ] Huỷ sau `persisting` → `409`, lượt chạy tới hết, `final` bình thường, `trip_data` đúng
- [ ] Endpoint cancel trả lời **trong khi** lượt vẫn đang giữ `session.lock` — test bằng
      lượt cố tình chậm, khẳng định cancel trả về < 100ms
- [ ] Đóng SSE giữa chừng kích hoạt cùng đường huỷ (khẳng định `session.state` đã rollback)
- [ ] Cancel khi không có lượt → 404; cancel hai lần → lần hai vô hại
- [ ] `POST /planner_chat` cũ không có khái niệm huỷ, test hiện có xanh

## Risk Assessment

| Rủi ro | Mức | Giảm thiểu |
|---|---|---|
| Endpoint cancel deadlock vì chờ `session.lock` | Cao | Nó **không bao giờ** chạm `session.lock`. Chỉ `_inflight_lock` + `TurnCancellation._lock`, cả hai giữ trong micro-giây. Test độ trễ < 100ms trong lúc lượt đang giữ lock |
| Rollback state nhưng quên checkpointer (hoặc ngược lại) → lượt sau hành xử lạ | Cao | Cả hai nằm trong **một** hàm rollback, gọi từ **một** chỗ. Test tương đương (bước 7) là thứ duy nhất chứng minh được điều này, và nó bắt buộc |
| Race đúng tại ranh giới rào | Trung bình | `armed` và `requested` cùng dưới một lock; `no_cancel` kiểm `requested` **trước khi** hạ `armed`, trong cùng critical section. Test bước 8 |
| `deepcopy(session.state)` đắt với `trip_data` lớn | Thấp | `trip_data` là JSON thuần vài chục KB. Đo thật ở Phase 6; nếu > 50ms thì đổi sang copy-on-write, nhưng đừng tối ưu trước khi đo |
| `RemoveMessage` không xoá được message thiếu `id` | Trung bình | `_compact_history` đã lọc `hasattr(m,"id") and m.id` — dùng cùng bộ lọc. Message không id là message chưa qua checkpointer, không cần xoá |
| Huỷ để lại file JSON debug lệch (`debug_persist_hook`) | Thấp | `persist_hook` chỉ chạy khi `debug_trip_plan_file` bật, và chạy sau lượt. Gọi nó **sau** rollback, hoặc bỏ qua khi lượt bị huỷ |
| Lượt bị huỷ vẫn giữ worker thread tới checkpoint kế tiếp | Thấp | Đúng theo thiết kế cooperative. Ghi ở Not-Implemented Register mục 3 |
