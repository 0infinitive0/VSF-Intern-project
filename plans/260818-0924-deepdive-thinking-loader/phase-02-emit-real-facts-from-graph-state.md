---
phase: 2
title: "Phát dữ kiện thật từ state graph"
status: completed
priority: P1
effort: "1d"
dependencies: [1]
---

# Phase 2: Phát dữ kiện thật từ state graph

## Overview

Làm cho frame `phase` chở theo dữ kiện thật của công việc đang chạy, thay vì chỉ một khoá
đục. Không thêm event SSE, không thêm lượt LLM, không đổi contract.

## Nền tảng đã có sẵn

- `emit_phase(key, **data)` (`streaming.py:145`) **đã** nhận kwargs tuỳ ý và đưa thẳng vào
  JSON của frame.
- `routing.py:220` **đã** dùng thật: `emit_phase("routing_legs", days=len(by_day))`.
- FE **đã** khai `phase` có thể mang extras: `{ key, at, days?, … }` (`types/index.ts:210`),
  và `stream-client.ts:162` truyền cả dict `d` qua `onPhase(key, at, d)`.

Nghĩa là đường ống đã thông từ đầu đến cuối. Phase này chỉ đổ dữ liệu vào.

## Requirements

**Functional**
- Mỗi phase key có một **schema dữ kiện tường minh**, tài liệu hoá trong
  `docs/chat_api_contract.md`.
- Dữ kiện rút từ state delta cho: `intake_check` (`intent`, `fields[]`), `routing` (`worker`).
- Dữ kiện phát từ site emit cho: `hotel_search` (`destination`, `radius_km`, `amenities[]`,
  `found`, `kept`), `itinerary_build` (`action`, `days[]`, `locked_days[]`).
- Không có dữ kiện thì **không gửi key đó** — không gửi `null`, không gửi `0` giả.

**Non-functional**
- **Whitelist field tường minh.** Cấm: ID nội bộ (`destination_id`, `session_id`,
  `hotel_id`), tool arg thô, chuỗi exception, bất kỳ field nào chưa có tên trong schema.
  Dữ kiện chỉ được là thứ chính người dùng đã nhập hoặc con số đếm được.
- `emit_phase` đã có hợp đồng never-raise; bộ rút dữ kiện phải nằm **trong** vùng đó —
  một lỗi rút field không được giết chat turn.
- Lượt POST không streaming: `emit_phase` no-op như hiện tại, không tính toán thừa.
- Client cũ nhận extras lạ vẫn chạy — đã đúng theo thiết kế, xác nhận lại.

## Architecture

Hai nguồn, hai cơ chế:

**Nguồn 1 — rút từ state delta.** `routes.py:536-543`:

```python
for node_name, update in chunk.items():
    if node_name == "__interrupt__":
        interrupts = update
        continue
    phase_key = PHASE_KEY_BY_NODE.get(node_name)
    if phase_key:
        emit_phase(phase_key, **phase_facts(node_name, update))
```

`update` là dict node vừa trả về. `extract_patch.py:510` trả
`{patch, intent, extraction_failed, patch_reason, pending_clarify_day}` — `intent` dùng
thẳng, `fields[]` rút từ đường dẫn field trong `patch`. `supervisor` trả `next_worker`.

`phase_facts()` là hàm thuần trong module riêng (`graph/phase_facts.py`), một nhánh cho
mỗi node có dữ kiện, mặc định trả `{}`. Thuần để test không cần dựng graph.

**Nguồn 2 — kwargs tại site emit.** Số kết quả tìm kiếm **không** nằm trong dict
`hotel_node` trả về (`{pending_tasks, task_results, selected_hotel_id}` —
`hotel_node.py:208,215`), nên phải phát từ trong node, cạnh chỗ gọi
`select_hotel_candidates`. Cùng khuôn `routing_legs` đang dùng.

## Related Code Files

- Create: `backend/src/agents/graph/phase_facts.py`
- Create: `backend/tests/test_phase_facts.py`
- Modify: `backend/src/api/routes.py` (vòng drain ~536-543)
- Modify: `backend/src/agents/graph/nodes/hotel_node.py` (thêm `emit_phase("hotel_search", …)`)
- Modify: `backend/src/services/trip_planner.py` (416, 2087 — thêm kwargs)
- Modify: `docs/chat_api_contract.md` (§Streaming — schema dữ kiện từng phase key)
- Modify: `backend/tests/test_stream_modes.py`

## Implementation Steps

1. Chạy `impact({target: "_run_turn_via_graph", direction: "upstream"})`, báo blast radius.
2. **Trước khi viết bộ rút**: chạy một lượt thật với log in ra `update` của từng node.
   Hình dạng state là giả định lớn nhất của phase này — xác minh, đừng suy đoán từ
   `return {}` trong source.
3. Viết `phase_facts.py` theo hình dạng vừa quan sát. Whitelist tường minh, mặc định `{}`.
4. Nối vào vòng drain. Bọc trong cùng vùng never-raise của `emit_phase`.
5. Thêm `emit_phase("hotel_search", …)` trong `hotel_node` cạnh chỗ có số liệu ứng viên.
   Chỉ thêm một lời gọi, không đổi logic tìm kiếm.
6. Thêm kwargs cho `itinerary_build` tại `trip_planner.py:2087`.
7. Cập nhật `docs/chat_api_contract.md`: bảng phase key → field dữ kiện, ghi rõ **mọi field
   đều tuỳ chọn** và client phải chịu được thiếu.
8. Test:
   - `phase_facts` với `update` thật của `extract_patch` → đúng `intent` + `fields`
   - `update` rỗng / thiếu khoá → trả `{}`, không raise
   - node không có nhánh → `{}`
   - `update` chứa field ngoài whitelist → **không** lọt ra
   - `hotel_search` phát đúng `found`/`kept`
   - lượt POST không streaming → không phát gì
9. `pytest backend/tests/test_phase_facts.py backend/tests/test_stream_modes.py`.

## Success Criteria

- [x] Hình dạng `update` từng node đã được **quan sát thật**, bảng 11 node trong docstring `phase_facts.py`
- [x] `intake_check` chở `intent` + `fields[]`, có test
- [~] `hotel_search` chở `kept` + `status` + `destination`/`radius_km`/`amenities`. **`found` bị bỏ** — xem ghi chú
- [x] Field ngoài whitelist không lọt ra — 4 test riêng
- [x] Không dữ kiện → không gửi field, có test
- [x] Lỗi trong bộ rút không giết chat turn — có test extractor tự nổ
- [x] `docs/chat_api_contract.md` khớp code — thêm bảng field, sửa 1 ví dụ cũ
- [x] Frame `phase` cũ vẫn hợp lệ — có test `compacting_history` không dữ kiện
- [x] `test_stream_modes.py` xanh; toàn suite 961 pass

## Risk Assessment

| Rủi ro | Giảm thiểu |
|---|---|
| Hình dạng state khác giả định | Bước 2 quan sát thật trước khi viết — không bỏ qua |
| Rút field làm vỡ chat turn | Nằm trong vùng never-raise của `emit_phase`; có test |
| Dữ kiện nhạy cảm lọt client | Whitelist tường minh + test khẳng định field lạ bị chặn |
| Đụng `hotel_node` gây regression tìm kiếm | Chỉ thêm một lời gọi emit, không đổi logic; chạy test hotel hiện có |
| Số `found`/`kept` không tồn tại ở nơi tưởng | Bước 5 xác minh biến thật; nếu không có, ghi lại và bỏ field đó thay vì tính lại |

## Kết quả và ba chỗ lệch plan

### 1. Quan sát bác bỏ hai giả định (bước 2 đã cứu)

| | plan giả định | thực tế đo được |
|---|---|---|
| `update` luôn là dict | ngầm định | `scope_guard` trả **`None`** |
| `supervisor` chỉ có `next_worker` | — | còn có `task_description` + `routing_reasoning`, **là văn xuôi LLM viết** |

Cái thứ hai nguy hiểm: nếu bộ rút được viết theo kiểu "lấy hết trừ vài field", nó đã
đẩy chữ do backend sinh ra lên dây — đúng thứ nguyên tắc `phase-labels.ts` cấm. Whitelist
mặc-định-từ-chối là lý do nó không xảy ra.

`load_context` cũng có phase key và trả **22 khoá gồm cả `response` hoàn chỉnh**. Nó phát
`{}`, và có test riêng cho điều đó.

### 2. `hotel_search` suýt hiện hai dòng — thiết kế phải đổi

Plan bảo "thêm `emit_phase("hotel_search", …)` trong `hotel_node`". Nhưng `hotel_node`
**đang** nằm trong `PHASE_KEY_BY_NODE`, nên drain cũng phát key đó → hai frame.

`phase_keys.py:15-18` đã ghi sẵn hậu quả: *"frontend keys its progress rows by
`${key}-${at}`, so the user would see the same step listed twice"* — và tiền lệ có sẵn:
`itinerary_node` bị **bỏ khỏi map** vì chính lý do này.

Nên làm theo tiền lệ: bỏ `hotel_node` khỏi `PHASE_KEY_BY_NODE`, và đặt emit vào
`_result` — closure mà **mọi** đường thoát (6 đường) đều đi qua. Một call site, không đổi
logic, mọi nhánh đều báo cáo. Test `test_hotel_search_is_emitted_exactly_once` khoá lại.

### 3. `found` bị bỏ, không tính lại

`found` (số ứng viên trước khi cắt hiển thị) không với tới được từ `_result`. Theo đúng
dòng giảm thiểu rủi ro của chính plan — *"nếu không có, ghi lại và bỏ field đó thay vì
tính lại"* — nó không được báo cáo. `kept` lấy từ `hotel_search_result["options"]` đã có sẵn.

Thay vào đó thêm `status` (`ok` / `no_results` / `error` / …), thứ plan không nghĩ tới
nhưng hữu ích hơn cho một dòng tiến độ: nó phân biệt "tìm xong không có" với "tìm lỗi".

### 4. `itinerary_build` chưa thêm kwargs

`trip_planner.py:2087` nằm ở **đầu** `_generate_and_save_itinerary`, trước khi lịch trình
được dựng — `days[]` và `locked_days[]` mà plan muốn chưa tồn tại ở đó. `action` thì chỉ
có một giá trị nên không phải dữ kiện. Bỏ qua thay vì bịa; nếu Phase 3/4 thấy thiếu, chỗ
đúng để lấy là `itinerary_node` chứ không phải điểm vào này.

### 5. Hai chỗ tài liệu cũ đã sửa nhân tiện

`docs/chat_api_contract.md` và docstring `emit_phase` đều nêu ví dụ extras `tool=` /
`route=`. Không có call site nào từng phát hai field đó — chỉ `routing_legs` dùng `days=`.
Đã sửa cả hai cho khớp code.
