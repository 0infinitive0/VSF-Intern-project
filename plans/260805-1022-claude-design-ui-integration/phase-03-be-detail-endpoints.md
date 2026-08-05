---
phase: 3
title: "[BE] Endpoint chi tiết khách sạn & địa điểm"
status: pending
priority: P1
effort: "1.5-2 ngày"
dependencies: [1]
track: backend
---

# Phase 3: [BE] Endpoint chi tiết khách sạn & địa điểm

## Tổng quan

Thêm hai endpoint chỉ-đọc làm nền cho Hotel Detail Focus Mode và Place Detail Focus Mode
trong design. Cả hai đọc từ bảng đã tồn tại và đã có dữ liệu; không đụng vào chat graph,
session hay bất kỳ state nào của agent.

Đây là hai đường đọc **mới thật sự** duy nhất trong plan. Mọi thứ chúng trả về đều là nội
dung thật trong DB.

## Yêu cầu

**Chức năng**
- `GET /api/v1/hotels/{hotel_id}` trả dòng khách sạn + danh sách phòng + giá từng phòng cho
  kỳ nghỉ, đúng contract Phase 1
- `GET /api/v1/attractions/{attraction_id}` trả dòng địa điểm đúng contract
- ID không tồn tại → `404` kèm `detail` dạng JSON, theo đúng quy ước endpoint hiện có
- ID sai định dạng (không phải UUID) → `422`, validation chuẩn FastAPI
- Cả hai độc lập với session: không `session_id`, không lock, không thay đổi state

**Phi chức năng**
- Chi tiết khách sạn resolve trong ≤ 3 query Supabase (hotel, rooms, room_prices)
- Giá phòng lọc theo khoảng ngày lưu trú khi caller truyền vào; nếu không thì lấy dòng giá
  mới nhất chưa `sold_out` của từng phòng
- Response cache được — không có nội dung riêng theo người dùng

## Kiến trúc

### Vì sao thêm hai endpoint này là an toàn

Router hiện tại (`backend/src/api/routes.py`) trộn các endpoint chat có phạm vi session với
tra cứu `registry` và lock theo session. Hai endpoint này **cố ý không dùng gì trong số
đó**. Chúng là đọc thuần qua đúng pattern `_get_supabase_client()` mà
`hotel_selection.py:30-36` đang dùng.

Đặt logic query vào module service mới, không đặt trong router — theo đúng quy ước
`services/` hiện có (`hotel_selection.py`, `itinerary_store.py`, …). Router chỉ là vỏ HTTP mỏng.

### `GET /api/v1/hotels/{hotel_id}`

Query param tuỳ chọn `check_in` / `check_out` (ngày ISO). Có thì lọc giá phòng theo khoảng
đó; không có thì lấy dòng giá `crawled_at` mới nhất của mỗi phòng mà chưa `sold_out`.

```
1. hotels      WHERE id = :hotel_id                         → 404 nếu rỗng
2. rooms       WHERE hotel_id = :hotel_id
3. room_prices WHERE room_id IN (…) [AND khoảng ngày]
```

Ghép: gắn tối đa **một** object `price` cho mỗi phòng; `null` nếu không có dòng nào khớp.
**Tuyệt đối không bịa giá bằng cách copy `hotels.lowest_price` xuống phòng** — đó là con số
cấp khách sạn, gán cho một loại phòng cụ thể là sai lệch.

Các field trả về đúng danh sách trong contract. `amenity_groups`, `category_scores`,
`nearby_attractions`, `nearby_essentials` là jsonb — truyền qua nguyên vẹn, để frontend
quyết định hiển thị gì. `awards` / `warnings` cũng trả luôn (rẻ, và đã ghi trong bảng
"Phần chưa làm" là có-sẵn-nhưng-chưa-dùng).

### `GET /api/v1/attractions/{attraction_id}`

Một query trên bảng `attractions`. Frontend resolve id từ
`trip_plan.days[].items[].reference_id` khi `reference_type == "attraction"`.

**Phải xác minh bộ giá trị `reference_type` trước khi code.** Mapper itinerary item trong
`trip_formatter.py` truyền thẳng `reference_type` từ item đã lưu; hãy kiểm tra giá trị thực
tế đang được lưu (`attraction`, `hotel`, `tour`, …) và ghi vào contract. Nếu item tham chiếu
sang bảng `tours` riêng thì hoặc thêm `GET /tours/{id}` song song, hoặc ghi vào bảng "Phần
chưa làm" — **không được** âm thầm trả 404 cho một item hợp lệ.

`opening_time` / `closing_time` là cột `time` — serialize thành chuỗi `"HH:MM:SS"`.
`ticket_price_adult` / `ticket_price_child` là numeric, có thể là `0` (miễn phí) hoặc `null`
(chưa rõ). **Hai giá trị này khác nhau và không được gộp** — frontend cần phân biệt
"miễn phí" với "chưa có thông tin".

## File liên quan

- Tạo: `backend/src/services/place_details.py` — query chi tiết khách sạn + địa điểm
- Sửa: `backend/src/api/routes.py` — hai route mới, mỏng
- Sửa: `backend/src/models/schemas.py` — `HotelDetailPayload`, `RoomDetailPayload`,
  `RoomPricePayload`, `AttractionDetailPayload`
- Tạo: `backend/tests/test_place_details.py`
- Sửa: `docs/chat_api_contract.md` — chỉ khi việc rà `reference_type` làm đổi contract

## Các bước thực hiện

1. Rà các giá trị `reference_type` thật đang được lưu trên itinerary item (query DB hoặc
   đọc phần ghi trong `trip_planner.py` / `itinerary_store.py`). Ghi bộ giá trị vào
   contract. Việc này quyết định một endpoint attraction có đủ hay không.
2. Định nghĩa 4 payload model trong `schemas.py`, mirror chính xác contract Phase 1. Mọi
   field đều optional trừ `id` và `name`.
3. Viết `place_details.py`:
   - `get_hotel_detail(hotel_id, check_in=None, check_out=None) -> dict | None`
   - `get_attraction_detail(attraction_id) -> dict | None`
   - cả hai trả `None` khi không tìm thấy; router biến `None` thành `404`
   - tái dùng pattern `_get_supabase_client()`; **log và ném lại** lỗi client thay vì nuốt
     nó thành kết quả rỗng (DB chết không được trông giống 404)
4. Thêm hai route. Theo đúng kiểu `HTTPException(status_code=404, detail=…)` mà
   `get_session_plan` đang dùng.
5. Helper chọn giá phòng: cho các dòng giá của một phòng và một khoảng ngày tuỳ chọn, chọn
   dòng khớp, nếu không thì dòng mới nhất chưa sold_out, nếu không nữa thì `None`.
6. Test: tìm thấy / không tìm thấy / id sai định dạng cho cả hai; khách sạn không có phòng;
   phòng không có dòng giá; địa điểm có `ticket_price_adult = 0` so với `null`; lỗi Supabase
   phải ra `500`, không phải `404`.
7. Kiểm tra tay trên dữ liệu seed: lấy một hotel id thật từ `pending_hotel_selection` và xác
   nhận response đủ dữ liệu để lấp đầy panel design. **Báo mức phủ field thực tế** (đặc biệt
   `images`, `nearby_attractions`, `check_in_time`) cho Dev F để frontend dựng empty state
   đúng với thực tế.

## Tiêu chí hoàn thành

- [ ] Cả hai endpoint trả đúng shape contract Phase 1
- [ ] `404` khi id không tồn tại, `422` khi id sai định dạng, `500` khi DB lỗi — ba đường phân biệt
- [ ] `price` của phòng là `null` khi không có dòng khớp; không bao giờ lấp bằng `hotels.lowest_price`
- [ ] `ticket_price = 0` và `ticket_price = null` vẫn phân biệt được trong response
- [ ] Đã rà và ghi lại bộ giá trị `reference_type`
- [ ] Không đụng đến session, lock hay state của agent
- [ ] Chi tiết khách sạn ≤ 3 query
- [ ] Test pass; đã bàn giao báo cáo mức phủ field cho Dev F

## Đánh giá rủi ro

**`reference_type` có thể không phải `"attraction"`.** Nếu itinerary item tham chiếu tour
hoặc hoạt động dạng text tự do thì một số card địa điểm sẽ không có gì để mở. Giảm thiểu:
bước rà ở mục 1 làm **trước tiên**; frontend phải coi "không có reference_id" là trạng thái
hợp lệ và đơn giản là không cho mở focus mode với item đó (Phase 9 xử lý).

**Khoảng ngày của `room_prices` có thể không khớp kỳ nghỉ.** Bảng này được crawl theo từng
khoảng ngày và có thể không có gì cho ngày người dùng chọn. Contract đã cho phép
`price: null`; frontend phải hiển thị "giá theo yêu cầu" chứ không phải số 0.

**Lỗi DB đội lốt 404.** `_hydrate_hotel_records` hiện đang nuốt exception và trả `[]`
(`hotel_selection.py:57-60`). **Đừng copy pattern đó ở đây** — một lỗi bị nuốt sẽ render ra
panel chi tiết rỗng trông y như dữ liệu thật.
