---
title: "Streaming chat messages"
description: "Thêm một kênh SSE cho POST /planner_chat: phát token LLM thật trên nhánh agent, phát tiến độ pipeline thật trên các nhánh tất định, kèm huỷ lượt có rollback state. Endpoint POST cũ giữ nguyên làm fallback."
status: "shipped — Phases 1/2/3/5/6 done, Phase 4 (cancellation) paused per 06/08/2026 decision"
priority: P1
effort: "8-11 ngày (1 dev BE + 1 dev FE, song song sau Phase 1)"
tags: [backend, frontend, sse, streaming, langgraph, cancellation, api-contract]
blockedBy: [260805-1022-claude-design-ui-integration]
blocks: []
created: 2026-08-06
updated: 2026-08-07
---

# Streaming chat messages

## Tổng quan

Hiện tại một lượt chat là **một POST đồng bộ duy nhất**. Người dùng gõ xong, bấm gửi, rồi
nhìn `ElapsedSpinner` đếm giây cho tới khi toàn bộ lượt chạy xong — với lượt
`recommend_hotels` hoặc `finalize` thì đó là 10-60 giây màn hình không có gì thay đổi
ngoài con số giây.

Plan này thêm **một kênh SSE song song** (`POST /api/v1/planner_chat/stream`) phát ba loại
sự kiện có thật:

- `phase` — tiến độ quan sát trực tiếp từ pipeline (đã chọn route, tool nào đang chạy,
  đang dựng lịch trình, đang tính chặng đường, đang ghi DB)
- `delta` — token LLM thật, **chỉ** trên nhánh `_run_chat_agent`
- `final` — đúng nguyên vẹn payload `PlannerChatResponse` mà endpoint cũ vẫn trả về

Cộng thêm **huỷ lượt thật** (`POST /api/v1/chat/{id}/cancel`) có rollback state, theo
quyết định của người dùng 06/08/2026.

`POST /api/v1/planner_chat` **giữ nguyên, không đổi một dòng nào**. Nó là fallback khi SSE
bị proxy chặn và là đường mà toàn bộ test hiện có đang đi.

### Phát hiện quyết định: chỉ 1 trong 4 nhánh trả lời là LLM

Đây là điều định hình toàn bộ plan. Text trả lời cho người dùng đến từ **bốn** đường khác
nhau trong `process_chat_turn` (`backend/src/agents/session.py:603`), và chỉ một đường có
token để stream:

| Nhánh | Nguồn text | Có token stream được? | Vì sao chậm |
|---|---|---|---|
| `_run_intake` (`session.py:986`) | chuỗi i18n tất định từ `next_question()` | ❌ không có LLM | Nhanh (<1s) — không cần stream |
| `_run_recommend_hotels` (`session.py:967`) | chuỗi format sẵn từ tool | ❌ tool trả về nguyên khối | **Chậm**: vector search + Supabase + tính điểm |
| `_run_finalize` (`session.py:856`) | chuỗi format sẵn từ `trip_formatter` | ❌ tool trả về nguyên khối | **Rất chậm**: dựng lịch trình + routing + ghi DB |
| `_run_chat_agent` (`session.py:1085`) | prose LLM từ `create_react_agent` | ✅ **có** | Trung bình |

Nghĩa là: **nếu chỉ làm token streaming thì đúng ba nhánh chậm nhất vẫn đứng im.** Đó là
lý do plan này làm cả `phase` events — và đó cũng là thứ đóng được mục **#14 trong
Not-Implemented Register** của plan `260805-1022` ("6 bước AI Searching có dấu tick tuần
tự"), mục trước đây bị loại vì *"backend không phát ra tiến độ theo bước — tick tuần tự sẽ
là tuyên bố tiến độ bịa"*. Lần này tiến độ là thật: mỗi event được phát tại một vị trí code
thực sự chạy qua, không phải timer.

### Ba chốt chặn hạ tầng đã tìm thấy (đều thật, đều phải sửa)

| # | Chốt chặn | Bằng chứng | Hệ quả nếu bỏ qua |
|---|---|---|---|
| 1 | Middleware `log_api_io` **gom toàn bộ body** rồi mới trả | `backend/src/main.py:70-83` — `async for chunk in response.body_iterator: res_body += chunk`, sau đó dựng `Response(content=res_body)` | SSE chết hoàn toàn: client không nhận được gì cho tới khi stream đóng |
| 2 | nginx **không tắt buffering** cho `/api/` | `frontend/nginx.conf:12-22` — không có `proxy_buffering off` | Chạy tốt ở dev (Vite proxy), chết ở Docker/staging. Loại lỗi chỉ hiện ra sau khi deploy |
| 3 | Toàn bộ handler là `def` đồng bộ (chạy trong thread pool) | `routes.py:140` + docstring `routes.py:9-11` — cố ý, vì Supabase/Ollama là blocking | `StreamingResponse` cần async generator; phải bắc cầu thread → async bằng queue, không thể `yield` thẳng từ hàm blocking |

Caddy (`Caddyfile`) tự nhận `text/event-stream` và tắt buffering từ v2 — không cần sửa,
nhưng Phase 6 vẫn xác minh bằng tay chứ không tin vào tài liệu.

### Rollback huỷ lượt: vì sao khả thi, và giới hạn thật của nó

Huỷ có rollback thường rất đắt. Ở codebase này nó **rẻ hơn dự kiến** vì một quyết định
kiến trúc đã có sẵn:

> *"every business fact (`intake_state`, `hotel_pref_state`, `trip_data`,
> `pending_hotel_selection`, `initial_plan_complete`, `planning_new_trip`,
> `pending_trip_edit_request`) lives in `self.state`"* — `TripSession` docstring,
> `session.py:101-120`

Mọi property của `TripSession` chỉ là **view đọc/ghi xuyên qua `self.state`**, một
`TripState` TypedDict thuần serializable (`agents/state.py:28`). Nên một
`copy.deepcopy(session.state)` trước lượt, gán lại khi huỷ, là rollback **nguyên tử cho
toàn bộ state trong RAM** — không cần undo từng field.

Hai thứ nằm **ngoài** `session.state` và phải xử lý riêng:

1. **Message history của LangGraph checkpointer** (`MemorySaver`, keyed theo `thread_id`,
   là store tách biệt — xem comment `session.py:1110-1116`). Rollback bằng
   `RemoveMessage`, đúng pattern đã chạy thật ở `_compact_history` (`session.py:1065`).
2. **Ghi DB không thể hoàn tác** — đây là giới hạn thật:
   - `_persist_itinerary_metadata` → `sessions.upsert()` + `persist_itinerary_bundle()`
     (`trip_planner.py:307-321`)
   - `ItineraryStore.finalize_trip_data` → `rpc("finalize_itinerary")`
     (`itinerary_store.py:252`)
   - `refresh_embedding` → rpc (`itinerary_store.py:266`, `:296`)

Vì không có transaction bao quanh các RPC đó, plan này **không giả vờ rollback được
chúng**. Thay vào đó dựng một **rào điểm-không-quay-lại** (Phase 4): ngay trước lần ghi
ngoài đầu tiên, lượt tự **tước quyền huỷ của chính nó**; từ đó `cancel` trả `409` kèm lý
do, và lượt chạy tới hết. Người dùng thấy nút "Dừng" tắt đi tại đúng thời điểm đó.

**Giới hạn thứ hai, phải nói thẳng:** huỷ **không** cắt ngang được một lời gọi blocking
đang bay (một query Supabase, một HTTP request tới LLM). Nó có hiệu lực tại checkpoint kế
tiếp. Nên độ trễ huỷ = thời lượng của bước blocking đang chạy — tệ nhất là vài giây trong
`recommend_hotels`. Đây là hành vi thật, được ghi vào Not-Implemented Register mục 3, và UI
phải phản ánh đúng (nút chuyển "Đang dừng…", không biến mất tức thì).

### Các quyết định đã chốt với người dùng (06/08/2026)

1. **Token + progress events**, một kênh SSE chung — không phải chỉ token, không phải
   typewriter giả phía client.
2. **Plan riêng**, liên kết với `260805-1022-claude-design-ui-integration` thay vì nhét
   thêm Phase 13/14 vào đó. Lý do: streaming đổi API contract đã đóng băng ở Phase 1
   (Done²) và sửa lại `chat-panel`/`message-list` của Phase 6 (Done).
3. **Huỷ thật, có rollback** — người dùng chọn phương án này sau khi đã thấy rõ chi phí
   (cooperative cancellation + rollback state). Đây là Phase 4, phase đắt nhất của plan.

## Mục tiêu

| # | Mục tiêu | Ưu tiên |
|---|---|---|
| 1 | Một kênh SSE phát `phase` / `delta` / `final`, với `final` giống hệt payload của endpoint POST cũ | P1 |
| 2 | Gỡ ba chốt chặn hạ tầng (middleware buffering, nginx buffering, cầu thread→async) | P1 |
| 3 | Phát tiến độ **thật** tại các vị trí code thực sự chạy qua — đóng mục #14 của plan 260805 | P1 |
| 4 | Stream token thật trên nhánh `_run_chat_agent`, không để lộ JSON tool-call hay tiền tố `SYSTEM ERROR:` | P1 |
| 5 | Huỷ lượt có rollback state trong RAM + checkpointer, kèm rào điểm-không-quay-lại trước lần ghi DB đầu tiên | P1 |
| 6 | `POST /planner_chat` cũ **không đổi một dòng**; FE tự hạ cấp về nó khi SSE hỏng | P1 |
| 7 | Mock server phát SSE đúng contract để FE làm song song từ sau Phase 1 | P2 |
| 8 | Không có bước tiến độ nào là bịa: mọi `phase` key ánh xạ 1-1 tới một dòng code | P1 |

## Danh sách Phase

| # | Phase | Track | Trạng thái | Phụ thuộc |
|---|---|---|---|---|
| 1 | [SSE transport & contract](./phase-01-sse-transport-and-contract.md) | Chung | Done | — |
| 2 | [Tiến độ lượt (phase events)](./phase-02-turn-progress-instrumentation.md) | Backend | Done | 1 |
| 3 | [Token streaming nhánh agent](./phase-03-token-streaming-on-agent-path.md) | Backend | Done | 1 |
| 4 | [Huỷ lượt & rollback](./phase-04-cancellation-with-rollback.md) | Backend | Pause | 2, 3 |
| 5 | [FE tiêu thụ stream](./phase-05-frontend-streaming-consumption.md) | Frontend | Done (trừ nút Dừng — phụ thuộc Phase 4) | 1 |
| 6 | [Tích hợp & kiểm thử](./phase-06-integration-and-verification.md) | Chung | Done (xem ghi chú chưa xác minh trong report) | 2,3,5 |

Phase 1 là phase chặn: nó đóng băng contract sự kiện + mock, sau đó **BE (2→3→4) và FE (5)
chạy song song**, gặp lại ở Phase 6.

## Contract sự kiện (điểm nối giữa 2 track)

`POST /api/v1/planner_chat/stream` — body **giống hệt** `PlannerChatRequest` hiện tại.
Response: `text/event-stream`, `Cache-Control: no-cache`, `X-Accel-Buffering: no`,
`Connection: keep-alive`.

```
event: phase
data: {"key":"hotel_search","tool":"recommend_hotels","at":1754...}

event: delta
data: {"text":"Khách sạn này "}

event: reset
data: {"reason":"discarded_tool_call_json"}

event: final
data: {"session_id":"...","reply":"...","suggestions":[...],"stage":"hotel_options",
       "hotel_options":[...],"trip_plan":null,"intake":{...},"requires_stay_dates":false}

event: cancelled
data: {"rolled_back":true}

event: error
data: {"detail":"Đã xảy ra lỗi máy chủ. Vui lòng thử lại."}

: heartbeat            ← comment frame mỗi 15s, chống idle-timeout của proxy
```

**Bất biến của contract:**

- `final` là **đúng cùng một dict** mà `planner_chat` cũ serialize ra. Không thêm, không
  bớt, không đổi tên field. Phase 6 gác điều này bằng test so sánh trực tiếp hai endpoint.
- Mỗi stream kết thúc bằng **đúng một** frame kết thúc: `final` **hoặc** `cancelled`
  **hoặc** `error`. Không bao giờ hai.
- `delta` chỉ xuất hiện trên nhánh `_run_chat_agent`. Client **không** được giả định lượt
  nào cũng có `delta`.
- Nối toàn bộ `text` của các `delta` (sau `reset` gần nhất) **phải bằng** `final.reply` khi
  lượt đó có stream token. Đây là một assertion test, không phải mong đợi suông.
- `phase.key` là **khoá đục** — backend không gửi text hiển thị. Frontend sở hữu nhãn
  i18n. Tránh có hai nguồn i18n cho cùng một chuỗi.

### Bảng khoá `phase` (mỗi khoá = một vị trí code thật)

| `key` | Phát tại | Tất định hay LLM |
|---|---|---|
| `received` | đầu `process_chat_turn` (`session.py:621`) | — |
| `routing` | ngay trước `_decide_route` (`session.py:702`) | LLM supervisor |
| `route_decided` | sau `_decide_route`, kèm `route` | — |
| `compacting_history` | trong `_compact_history` **chỉ khi thật sự nén** (`session.py:1050`) | LLM |
| `intake_check` | vào `_run_intake` (`session.py:986`) | tất định |
| `hotel_search` | trước `tools.recommend_hotels.invoke` (`session.py:981`) | DB + vector |
| `tool_start` / `tool_end` | vòng lặp event của `_run_chat_agent` (`session.py:1136-1142`) — chỗ này **đã log đúng thông tin đó rồi** | — |
| `itinerary_build` | trong `_generate_and_save_itinerary` (`trip_planner.py:1688`) | LLM + scheduler |
| `routing_legs` | trong `recalculate_itinerary_routes` (`routing.py:93`) | HTTP routing |
| `persisting` | trước `_persist_itinerary_metadata` (`trip_planner.py:307`) — **cũng là rào điểm-không-quay-lại** | DB write |
| `generating` | token prose đầu tiên của agent | LLM |

Không có khoá nào trong bảng này được phát "theo lịch". Nếu một nhánh không chạy qua vị trí
đó thì event không tồn tại — UI phải chịu được việc thiếu bước, và không được vẽ sẵn 6 ô
tick rồi chờ điền.

### Huỷ lượt

```
POST /api/v1/chat/{session_id}/cancel
  → 202 {"cancelling": true}                        đã nhận, sẽ huỷ ở checkpoint kế tiếp
  → 409 {"detail": "past_point_of_no_return"}       đã ghi DB, không huỷ được
  → 404                                             không có lượt nào đang chạy
```

Endpoint này **không được lấy `session.lock`** — lock đang bị chính lượt cần huỷ giữ. Nó
tra một registry riêng các lượt đang bay, keyed theo `session_id`, rồi set một
`threading.Event`. Chi tiết ở Phase 4.

## Lấy gì từ hạ tầng đã có

### Được lấy

- **Pattern rollback checkpointer**: `RemoveMessage` trong `_compact_history`
  (`session.py:1065`) đã chứng minh cách xoá sạch message history của một thread và ghi lại
  — Phase 4 dùng đúng cơ chế đó, không phát minh lại.
- **`TurnResult` + `derive_stage`**: `final` được dựng bằng đúng cùng đoạn code đang chạy ở
  `routes.py:181-204`. Phase 1 trích nó ra một helper dùng chung để hai endpoint không thể
  trôi khỏi nhau.
- **`stream_mode` đã có sẵn**: `_run_chat_agent` đã gọi `session.agent.stream(...)`
  (`session.py:1121`) — Phase 3 chỉ đổi từ `"values"` sang `["values", "messages"]`, không
  viết lại vòng lặp.
- **`sanitize_system_error`**: vẫn là cổng duy nhất cho text ra ngoài; Phase 3 phải chạy
  qua nó **trước** khi phát delta đầu tiên, không phải sau.

### Không được lấy

- **Không dùng `EventSource`** ở frontend. Nó chỉ GET được, mà lượt chat cần POST body.
  Dùng `fetch` + `ReadableStream` + `TextDecoder` + parser frame SSE tự viết (~40 dòng).
- **Không chuyển handler sang `async def`**. Docstring `routes.py:9-11` nói rõ lý do:
  Supabase/Ollama là blocking, `async def` sẽ chẹn event loop. Giữ blocking trong thread,
  bắc cầu bằng queue.
- **Không stream token của `_decide_route` và `_compact_history`**. Cả hai gọi LLM nhưng
  output là nhãn route / bản tóm tắt nội bộ — không phải câu trả lời cho người dùng. Phát
  chúng ra sẽ là rác.

## Phần chưa làm (Not Implemented Register)

| # | Thứ không làm | Vì sao | Thay bằng |
|---|---|---|---|
| 1 | Stream token cho `recommend_hotels`, `finalize`, và toàn bộ nhánh intake | Ba nhánh này không có LLM sinh prose cho người dùng — text là chuỗi i18n tất định hoặc output format sẵn của tool. Không có token nào tồn tại để mà stream | `phase` events thật cho từng bước bên trong (`hotel_search`, `itinerary_build`, `routing_legs`, `persisting`), rồi text về nguyên khối trong `final` |
| 2 | Rollback các lần ghi Supabase (`persist_itinerary_bundle`, `finalize_itinerary`, `refresh_embedding`) | Không có transaction bao quanh các RPC đó, và không có RPC bù trừ. Giả vờ rollback được sẽ để lại DB lệch với state trong RAM — tệ hơn là không cho huỷ | Rào điểm-không-quay-lại: huỷ bị tước quyền ngay trước lần ghi đầu tiên, `cancel` trả `409`, nút "Dừng" tắt trong UI |
| 3 | Huỷ tức thời | Cancellation là cooperative — token chỉ được kiểm tra tại ranh giới checkpoint. Một query Supabase hay HTTP request tới LLM đang bay thì không cắt được từ bên ngoài mà không leak connection | Huỷ có hiệu lực tại checkpoint kế tiếp; UI hiện "Đang dừng…" thay vì biến mất tức thì. Độ trễ tệ nhất = thời lượng bước blocking dài nhất (`recommend_hotels`, vài giây) |
| 4 | Tiến độ theo phần trăm / thanh progress xác định | Không bước nào trong pipeline biết trước tổng thời lượng của mình. Số phần trăm sẽ là bịa | Progress vô hạn (indeterminate) + nhãn bước hiện tại + số giây thật đã trôi — đúng như `ElapsedSpinner` đang làm, chỉ thêm nhãn bước |
| 5 | Sáu ô tick tuần tự vẽ sẵn như bản design | Các nhánh chạy qua tập bước **khác nhau**: lượt intake không đi qua `hotel_search`, lượt hỏi đáp không đi qua `itinerary_build`. Vẽ sẵn 6 ô rồi chờ điền sẽ hiện những ô không bao giờ tick | Danh sách bước **mọc dần** theo event thật nhận được. Đây là bản đóng có điều kiện cho mục #14 của plan 260805 — tiến độ thật thì có, hình dạng vẽ sẵn thì không |
| 6 | Streaming khi chạy nhiều uvicorn worker | Registry lượt đang bay là process-local, giống hệt `SessionRegistry` hiện tại (`session.py:1216-1218` đã ghi rõ giới hạn này). `cancel` gửi tới worker khác sẽ trả 404 | Giữ nguyên ràng buộc một worker đang có. Multi-worker cần session backed bởi Supabase — ngoài phạm vi, đúng như plan trước đã kết luận |
| 7 | Khôi phục stream sau khi mất mạng (`Last-Event-ID` / resume) | Cần buffer sự kiện phía server theo từng lượt và đánh số thứ tự. Với lượt dài nhất ~60s thì chi phí không đáng | Mất kết nối → FE hạ cấp về `POST /planner_chat` cho lượt đó. Lượt vẫn chạy tới hết ở server, kết quả vẫn vào session |

## Rủi ro

| Rủi ro | Mức | Giảm thiểu |
|---|---|---|
| Sửa `log_api_io` làm hỏng log của các endpoint thường | Cao | Không sửa logic gom body; chỉ **thoát sớm** cho path streaming trước khi chạm `body_iterator`. Phase 1 thêm test giữ nguyên hành vi log của `/planner_chat` cũ |
| Buffering ở proxy chỉ lộ ra sau khi deploy | Cao | Phase 6 xác minh **cả ba** tầng bằng tay (Vite dev, nginx Docker, Caddy staging) bằng `curl -N`, kèm mốc thời gian giữa các frame. Không tin vào mặc định của tài liệu |
| Token JSON tool-call bị loại lộ ra màn hình | Trung bình | `_looks_like_textual_tool_call` chỉ chạy được sau khi có đủ text. Phase 3 dựng cổng 16 ký tự đầu: nếu ký tự không-trắng đầu tiên là `{`/`[` hoặc khớp `SYSTEM ERROR:` thì **tắt hẳn stream cho attempt đó**, trả về nguyên khối. `reset` là lưới an toàn cho trường hợp phát hiện muộn |
| Rollback huỷ để lại checkpointer lệch với `session.state` | Cao | Phase 4 rollback **cả hai** trong cùng một hàm, và test khẳng định: sau huỷ, lượt kế tiếp cho ra đúng kết quả như thể lượt bị huỷ chưa từng xảy ra |
| Huỷ ngay tại ranh giới rào (race) | Trung bình | Rào và cancel-token dùng chung một lock nhỏ; `disarm()` và `is_cancelled()` không thể chen nhau. Test race bằng cách ép huỷ đúng lúc `persisting` phát ra |
| Hai endpoint trôi khỏi nhau theo thời gian | Trung bình | Phase 1 trích phần dựng `PlannerChatResponse` ra một helper dùng chung; Phase 6 test so sánh byte-for-byte hai endpoint trên cùng một kịch bản |
| Thread pool cạn khi có nhiều stream cùng lúc | Thấp | Mỗi stream giữ một worker thread cho tới hết lượt — giống hệt POST hiện tại, không tệ hơn. Ghi lại ngưỡng thật đo được ở Phase 6 |

## Tiêu chí hoàn thành

- [x] `POST /api/v1/planner_chat` cũ chạy y hệt trước; toàn bộ test hiện có xanh, không sửa test nào
- [x] `curl -N` tới `/planner_chat/stream` nhận frame đầu **trước** khi lượt chạy xong, qua cả ba tầng proxy —
      Vite dev + nginx xác minh bằng tay 07/08/2026; **Caddy staging chưa xác minh được** (không
      truy cập được từ môi trường phát triển)
- [x] `final.data` khớp byte-for-byte với body của `POST /planner_chat` trên cùng kịch bản
- [x] Nối các `delta` == `final.reply` trên mọi lượt có stream token
- [x] Không lượt nào để lọt JSON tool-call hoặc tiền tố `SYSTEM ERROR:` ra ngoài dưới dạng delta
- [x] Mọi `phase.key` phát ra đều truy ngược được về một dòng code thực thi — không có key theo lịch
- [ ] Huỷ trước rào: `session.state` và message history của checkpointer trở về đúng trạng thái trước lượt; lượt kế tiếp cho kết quả như thể chưa từng có lượt bị huỷ — **Phase 4 tạm dừng, không áp dụng cho lần ship này**
- [ ] Huỷ sau rào: trả `409`, lượt chạy tới hết, DB và session vẫn nhất quán — **Phase 4 tạm dừng, không áp dụng cho lần ship này**
- [x] Mất kết nối SSE giữa chừng → FE hạ cấp về POST và vẫn hiển thị đúng kết quả — chỉ khi
      **chưa nhận frame nào**; đứt sau khi đã nhận frame báo lỗi mạng, không gửi lại (đúng
      thiết kế phase-05, tránh gửi trùng tin nhắn)
- [x] `frontend/mock/server.js` phát SSE đúng contract, FE dev được mà không cần backend

## Liên hệ với plan khác

- **`260805-1022-claude-design-ui-integration`** — plan này `blockedBy` nó, nhưng chỉ phụ
  thuộc vào Phase 1 (contract, Done²), 5 (design system, Done¹), 6 (chat panel, Done) và 7
  (Done). **Cả bốn đều đã xong, nên plan này bắt đầu được ngay.** Các phase còn lại của
  260805 (8, 9, 10, 11, 2, 3, 4, 12) không đụng gì tới streaming và chạy song song được.
- Plan này **đóng có điều kiện** mục #14 trong Not-Implemented Register của 260805 (xem
  mục 5 trong bảng "Phần chưa làm" ở trên: tiến độ thật thì có, sáu ô tick vẽ sẵn thì
  không). Khi Phase 6 xong, cập nhật lại dòng #14 ở `260805-1022/plan.md` trỏ sang đây.
- **`260723-1015-v-ota-poc-master-roadmap`** — đóng hai tiêu chí đang treo:
  `phase-03:63` "Chat endpoint streams tokens" và `phase-05:70` "Assistant responses stream
  visibly".

<!-- slug: streaming-chat-messages -->
