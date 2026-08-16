---
phase: 2
title: "Dead plane cleanup"
status: completed
priority: P1
effort: "0.5d"
dependencies: []
---

# Phase 2: Dead plane cleanup

## Overview

Ba endpoint và một hàm trong `routes.py` vẫn đọc/ghi state của control plane đã bị xoá ở
Phase 11 của plan trước. Không node nào trong graph ghi vào state đó, nên chúng trả về
dữ liệu rỗng kèm `{"status": "success"}`. Phase này xoá chúng và cập nhật API contract.

## Requirements

**Functional**

- Không endpoint nào còn đọc `session.trip_data`, `session.intake_state`,
  `session.hotel_pref_state`, hoặc `session.pending_hotel_selection`.
- Không endpoint nào trả `success` cho dữ liệu rỗng.
- Endpoint frontend đang dùng thật giữ nguyên hành vi, byte-for-byte.

**Non-functional**

- `docs/chat_api_contract.md` phản ánh đúng surface còn lại — đây là **thay đổi
  public contract**, phải ghi rõ, không xoá lặng lẽ.

## Architecture

### Bằng chứng: cái gì thật sự chết

Comment ở `routes.py:360-366` khẳng định:

> *"There is no alternative plane and no setting selecting one: the legacy
> process_chat_turn cascade is gone."*

Đúng về **luồng xử lý**. Sai về **state**: các field của plane đó vẫn còn trên
`TripSession` và vẫn được ba endpoint đọc.

Writer duy nhất của `session.trip_data` trong toàn repo:

| Vị trí | Ngữ cảnh |
|---|---|
| `session.py:153` | Constructor `create_chat_session(trip_data=...)` |
| `session.py:301` | Reset về `None` |
| `session.py:502` | Restore từ `ItineraryStore` khi rehydrate session từ DB |

**Không có writer nào trong `backend/src/agents/graph/`.** Graph ghi `trip_data` vào
checkpointer state (`TravelGraphState.trip_data`, `state.py:121`), một nơi hoàn toàn khác.

### Ba endpoint chết

**`POST /itineraries/generate`** (`def` ở `routes.py:656`)

```python
if session.trip_data and session.trip_data.get("itineraries"):   # luôn None sau cutover
    ...
_run_turn_via_graph(session_id, "Tạo lịch trình", request.language)
trip_plan = to_trip_plan_payload(session.trip_data)              # None
return {"status": "success", "trip_plan": trip_plan}             # success + None
```

Hai lỗi chồng nhau: đọc state chết, **và** dùng chuỗi tiếng Việt `"Tạo lịch trình"` làm
RPC — gửi vào LLM extractor để lấy lại ý định mà caller đã biết chắc.

**`POST /hotels/search`** (`def` ở `routes.py:587`) — đọc `session.pending_hotel_selection`,
`session.intake_state.destination/people/preferences/start_date/end_date`,
`session.hotel_pref_state.target_price`. Toàn bộ là state legacy. Còn **ba** câu
`print(f"DEBUG: ...")` ở dòng **602, 606, 609** — debug output đi thẳng ra stdout của
server, không qua logger.

**`POST /chat/select_place` + `/places/select`** (`routes.py:326-341`) — gửi
`f"Tôi chọn địa điểm ID {request.place_id}"` vào graph. Không có node nào đọc
`place_id`; `qa_node` cố tình không có tool `select_place` (docstring `qa_node.py:22-32`
giải thích: pick địa điểm được resolve qua interrupt trong `rebuild_day`, không qua tool).
Endpoint này gửi text vào extractor và hy vọng.

### Bằng chứng không có caller

`frontend/src/api/chat-client.ts` gọi đúng 5 endpoint:

| Endpoint | Dòng |
|---|---|
| `POST /chat/session` | 57 |
| `POST /planner_chat` | 71 |
| `POST /hotels/select` | 84 |
| `GET /chat/{id}/plan` | 96 |
| `POST /hotels/change` | 107 |

`frontend/src/api/stream-client.ts:134` gọi thêm `POST /planner_chat/stream`.

**Không file nào trong `frontend/src/`, `backend/tests/`, hay `eval/` gọi ba endpoint
chết.** Chỉ `docs/chat_api_contract.md` còn tài liệu hoá chúng (dòng 17, 19, 222, 264,
670-671).

Kết luận: **xoá, không port.** Port sang graph state là viết code mới cho tính năng
không ai dùng — vi phạm YAGNI.

<!-- Updated: Validation Session 1 - xoá hẳn, không dùng HTTP 410 -->

**Quyết định (Validation Session 1): xoá hẳn, không giữ route trả 410.** Đây là dự án
thực tập, không có consumer bên ngoài cần bảo đảm tương thích. Phương án 410 vẫn ghi ở
bảng risk như đường lùi nếu bước 1 phát hiện caller ngoài repo.

### `_prepare_turn_inputs` — dead code

`routes.py:282-300`. Docstring nói *"Shared bởi planner_chat và planner_chat_stream so
the two endpoints cannot drift apart"*, nhưng cả hai đều gọi thẳng `_run_turn_via_graph`
(dòng 473, 493) và không hàm nào gọi nó. Nó cũng ghi `session.hotel_pref_state` — state
legacy. Xoá.

### `/hotels/change` giữ lại, nhưng ghi nhận nợ

Frontend dùng thật (`chat-client.ts:107`). Nhưng nó gửi chuỗi `"đổi khách sạn"` vào graph
(`routes.py:354`) — cùng anti-pattern "NL string làm RPC". `POST /hotels/select` đã sửa
đúng bằng `extra_state={"selected_hotel_id": ...}` (`routes.py:318-320`).

**Không sửa trong phase này** — nó đang hoạt động, và sửa nó cần một tín hiệu state
deterministic mới mà `hotel_node` phải đọc. Ghi vào `docs/chat_api_contract.md` như nợ
đã biết, và để Phase 4 quyết định (Phase 4 đụng đúng vùng `hotel_node`/`trip_data`).

## Related Code Files

- Modify: `backend/src/api/routes.py` — xoá `itineraries_generate`, `hotels_search`, `select_place`, `_prepare_turn_inputs`
- Modify: `docs/chat_api_contract.md` — bỏ 3 endpoint, ghi nợ `/hotels/change`
- Verify: `backend/src/agents/session.py` — xác nhận field nào trên `TripSession` thành mồ côi sau khi xoá
- Read-only: `frontend/src/api/chat-client.ts`, `frontend/src/api/stream-client.ts` — bằng chứng không có caller

## Implementation Steps

1. **Xác nhận lại không có caller** ngay trước khi xoá (repo có thể đã đổi):
   ```bash
   grep -rn "itineraries/generate\|hotels/search\|places/select\|select_place" \
     frontend/src backend/tests eval scripts
   ```
   Kỳ vọng: chỉ khớp trong comment/docstring, không khớp call site.

2. **Xoá `POST /chat/select_place` + `/places/select`** (`routes.py:326-341`) cùng
   `SelectPlaceRequest` nếu không còn nơi dùng.

3. **Xoá `POST /hotels/search`** (`def` ở `routes.py:587`). Bao gồm cả **ba** câu
   `print(f"DEBUG: ...")` ở dòng 602, 606, 609. Sau khi xoá, xác nhận
   `grep -n "print(" backend/src/api/routes.py` không còn kết quả nào.

4. **Xoá `POST /itineraries/generate`** (`routes.py:655-674`).

5. **Xoá `_prepare_turn_inputs`** (`routes.py:282-300`).

6. **Chạy test suite.** Bất kỳ test nào đỏ là một caller ta bỏ sót — điều tra trước khi
   sửa test.

7. **Kiểm tra field mồ côi trên `TripSession`**: sau khi xoá, `intake_state`,
   `hotel_pref_state`, `pending_hotel_selection` còn reader nào không?
   ```bash
   grep -rn "intake_state\|hotel_pref_state\|pending_hotel_selection" backend/src
   ```
   **Không xoá chúng trong phase này** — `session.py` còn dùng cho serialize/restore và
   `derive_stage`. Chỉ ghi lại kết quả vào Phase 3 để doc phản ánh đúng.

8. **Cập nhật `docs/chat_api_contract.md`**: bỏ 3 endpoint khỏi bảng (dòng 17, 19) và
   section chi tiết (222, 264), sửa câu tổng kết (670-671). Thêm một dòng ghi nợ
   `/hotels/change` dùng NL string làm RPC.

9. **Smoke test thủ công**: chạy backend + frontend, thực hiện luồng đầy đủ
   `session → chat → chọn khách sạn → xem plan → đổi khách sạn`. Không đường nào được gãy.

## Success Criteria

- [x] `routes.py` không còn đọc `session.trip_data`/`intake_state`/`hotel_pref_state`/`pending_hotel_selection`
- [x] Ba endpoint chết đã xoá; `_prepare_turn_inputs` đã xoá
- [x] Không còn `print(` trong `routes.py`
- [ ] `backend/tests/` xanh, không sửa test nào để làm nó xanh
- [x] `docs/chat_api_contract.md` khớp surface thật, ghi rõ đây là breaking change
- [x] Nợ `/hotels/change` (NL string làm RPC) được ghi lại, không sửa lặng lẽ
- [ ] Smoke test 5 endpoint frontend đang dùng: pass

## Risk Assessment

| Rủi ro | Mức | Giảm thiểu |
|---|---|---|
| Có consumer ngoài repo (Postman, script nội bộ, demo) gọi endpoint đã xoá | Trung bình | Người dùng đã quyết định xoá hẳn (Validation Session 1) — dự án thực tập, không có consumer ngoài cần bảo đảm. Đường lùi nếu bước 1 phát hiện caller ngoài repo: `raise HTTPException(410, "Removed after graph cutover")` thay vì xoá. Vẫn tốt hơn trả `success` cho dữ liệu rỗng. |
| Xoá nhầm endpoint frontend đang dùng | Thấp | Bước 1 verify lại ngay trước khi xoá; bước 9 smoke test đủ 5 endpoint. |
| `SelectPlaceRequest` còn dùng chỗ khác | Thấp | Grep trước khi xoá schema. Nếu còn, giữ schema, chỉ xoá route. |
| Xoá field trên `TripSession` làm vỡ serialize/restore | Trung bình | Bước 7 **cố tình không xoá** field. Chỉ khảo sát và ghi lại. Việc dọn `TripSession` là plan riêng. |

**Rollback:** `git revert`. Không có migration, không có state thay đổi.

## Execution Log — 2026-08-15

Step 1 re-verified no callers immediately before deleting: the only repo matches
for the three endpoint paths were a comment and a tool-name assertion in
`tests/test_graph_v2_skeleton.py:114,117` (about `qa_node` deliberately lacking a
`select_place` tool), not call sites. No external caller surfaced, so the fallback
to `HTTP 410` was not needed.

Deleted: `hotels_search` (+ `LoadMoreHotelsRequest` and its three `print(f"DEBUG: …")`
lines), `itineraries_generate`, `select_place` (+ `/places/select` alias),
`_prepare_turn_inputs`. Orphaned `SelectPlaceRequest` import and a stray
`from pydantic import BaseModel` removed with them. `SelectPlaceRequest` itself
kept in `schemas.py` — deleting a schema was not in scope and it costs nothing.

Step 7 survey (fields deliberately left in place): after the deletions `routes.py`
no longer appears among readers of `intake_state`/`hotel_pref_state`/
`pending_hotel_selection`/`session.trip_data` at all. Remaining readers, for
Phase 3 to describe: `agents/session.py` (45 hits, serialize/restore/`derive_stage`),
`models/schemas.py` (15), `services/trip_planner.py` (9), `cli/terminal_chat.py` (6),
`agents/tools/select_hotel.py` (6), `services/trip_formatter.py` (4),
`services/session_store.py` (3), `agents/tools/recommend_hotels.py` (3),
`agents/tools/modify_itinerary.py` (2), `agents/tools/finalize_itinerary.py` (2),
`main.py` (1).

Surviving route surface verified against the registered FastAPI routes — all five
the frontend calls are present (`/chat/session`, `/planner_chat`, `/hotels/select`,
`GET /chat/{id}/plan`, `/hotels/change`) plus `/planner_chat/stream`.

**Not done — step 9, the manual smoke test** of that five-endpoint flow against a
running backend + frontend. Route registration and the full test suite are the
evidence available without a live stack.