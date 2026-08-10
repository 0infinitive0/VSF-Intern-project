---
title: "Phase 2: Turn progress instrumentation"
status: done
phase: 2
priority: P1
effort: "2 ngày"
dependencies: [1]
---

# Phase 2: Tiến độ lượt (phase events)

## Overview

Luồn một emitter xuyên qua `process_chat_turn` và các service nó gọi, phát `phase` event
tại **các vị trí code thực sự chạy qua**. Đây là phase mang lại giá trị lớn nhất cho người
dùng: ba nhánh chậm nhất (`recommend_hotels`, `finalize`, intake) không có token nào để
stream, nên `phase` event là thứ **duy nhất** làm chúng bớt đứng im.

Đây cũng là phase đóng có điều kiện mục **#14** trong Not-Implemented Register của plan
`260805-1022`.

## Requirements

- Functional:
  - Phát đủ **12 khoá** trong bảng `phase` của `plan.md` (bảng có 11 dòng —
    `tool_start`/`tool_end` là hai khoá chung một dòng), mỗi khoá tại đúng vị trí đã ghi.
    `generating` do Phase 3 sở hữu, còn lại 11 khoá thuộc phase này.
  - Emitter mặc định **no-op**: `POST /planner_chat` cũ gọi cùng đoạn code, không phát gì,
    không tốn gì.
- Non-functional:
  - Không đổi chữ ký công khai của `process_chat_turn` theo kiểu phá vỡ caller. Tham số
    mới là keyword-only, có default.
  - `emit()` không bao giờ raise. Một lỗi trong đường instrument không được giết lượt chat.

## Architecture

### Luồn emitter mà không làm ô nhiễm chữ ký

Ba service nằm sâu (`trip_planner`, `routing`, `itinerary_store`) cũng cần phát event.
Truyền emitter qua 4 tầng tham số là bẩn và sẽ đụng vào hàng chục chữ ký.

**Dùng `contextvars`** — chuẩn thư viện, an toàn thread, và mỗi lượt chạy trọn trong một
worker thread nên không có chuyện lẫn context giữa các lượt:

```python
# backend/src/api/streaming.py
_current_emitter: ContextVar[TurnEmitter | None] = ContextVar("turn_emitter", default=None)

def emit_phase(key: str, **data: Any) -> None:
    """Phát một phase event nếu lượt hiện tại đang stream; ngược lại không làm gì.

    Không bao giờ raise — đường instrument hỏng thì lượt chat vẫn phải chạy.
    """
    try:
        em = _current_emitter.get()
        if em is not None:
            em.emit("phase", key=key, at=time.time(), **data)
    except Exception:
        logger.debug("emit_phase failed for %s", key, exc_info=True)

@contextmanager
def emitting_to(emitter: TurnEmitter | None):
    token = _current_emitter.set(emitter)
    try:
        yield
    finally:
        _current_emitter.reset(token)
```

`ContextVar` được set/reset **bên trong worker thread** (không phải ở async handler) — mỗi
thread có bản copy context riêng, nên hai lượt song song không thấy emitter của nhau.

Endpoint stream bọc lời gọi:

```python
with emitting_to(emitter):
    result = process_chat_turn(session, message, language=language)
```

Endpoint POST cũ **không bọc** → `_current_emitter` là `None` → mọi `emit_phase` là một
lần đọc ContextVar rồi return. Không đổi hành vi.

### Các điểm phát

| Khoá | File:vị trí | Ghi chú cài đặt |
|---|---|---|
| `received` | `session.py:621` đầu `process_chat_turn` | Đã có ở Phase 1, chuyển vào đây |
| `routing` | `session.py:702` trước `_decide_route` | Chỉ phát khi `trip_supervisor_router` bật — tắt cờ thì không có LLM call, phát ra sẽ là bịa |
| `route_decided` | `session.py:702` sau `_decide_route` | Kèm `route=<label>` |
| `compacting_history` | `session.py:1050` | Phát **bên trong** nhánh `if approx_tokens > 5500`, sau dòng log — không phát ở đầu `_compact_history` vì phần lớn lượt thoát sớm mà không nén |
| `intake_check` | `session.py:986` vào `_run_intake` | |
| `hotel_search` | `session.py:981` trước `tools.recommend_hotels.invoke` | Cũng phát ở `routes.py:308` (`hotels_search`) nếu endpoint đó cũng stream — **không** trong phạm vi phase này |
| `tool_start` / `tool_end` | `session.py:1136-1142` | Chỗ này **đã** log đúng tên tool rồi; thêm `emit_phase` cạnh dòng `logger.info` sẵn có, kèm `tool=<name>` |
| `itinerary_build` | `trip_planner.py:1688` `_generate_and_save_itinerary` | |
| `routing_legs` | `routing.py:93` `recalculate_itinerary_routes` | Kèm `legs=<số chặng>` nếu biết trước vòng lặp |
| `persisting` | `trip_planner.py:307` `_persist_itinerary_metadata` | **Cũng là rào điểm-không-quay-lại** — Phase 4 gắn `disarm()` vào đúng đây |
| `generating` | Phase 3 sở hữu | Không làm ở phase này |

### Quy tắc chống bịa

Một `emit_phase` chỉ được đặt tại dòng mà **chắc chắn phải chạy qua** để công việc tương
ứng xảy ra. Cấm:

- phát trước một `if` rồi công việc không chạy;
- phát theo timer hay theo lịch;
- phát một khoá "để cho đủ bộ" khi nhánh đó không có bước tương ứng.

Test của phase này chính là gác điều đó: mỗi khoá có một test khẳng định nó **có** xuất
hiện trên nhánh của nó, và **không** xuất hiện trên nhánh khác.

## Related Code Files

- Modify: `backend/src/api/streaming.py` — thêm `_current_emitter`, `emit_phase`, `emitting_to`
- Modify: `backend/src/api/routes.py` — bọc `emitting_to` trong endpoint stream
- Modify: `backend/src/agents/session.py` — 7 điểm phát
- Modify: `backend/src/services/trip_planner.py` — `itinerary_build`, `persisting`
- Modify: `backend/src/services/routing.py` — `routing_legs`
- Create: `backend/tests/test_api/test_phase_events.py`

## Implementation Steps

1. Thêm `_current_emitter` / `emit_phase` / `emitting_to` vào `streaming.py`.
2. Bọc `emitting_to(emitter)` quanh `process_chat_turn` trong endpoint stream; xác nhận
   endpoint POST cũ không bọc.
3. Thêm điểm phát trong `session.py` theo bảng trên. Với `tool_start`/`tool_end`, đặt cạnh
   `logger.info` đã có — cùng dữ liệu, không tính toán thêm.
4. Thêm điểm phát trong `trip_planner.py` và `routing.py`.
5. Viết `test_phase_events.py`: mỗi nhánh (intake / hotel / finalize / agent) chạy qua một
   `TurnEmitter` giả, khẳng định **tập khoá đúng** — cả có lẫn không.
6. Thêm một test khẳng định `POST /planner_chat` cũ chạy với `_current_emitter is None` và
   output không đổi.

## Success Criteria

- [x] Lượt intake phát `received`, `routing`, `route_decided`, `intake_check` — và **không**
      phát `hotel_search` / `itinerary_build` / `persisting` (`test_phase_events.py`, xác
      minh lại bằng tay qua `curl -N` 07/08/2026)
- [x] Lượt `recommend_hotels` phát `hotel_search`; lượt finalize phát `itinerary_build`,
      `routing_legs`, `persisting` — **thứ tự thật khác giả định ban đầu của mục này**:
      `itinerary_build` → `persisting` → `routing_legs`, vì route recalculation chạy BÊN
      TRONG `persist_itinerary_bundle`. Đã sửa lại trong `docs/chat_api_contract.md`;
      giả định "đúng thứ tự" ở đây là sai, thứ tự phát thật thắng
- [x] `compacting_history` **chỉ** phát khi lịch sử thật sự vượt ngưỡng nén
      (`test_compacting_history_only_when_actually_compacting`)
- [x] Mọi khoá phát ra truy ngược được về một dòng code — bảng khoá trong
      `docs/chat_api_contract.md` ghi rõ file:hàm cho từng khoá
- [x] `POST /planner_chat` cũ: output không đổi, toàn bộ test hiện có xanh
- [x] `emit_phase` nuốt mọi exception — `test_emit_phase_swallows_broken_emitters`

## Risk Assessment

| Rủi ro | Giảm thiểu |
|---|---|
| `ContextVar` rò rỉ giữa các lượt trong thread pool tái sử dụng thread | `emitting_to` là context manager có `reset(token)` trong `finally`. Test: chạy 2 lượt tuần tự trên cùng thread, lượt thứ 2 (không stream) phải thấy `None` |
| Instrument làm chậm đường POST cũ | `emit_phase` khi không stream = một lần `ContextVar.get()` + so sánh `None`. Không đo được |
| Đặt nhầm điểm phát → tiến độ bịa | Test theo nhánh (bước 5) khẳng định cả khoá **vắng mặt**, không chỉ khoá có mặt |
| `routing_legs` phát mỗi chặng làm ngập stream | Phát **một** lần trước vòng lặp kèm tổng số chặng, không phát trong vòng lặp |
