---
title: "Phase 1: SSE transport and contract"
status: done
phase: 1
priority: P1
effort: "2 ngày"
dependencies: []
---

# Phase 1: SSE transport & contract

## Overview

Dựng đường ống SSE trống rỗng nhưng chạy được từ đầu tới cuối: endpoint mới, cầu
thread→async, ba chốt chặn hạ tầng được gỡ, contract sự kiện đóng băng trong
`docs/chat_api_contract.md`, types TypeScript, và mock server phát SSE. Cuối phase này chưa
có `phase` event nào ngoài `received`, chưa có `delta` nào — nhưng `final` đã về đúng và FE
bắt đầu làm song song được.

**Đây là phase chặn.** Sau nó, Phase 2/3/4 (BE) và Phase 5 (FE) chạy song song.

## Requirements

- Functional:
  - `POST /api/v1/planner_chat/stream` nhận **đúng** `PlannerChatRequest` hiện tại, trả
    `text/event-stream`.
  - Phát `received` khi bắt đầu, `final` khi xong, `error` khi hỏng, `: heartbeat` mỗi 15s.
  - `POST /api/v1/planner_chat` cũ không đổi hành vi.
- Non-functional:
  - Frame đầu tiên tới client **trước** khi lượt chạy xong, qua Vite dev proxy và nginx.
  - Không chuyển handler blocking sang `async def`.

## Architecture

### Cầu thread → async

Handler stream là `async def` (bắt buộc, để `StreamingResponse` yield được), nhưng
`process_chat_turn` vẫn chạy blocking trong worker thread. Nối bằng một queue:

```python
# backend/src/api/streaming.py  (mới)

@dataclass
class StreamEvent:
    event: str                 # "phase" | "delta" | "reset" | "final" | "cancelled" | "error"
    data: dict[str, Any]

_SENTINEL = object()          # đánh dấu hết stream

class TurnEmitter:
    """Kênh một chiều từ worker thread (đồng bộ) sang SSE generator (async).

    `emit()` được gọi từ sâu trong pipeline đồng bộ và KHÔNG BAO GIỜ được block —
    dùng queue không giới hạn, bỏ qua backpressure. Một lượt phát tối đa vài chục
    event nên bộ nhớ không phải mối lo; block ở đây thì sẽ deadlock chính lượt đó.
    """
    def __init__(self) -> None:
        self._q: queue.SimpleQueue = queue.SimpleQueue()

    def emit(self, event: str, **data: Any) -> None:
        self._q.put(StreamEvent(event, data))

    def close(self) -> None:
        self._q.put(_SENTINEL)
```

Generator async đọc queue bằng `asyncio.get_running_loop().run_in_executor` với timeout
ngắn, để xen được heartbeat và phát hiện client ngắt kết nối:

```python
async def sse_stream(emitter, worker_future, request):
    yield ": open\n\n"                       # ép proxy flush ngay
    last_beat = time.monotonic()
    while True:
        if await request.is_disconnected():
            break                             # Phase 4 gắn huỷ vào đây
        item = await _poll(emitter, timeout=1.0)
        if item is _SENTINEL:
            break
        if item is not None:
            yield f"event: {item.event}\ndata: {json.dumps(item.data, ensure_ascii=False)}\n\n"
            last_beat = time.monotonic()
        elif time.monotonic() - last_beat > 15:
            yield ": heartbeat\n\n"
            last_beat = time.monotonic()
```

`ensure_ascii=False` là bắt buộc — reply là tiếng Việt, escape ra `\uXXXX` sẽ làm frame
phình gấp ~3 lần.

### Trích helper dựng response dùng chung

`routes.py:181-204` đang dựng `PlannerChatResponse` inline. Hai endpoint mà mỗi bên tự dựng
thì chắc chắn sẽ trôi khỏi nhau. Trích ra:

```python
# backend/src/api/routes.py
def build_chat_response(session, result, session_id, language) -> PlannerChatResponse:
    """Nguồn duy nhất dựng PlannerChatResponse. Cả planner_chat và
    planner_chat_stream đều đi qua đây — Phase 6 test hai endpoint khớp nhau."""
```

`planner_chat` cũ được sửa để **gọi helper này** thay vì dựng inline. Đó là thay đổi duy
nhất được phép chạm vào endpoint cũ, và nó không đổi output — Phase 6 gác bằng test.

### Gỡ chốt chặn 1 — middleware buffering

`main.py:45-83`. Thoát sớm, **trước** khi chạm `response.body_iterator`:

```python
_STREAMING_PATHS = ("/api/v1/planner_chat/stream",)

@app.middleware("http")
async def log_api_io(request: Request, call_next):
    if not request.url.path.startswith("/api/"):
        return await call_next(request)
    if request.url.path in _STREAMING_PATHS:
        # SSE: gom body sẽ giữ toàn bộ stream lại tới khi đóng. Log input rồi
        # trả thẳng response, không đụng vào body_iterator.
        ...log input only...
        return await call_next(request)
    ...giữ nguyên toàn bộ nhánh cũ, không sửa một dòng...
```

Không đổi logic gom body của nhánh cũ. Đây là điều kiện để test log hiện có vẫn xanh.

### Gỡ chốt chặn 2 — nginx

`frontend/nginx.conf`, trong `location /api/`:

```nginx
proxy_buffering     off;
proxy_cache         off;
proxy_read_timeout  600s;    # stream sống lâu hơn một request thường
```

App cũng gửi `X-Accel-Buffering: no` để phòng khi có tầng nginx khác không do repo này sở
hữu.

## Related Code Files

- Create: `backend/src/api/streaming.py` — `StreamEvent`, `TurnEmitter`, `sse_stream()`, format frame
- Create: `backend/tests/test_api/test_chat_stream.py`
- Modify: `backend/src/api/routes.py` — thêm `planner_chat_stream`, trích `build_chat_response`
- Modify: `backend/src/main.py` — thoát sớm cho path streaming trong `log_api_io`
- Modify: `frontend/nginx.conf` — tắt buffering cho `/api/`
- Modify: `docs/chat_api_contract.md` — thêm mục contract SSE + bảng khoá `phase`
- Modify: `frontend/src/types.ts` — `StreamEvent`, `PhaseKey`, `TurnPhase`
- Modify: `frontend/mock/server.js` — phát SSE cho `/planner_chat/stream`

## Implementation Steps

1. Tạo `backend/src/api/streaming.py`: `StreamEvent`, `TurnEmitter`, `_poll`, `sse_stream`,
   helper format frame. Chưa nối vào pipeline.
2. Trích `build_chat_response()` trong `routes.py`; sửa `planner_chat` cũ gọi nó. Chạy
   `backend/tests/test_api/test_chat_flow.py` — phải xanh, không sửa test.
3. Thêm `planner_chat_stream`: cùng phần tra session + 404 như endpoint cũ, rồi chạy
   `process_chat_turn` trong `run_in_executor`, phát `received` → `final`.
4. Sửa `log_api_io` thoát sớm cho path streaming.
5. Sửa `frontend/nginx.conf`; thêm header `X-Accel-Buffering: no` vào `StreamingResponse`.
6. Viết mục contract SSE vào `docs/chat_api_contract.md` — copy nguyên bảng khoá `phase` từ
   `plan.md` để phase file và doc không lệch.
7. Thêm types vào `frontend/src/types.ts`.
8. Thêm nhánh SSE cho `/planner_chat/stream` trong `frontend/mock/server.js`: dùng lại
   fixture `TURNS` sẵn có, chia `_delay` thành các mốc phát `phase` giả lập, rồi phát
   `final` bằng đúng fixture cũ.

## Success Criteria

- [x] `curl -N -X POST .../planner_chat/stream -d '{...}'` in ra `: open` **ngay**, rồi
      `final` sau khi lượt xong — xác minh bằng tay 07/08/2026, xem
      `plans/reports/verification-260806-streaming.md`
- [x] Frame đầu tới trước frame cuối ít nhất 1s trên lượt có `_delay` (đo bằng mốc thời gian)
      — xác minh trên backend thật (không phải `_delay` mock): 1.97-8.5s tuỳ tầng proxy
- [x] `POST /planner_chat` cũ: toàn bộ test hiện có xanh, không sửa test nào
- [x] Log của endpoint cũ vẫn in đủ input + output như trước
- [x] SSE chạy qua Vite dev proxy và qua nginx trong Docker — Vite dev + nginx (container
      cô lập dùng đúng `nginx.conf` của nhánh này) xác minh bằng tay; Caddy staging
      **chưa xác minh được** (không truy cập được từ môi trường này)
- [x] Mock server phát được stream đủ 4 lượt kịch bản — xác minh bằng tay 07/08/2026, cả 4
      lượt (`turnCounters` 1-4) và lượt `:stream` (agent chat, delta thật) đều phát đúng

## Risk Assessment

| Rủi ro | Giảm thiểu |
|---|---|
| Thoát sớm trong middleware làm mất log của endpoint thường | Match theo path chính xác, không prefix. Test khẳng định log của `/planner_chat` không đổi |
| `SimpleQueue` không giới hạn → phình bộ nhớ nếu client treo | Một lượt phát tối đa ~vài chục event. Generator vẫn đọc queue tới `_SENTINEL` kể cả khi client ngắt, nên queue luôn cạn |
| `run_in_executor` dùng chung thread pool với handler đồng bộ | Đúng như POST hiện tại — mỗi lượt giữ một thread. Không tệ hơn baseline; Phase 6 đo ngưỡng thật |
| Vite proxy nén hoặc buffer SSE | Xác minh ở bước 8; nếu có, thêm `compress: false` vào config proxy |
