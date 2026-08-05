---
phase: 2
title: "[BE] Mở rộng payload khách sạn & route"
status: pending
priority: P1
effort: "1-1.5 ngày"
dependencies: [1]
track: backend
---

# Phase 2: [BE] Mở rộng payload khách sạn & route

## Tổng quan

Ngừng vứt bỏ dữ liệu backend đã tính sẵn. Có **hai** chỗ đang bị cắt bỏ theo đúng cùng một
kiểu:

1. `hotel_selection.py` đã select ảnh, tiện nghi, điểm đánh giá, địa chỉ, toạ độ từ Supabase
   và đã tính điểm relevance thật để xếp hạng — rồi `to_hotel_options_payload` vứt hết, chỉ
   trả 7 field.
2. `recalculate_itinerary_routes` (`routing.py:93`) đã gọi routing API và gắn
   `route_to_next = {distance_km, duration_mins, polyline}` lên từng itinerary item — rồi
   `to_trip_plan_payload` không copy sang payload.

Phase này mở rộng cả hai đúng theo contract Phase 1.

Đây là thay đổi backend nhỏ nhất nhưng đòn bẩy lớn nhất trong plan: chỉ riêng nó đã mở khoá
card khách sạn theo design (ảnh, tiện nghi, điểm đánh giá, vòng match) **và** route bám
đường thật trên map, mà **không thêm một query hay một lời gọi routing nào**.

## Yêu cầu

**Chức năng**
- `to_hotel_options_payload` trả về đủ mọi field trong contract Phase 1
- `rank_hotel_candidates` gắn điểm composite đã tính vào từng option dict để nó sống sót
  vào payload thay vì bị bỏ đi sau khi sort
- `match_reasons` chỉ phát ra **mã + giá trị thô**, tuyệt đối không phải câu chữ hiển thị
- Field không có trong DB thì serialize thành `null` / `[]`, không bao giờ là giá trị bịa

**Phi chức năng**
- Không thêm round-trip Supabase nào — mọi thứ lấy từ dòng đã fetch
- Consumer cũ vẫn chạy: `suggestions[i].value` vẫn phải bằng `str(index)`, và cơ chế match
  theo số thứ tự của `select_hotel` không đổi

## Kiến trúc

### Dữ liệu đã nằm sẵn ở đâu

`_hydrate_hotel_records` (`hotel_selection.py:39-66`) select:

```
id, destination_id, name, star_rating, description, coordinates, amenities,
amenity_groups, review_score, review_count, address, area_name,
lowest_price, currency, image_url
```

và `select_hotel_candidates` copy phần lớn sang từng option dict
(`hotel_selection.py:139-157`). Nghĩa là `pending_hotel_selection["options"][i]`
**đã chứa sẵn** coordinates, review_score, review_count, address, amenities, lowest_price.
`to_hotel_options_payload` (vòng `for index, option in enumerate(...)` trong
`trip_formatter.py`) đơn giản là không copy chúng qua.

Hai field design cần mà **chưa** có trong danh sách select, phải bổ sung: `images` (mảng
gallery — `image_url` chỉ là một ảnh) và `city`.

### Match score

`_composite_score` (`hotel_selection.py:172-182`) đã tính một điểm relevance 0..1 thật:
`0.55·similarity + 0.20·rating + 0.15·review + 0.10·price`, cộng thêm bonus độ khớp ngân
sách và tiện nghi (`_budget_bonus`, `_amenity_bonus`, tối đa +0.20). `rank_hotel_candidates`
dùng nó để sort rồi vứt đi.

Thay đổi: cho `_final_score` ghi kết quả và các thành phần ngược lại vào option dict:

```python
data["match_score"] = round(min(1.0, final), 4)
data["match_reasons"] = _match_reasons(data, candidate, target_price, amenity_prefs)
```

`_match_reasons` là hàm thuần mới, chỉ trả mã và giá trị thô:

| Mã | Phát ra khi | `value` |
|---|---|---|
| `budget_fit` | `_budget_bonus` > 0 | tỉ lệ giá/mục tiêu, đã làm tròn |
| `high_rating` | `review_score >= 8.0` | điểm đánh giá |
| `star_rating` | `star_rating >= 4` | số sao |
| `amenity_match` | có tiện nghi khớp sở thích | chuỗi tiện nghi đã khớp |
| `strong_similarity` | `similarity >= 0.75` | độ tương đồng |
| `near_center` | có `area_name` và thuộc khu trung tâm | tên khu vực |

Frontend sở hữu toàn bộ câu chữ; backend chỉ sở hữu dữ kiện. Đây chính là điều giữ cho
panel "AI đề xuất vì..." trung thực, đồng thời đúng nguyên tắc i18n không hardcode chuỗi.

**`match_score` là điểm relevance, không phải xác suất hài lòng.** UI phải gọi nó là điểm
khớp/độ phù hợp (chữ "MATCH" trong design vốn đã đúng).

### Route trên itinerary item

`to_trip_plan_payload` (`trip_formatter.py`) dựng mỗi item với đúng 8 field và bỏ qua route
đã được `recalculate_itinerary_routes` gắn lên. Bổ sung `route_to_next` và `route_from_hotel`
vào mapper item.

Không cần đổi gì trong `routing.py` (Phase 12 mới sửa file đó). Không phát sinh lời gọi
routing mới — route đã được tính
lúc `persist_itinerary_bundle` chạy (`itinerary_store.py:215-219`) và đã nằm sẵn trên item.

Ba điểm phải giữ đúng nguyên trạng, **không "dọn dẹp"**:

- **`{0.0, 0.0, ""}` không phải `null`.** Khi hai điểm trùng toạ độ, `get_route_to_next` trả
  object với số 0 (`routing.py:84-89`). Đây là "cùng chỗ, không cần di chuyển" — khác hẳn
  `null` nghĩa là "không có dữ liệu route". **Truyền qua nguyên vẹn**, đừng chuẩn hoá thành
  `null`; frontend cần phân biệt hai trạng thái này.
- **`profile` phải được truyền qua.** Phase 12 bổ sung khoá này vào `route_to_next`
  (`driving-traffic` / `walking` / `cycling`). Mapper phải copy nó — nếu thiếu, frontend
  không dựng được nhãn phương tiện. Phase 2 và 12 chạy song song, nên viết mapper theo kiểu
  copy nguyên object `route_to_next` thay vì liệt kê từng khoá; như vậy không phụ thuộc thứ
  tự hai phase land.
- **`route_from_hotel` thường là `null` sau round-trip DB.** `ITEM_RPC_FIELDS`
  (`itinerary_store.py:47-60`) không chứa nó nên nó bị lọc trước khi persist. Mapper vẫn phải
  copy nó khi có (đường in-memory), và contract khai báo nullable. Đây là mục 15 bảng "Phần
  chưa làm" — **không sửa trong phase này** vì cần đụng RPC/migration phía DB.

## File liên quan

- Sửa: `backend/src/services/hotel_selection.py`
  - `_hydrate_hotel_records` — thêm `images`, `city` vào danh sách `select(...)`
  - `select_hotel_candidates` — copy field mới sang option dict
  - `rank_hotel_candidates` / `_final_score` — lưu `match_score`, thêm `_match_reasons`
- Sửa: `backend/src/services/trip_formatter.py` — mở rộng `to_hotel_options_payload`
  **và** mapper item trong `to_trip_plan_payload` (thêm `route_to_next`, `route_from_hotel`)
- Sửa: `backend/src/models/schemas.py` — thêm field mới vào `HotelOption`; thêm
  `RouteInfoPayload` và gắn vào `ItineraryItem`
- Sửa: `backend/tests/**` — phủ payload mở rộng, việc lưu điểm, và route pass-through
- **Không đổi:** `backend/src/services/routing.py` — chỉ đọc kết quả của nó

## Các bước thực hiện

1. Thêm `images`, `city` vào chuỗi `select(...)` trong `_hydrate_hotel_records`.
2. Copy các field mới trong `select_hotel_candidates` (và ở đoạn mapping song song quanh
   `hotel_selection.py:329-342` — **có hai chỗ dựng option dict**, phải sửa cả hai, nếu
   không payload sẽ khác nhau giữa luồng tìm kiếm và luồng chọn lại).
3. Thêm `_match_reasons(data, candidate, target_price, amenity_prefs) -> list[dict]`.
4. Trong `_final_score`, ghi `match_score` và `match_reasons` vào option dict trước khi
   trả về điểm. Giữ hành vi sort **y hệt từng byte**.
5. Mở rộng `HotelOption` trong `schemas.py` với các field optional mới.
6. Mở rộng `to_hotel_options_payload` để copy chúng. Giữ kiểu "bỏ qua khi None" hiện có cho
   các field giá; dùng `null`/`[]` cho field mới để shape ổn định.
7. Test: assert shape payload mở rộng; assert `match_score` ∈ [0,1]; assert
   `suggestions[i].value == str(options[i].index)` vẫn đúng; assert một dòng khách sạn
   thiếu `images`/`review_score` cho ra `[]`/`null` chứ không crash và không có giá trị mặc định bịa.
8. Kiểm chứng trên DB thật xem `images` có dữ liệu cho các khách sạn đã seed không — nếu
   phần lớn rỗng thì **báo lại trong phase report** để frontend giữ nguyên đường placeholder.
9. Thêm `RouteInfoPayload` vào `schemas.py`, gắn `route_to_next` / `route_from_hotel` vào
   `ItineraryItem`, và copy chúng trong mapper item của `to_trip_plan_payload`.
10. Test route pass-through:
    - item có route → payload giữ nguyên `distance_km`, `duration_mins`, `polyline`
    - hai điểm trùng toạ độ → payload giữ `{0.0, 0.0, ""}`, **không** bị chuẩn hoá thành `null`
    - item không có route → `null`
    - chuỗi `polyline` không bị escape hay cắt ngắn
11. Kiểm chứng thật: chạy một chuyến rồi xác nhận `trip_plan.days[].items[].route_to_next`
    có mặt trong response HTTP. **Báo lại tỉ lệ item có route** — nếu routing API bị
    rate-limit lúc seed thì phần lớn sẽ `null` và Dev F cần biết để test đường fallback.

## Tiêu chí hoàn thành

- [ ] `hotel_options[]` khớp chính xác contract Phase 1
- [ ] Có `match_score` trong [0,1]; `match_reasons` là mã + giá trị, không có câu chữ
- [ ] Cả hai chỗ dựng option dict trong `hotel_selection.py` phát ra shape giống hệt nhau
- [ ] `route_to_next` / `route_from_hotel` có mặt trong `trip_plan` payload
- [ ] `{0.0, 0.0, ""}` (trùng toạ độ) khác biệt rõ với `null` (không có route)
- [ ] Mapper copy nguyên object `route_to_next` (gồm cả `profile` từ Phase 12), không liệt kê từng khoá
- [ ] `routing.py` không bị sửa trong phase này (Phase 12 mới là phase sửa nó)
- [ ] Không phát sinh query Supabase nào thêm mỗi lượt chat
- [ ] Chọn theo số thứ tự (`select_hotel`) và sự khớp với `suggestions` không đổi
- [ ] Field thiếu trong DB xuống cấp thành `null`/`[]`, không bao giờ thành giá trị bịa
- [ ] Đã báo tỉ lệ item có route thật cho Dev F
- [ ] Test suite backend pass

## Đánh giá rủi ro

**Hai chỗ dựng option dict khác nhau.** `hotel_selection.py` dựng option dict ở hai nơi
(tìm kiếm ~:139, chọn lại ~:329). Chỉ sửa một chỗ sẽ tạo payload khác nhau âm thầm theo
đường code. Giảm thiểu: tách một helper `_build_option_dict` duy nhất dùng cho cả hai, và
thêm test chạy qua cả hai đường.

**`images[]` có thể rỗng trong dữ liệu seed.** Không phải blocker — frontend vẫn cần đường
placeholder dù sao (URL ngoài có thể 404). Báo mức độ phủ thực tế cho Dev F.

**Kích thước payload.** `amenity_groups` và `category_scores` là blob jsonb có thể rất lớn;
chúng bị **cố ý loại** khỏi `hotel_options[]` và chỉ có ở endpoint chi tiết (Phase 3).
Giữ nguyên như vậy — payload danh sách mang N khách sạn mỗi lượt.
