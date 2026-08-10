---
phase: 5
title: "Dọn dead code backend"
status: pending
priority: P2
effort: "4-6h"
dependencies: [1, 4]
---

# Phase 5: Dọn dead code backend

## Overview

Xoá import/biến chết, symbol không ai tham chiếu, config field không được đọc, và
gộp một hàm bị định nghĩa trùng ở hai module. Chỉ đụng `backend/src/api/routes.py`
ở mức 4 dòng để tránh conflict với hai plan đang làm dở trên file đó.

## Requirements

**Functional**
- `ruff check src --select F` → 0 lỗi
- Không còn hàm nào bị định nghĩa trùng ở hai module
- Test suite xanh, số test không giảm

**Non-functional**
- Không mass-format (`UP*`/`W*` để nguyên)
- Mỗi symbol bị xoá phải có bằng chứng grep kèm theo
- Thay đổi trên `routes.py` giữ ở mức tối thiểu

## Architecture

### Định nghĩa trùng — sửa trước, vì là rủi ro thật

`to_hotel_options_payload` được định nghĩa ở **hai** module:

```
backend/src/models/schemas.py:372      def to_hotel_options_payload(pending) -> list[HotelOption]
backend/src/services/trip_formatter.py:359  def to_hotel_options_payload(...)
```

Và `routes.py` import **cả hai**:

```
routes.py:39   from src.models.schemas import ..., to_hotel_options_payload, ...
routes.py:293  from src.models.schemas import to_hotel_options_payload   ← ruff F401: unused
```

Bản import sau shadow bản trước trong phạm vi hàm. Hiện chưa gây lỗi vì cả hai
cùng trỏ về `schemas`, nhưng có hai định nghĩa cùng tên ở hai module với hai chữ
ký khác nhau là bẫy đặt sẵn: đổi một bên, bên kia im lặng phân kỳ.

Test tồn tại cho **cả hai**:
- `tests/test_services/test_trip_formatter.py:7` → import từ `trip_formatter`
- `tests/test_api/test_chat_session.py:27` → import từ `schemas`

Cách gộp: giữ bản ở `trip_formatter.py` (đúng lớp — định dạng payload), để
`schemas.py` re-export hoặc bỏ hẳn tuỳ chữ ký thực tế. **Phải đọc cả hai thân
hàm trước khi quyết** — chúng có thể đã phân kỳ. Nếu khác nhau, đó là bug đang
tồn tại, cần báo cáo chứ không lặng lẽ chọn một bên.

### Import đè lên chính nó — bug thật

```
backend/src/agents/tools/select_hotel.py:23-24  import InjectedToolCallId, InjectedState
backend/src/agents/tools/select_hotel.py:43-44  import InjectedToolCallId, InjectedState   ← F811
```

Nếu hai dòng import từ **nguồn khác nhau** (ví dụ `langchain_core` vs
`langgraph.prebuilt`), hành vi runtime đang phụ thuộc vào bản thứ hai — có thể
không phải bản người viết định dùng. Đọc cả hai dòng, xác định nguồn đúng, giữ
một.

### Symbol không ai tham chiếu

Mỗi mục dưới đây đã được xác minh: grep toàn repo (`backend/src`, `backend/tests`,
`backend/scripts`) chỉ trả về **chính dòng định nghĩa**.

| File | Symbol | Ghi chú |
|---|---|---|
| `src/models/schemas.py:32` | `ChatRequest` | Docstring ghi "pre-Phase 3"; đã thay bằng `PlannerChatRequest` |
| `src/models/schemas.py:36` | `ChatResponse` | Như trên |
| `src/models/schemas.py:41` | `AttractionPayload` | Thay bằng `TripPlanPayload` |
| `src/models/schemas.py:50` | `HotelPayload` | Thay bằng `HotelOption` |
| `src/models/schemas.py:59` | `RoomPayload` | Thay bằng `HotelOption.matched_rooms` |
| `src/agents/state.py:16` | `TripAgentState` | TypedDict, 0 usage |
| `src/agents/session.py:277` | `_load_pending_hotel_selection` | Private, 0 usage |
| `src/services/trip_formatter.py:63` | `build_natural_activity_string` | 0 usage |

### Hai symbol trông chết nhưng KHÔNG được xoá

Kiểm tra chéo với plan đang treo cho thấy hai symbol dưới đây là **đồ dựng sẵn
cho phase chưa làm**, không phải rác. "Chưa ai gọi" ≠ "chết" khi có plan mô tả
đúng chỗ dùng.

| Symbol | Chủ sở hữu | Bằng chứng |
|---|---|---|
| `src/models/schemas.py:93` `RouteInfoPayload` | `260805-1022-.../phase-12-be-mapbox-routing.md` (`pending`) | Dòng 155: "Sửa: `backend/src/models/schemas.py` — thêm `profile` vào `RouteInfoPayload`" |
| `src/services/routing.py:167` `get_route_to_next` | Cùng phase-12 | Phase-12 **viết lại toàn bộ** `routing.py` (thay `OSRMClient` bằng `MapboxDirectionsClient`, thêm `_pick_profile`/`_haversine_km`). Xoá một hàm trong file sắp bị viết lại chỉ tạo conflict — để chủ sở hữu phase-12 quyết |

### Config field không được đọc

`backend/src/config.py`: `app_host`, `app_port`, `database_url`, `log_level` —
grep toàn repo chỉ ra dòng khai báo. Ứng dụng lấy host/port từ uvicorn CLI trong
`docker-compose.yml`. Xoá.

**Không đụng** `qdrant_url`/`qdrant_api_key` ở đây — Phase 2 đã xử lý.

### Import/biến chết còn lại (ruff F401/F841)

```
src/agents/session.py:26        _is_hotel_choice_attempt
src/agents/session.py:38        _has_budget_signal
src/agents/tools/query_hotel.py:3          typing.Any
src/agents/tools/recommend_hotels.py:29    format_hotel_options
src/agents/tools/select_hotel.py:26        TripState
src/services/routing.py:5                  functools.lru_cache
src/services/suggestions.py:7              typing.Any
src/services/supabase_search.py:11         requests
src/services/supabase_search.py:13         OllamaEmbeddings
src/airflow/.../hotel_nearby_pipeline.py:5      time
src/airflow/.../hotel_nearby_supabase_dag.py:3  json
src/api/routes.py:293                      to_hotel_options_payload

F841 (biến gán không dùng):
src/services/supabase_search.py:192, :299   supabase
src/services/trip_intake.py:442             allowed_labels
src/api/routes.py:348, :368, :371           exc, result, exc
src/airflow/dashboard/app.py:141, :163      e
```

`session.py:26,38` import hai hàm private từ module khác mà không dùng — có thể
là **seam re-export** cho test. Grep `_is_hotel_choice_attempt` và
`_has_budget_signal` trong `backend/tests/` trước khi xoá; nếu test import chúng
qua `session_module`, giữ lại và thêm `# noqa: F401` kèm lý do.

`supabase_search.py:11` import `requests` không dùng — nhưng `requests` **có**
được dùng ở chỗ khác trong repo, nên vẫn phải khai báo trong requirements
(Phase 4). Hai việc khác nhau.

### `routes.py` là file nóng

Hai plan đang sửa file này. Thay đổi ở phase này giới hạn ở: 1 dòng import thừa
(:293) + 3 biến `exc`/`result` không dùng. Làm ở commit riêng, cuối cùng của
phase, để dễ rebase.

## Related Code Files

- Modify: `backend/src/models/schemas.py` — xoá 6 model chết, gộp `to_hotel_options_payload`
- Modify: `backend/src/services/trip_formatter.py` — giữ bản chuẩn, xoá `build_natural_activity_string`
- Modify: `backend/src/agents/tools/select_hotel.py` — sửa F811, xoá import thừa
- Modify: `backend/src/agents/session.py` — xử lý 2 import (kiểm test trước)
- Modify: `backend/src/agents/state.py` — xoá `TripAgentState`
- Modify: `backend/src/services/routing.py` — chỉ xoá import `functools.lru_cache`. **Giữ** `get_route_to_next` (phase-12 sở hữu)
- Modify: `backend/src/services/supabase_search.py`, `suggestions.py`, `trip_intake.py`
- Modify: `backend/src/config.py` — xoá 4 field
- Modify: `backend/src/agents/tools/query_hotel.py`, `recommend_hotels.py`
- Modify: `backend/src/airflow/dags/data_pipeline/hotel_nearby_pipeline.py`, `hotel_nearby_supabase_dag.py`
- Modify: `backend/src/airflow/dashboard/app.py`
- Modify: `backend/src/api/routes.py` — commit riêng, cuối cùng

## Implementation Steps

1. Xác nhận lại phạm vi loại trừ: `RouteInfoPayload` và `get_route_to_next`
   **không** nằm trong phase này (phase-12 sở hữu). Nếu phase-12 đã bị huỷ trong
   thời gian chờ, mở lại quyết định này.
2. **Gộp `to_hotel_options_payload` trước.** Đọc cả hai thân hàm
   (`schemas.py:372`, `trip_formatter.py:359`). Nếu đã phân kỳ, dừng lại và báo
   cáo khác biệt trước khi chọn. Giữ bản `trip_formatter`, cập nhật import ở
   `routes.py` và cả hai file test.
3. **Sửa F811 ở `select_hotel.py`.** Xác định nguồn import đúng cho
   `InjectedToolCallId`/`InjectedState`, giữ một cặp. Chạy
   `pytest tests/test_hotel_flow_tools.py -q` ngay sau đó.
4. Xoá 5 model chết ở `schemas.py` (**không** `RouteInfoPayload`). Xác minh từng
   cái bằng grep bao gồm cả dạng chuỗi (FastAPI `response_model`,
   `model_validate` động):
   ```bash
   grep -rn "ChatRequest\|ChatResponse\|AttractionPayload\|HotelPayload\|RoomPayload" \
     --include='*.py' backend/
   ```
5. Xoá `TripAgentState`, `_load_pending_hotel_selection`,
   `build_natural_activity_string`.
6. Xoá 4 config field. `grep -rn "app_host\|app_port\|database_url\|log_level" backend/`
   phải chỉ còn 0 kết quả sau khi xoá.
7. Xử lý 2 import ở `session.py:26,38` — kiểm test trước:
   ```bash
   grep -rn "_is_hotel_choice_attempt\|_has_budget_signal" backend/tests/
   ```
8. Chạy `ruff check src --select F --fix` cho phần còn lại, rồi review từng hunk
   của `git diff`. **Không** chạy `--fix` không giới hạn rule.
9. Xử lý F841 thủ công: `except ... as exc` không dùng → bỏ `as exc`; biến
   `supabase`/`allowed_labels`/`result` → xoá hoặc dùng, tuỳ ý định ban đầu (đọc
   code xung quanh, đừng xoá mù — biến gán không dùng đôi khi là bug logic).
10. Commit riêng cho `routes.py`, đặt cuối cùng.
11. Chạy full suite + `ruff check src --select F`.

## Success Criteria

- [ ] `cd backend && ruff check src --select F` → 0 lỗi
- [ ] `cd backend && pytest -q` → xanh, số test không giảm
- [ ] `grep -c "def to_hotel_options_payload" -r backend/src` → 1
- [ ] `grep -rn "ChatRequest\|ChatResponse\|AttractionPayload\|HotelPayload\|RoomPayload" backend/src` → 0
- [ ] `RouteInfoPayload` và `get_route_to_next` **vẫn còn** (phase-12 sở hữu)
- [ ] `git diff --stat` trên `routes.py` ≤ 6 dòng, ở commit riêng
- [ ] `git diff` không chứa thay đổi `UP*`/`W*` (không mass-format)
- [ ] Mỗi symbol bị xoá có bằng chứng grep trong PR description

## Risk Assessment

| Rủi ro | Giảm thiểu |
|---|---|
| Xoá symbol còn dùng qua đường động (FastAPI `response_model`, `getattr`, tên dạng chuỗi) | Bước 4 grep cả dạng chuỗi, không chỉ định danh. Test suite (Phase 1) + CI (Phase 4) là lưới an toàn |
| Hai bản `to_hotel_options_payload` đã phân kỳ → gộp làm đổi hành vi | Bước 2 dừng lại và báo cáo nếu khác nhau. Cả hai đều có test — chạy cả hai file test sau khi gộp |
| Sửa F811 ở `select_hotel.py` đổi hành vi runtime | Đó là mục đích: hành vi hiện tại đang phụ thuộc vào import đè. Bước 3 chạy test hotel flow ngay sau |
| Conflict với 2 plan đang sửa `routes.py` | Giới hạn thay đổi ở 4 dòng, commit riêng, đặt cuối |
| Người thực thi thấy `RouteInfoPayload`/`get_route_to_next` "0 usage" rồi xoá theo phản xạ | Đã loại trừ tường minh ở 4 chỗ trong phase này, kèm tiêu chí nghiệm thu ngược ("vẫn còn") |
| Xoá biến F841 che mất bug logic (giá trị lẽ ra phải được dùng) | Bước 9 yêu cầu đọc code xung quanh. `supabase_search.py:192,299` gán `supabase` rồi không dùng — đáng nghi, cần xem kỹ |
