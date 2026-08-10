# Design audit — toàn bộ phase frontend (5-10) ↔ `trip_planner_components`

Đối chiếu `plans/260805-1022-claude-design-ui-integration/plan.md` + phase 5-10 với
`data/trip_planner/trip_planner_components/` (16 file `*.dc.html` + `styles/*.css`).

**Kết luận:** phần lớn plan bám design đúng và các quyết định "không bịa dữ liệu" đều có căn
cứ. Lệch nằm ở ba nhóm: (1) năm vùng UI của design bị bỏ **im lặng** — không có nguồn dữ liệu
và cũng không được ghi vào bảng "Phần chưa làm"; (2) một quyết định luồng chọn khách sạn mà
plan không nhận ra là design làm khác; (3) hai tiêu chí hoàn thành của Phase 10 tự mâu thuẫn
với chính phần kiến trúc của nó.

---

## 1. Bị bỏ im lặng — đã bổ sung vào bảng "Phần chưa làm"

Mỗi mục dưới đây design **có**, dữ liệu **không có**, và plan trước đây **không nói gì** —
tức là người implement sẽ hoặc bịa nó, hoặc phát hiện lúc đang code.

| # mới | Vùng design | File | Vì sao không có nguồn |
|---|---|---|---|
| 17 | "Đánh giá nổi bật" của **khách sạn** | `HotelDetail.dc.html` §`topReviews` | `hotels` select chỉ có `review_score`+`review_count` (`hotel_selection.py:50`). Mục 6 cũ chỉ ghi cho *địa điểm* |
| 18 | Khối "Liên hệ" khách sạn | `HotelDetail.dc.html` §`contact` | Không có cột phone/email/website; `GET /hotels/{id}` không định nghĩa |
| 19 | "cách trung tâm X" (card **và** hero) | `HotelCard`, `HotelDetail` | Không có `distance_to_center`, và **không có toạ độ tâm** của từng điểm đến. Tự chọn tâm rồi haversine = bịa |
| 20 | Khối "Tiện ích" của **địa điểm** | `PlaceDetail.dc.html` §`facilities` | `attractions` không có cột tiện ích. Tiện nghi là dữ liệu khách sạn |
| 21 | Chính sách huỷ/thanh toán phòng + ô "Phòng đã chọn" | `RoomCard` §`cancel`/`pay`, `HotelDetail` §`roomChosen` | Không có cột chính sách. Ô "Phòng đã chọn" là hệ quả mục 4 |

Mục 19 đáng chú ý nhất: nó xuất hiện **hai chỗ** trong design và trông rất giống dữ liệu thật,
nên là chỗ dễ bịa nhất trong cả bản redesign.

---

## 2. Luồng chọn khách sạn: design làm hai bước, plan giả định một bước

Design (`V-OTA Planner.dc.html:167`, `:1490-1493`):

1. Bấm "Chọn" trên card → chỉ đánh dấu cục bộ (`s.hotel`)
2. Nút **"Tạo lịch trình từ khách sạn này"** ở header stage mới là hành động xác nhận
3. Badge header đổi theo trạng thái: chưa chọn → "Chọn một khách sạn để xem khoảng cách tới
   các điểm nổi bật"; đã chọn → "*Tên* — điểm xuất phát & kết thúc mỗi ngày"

Phase 8 viết: "Bấm chọn vẫn gửi `String(hotel.index)` như một tin nhắn thường" — một bước, và
đó cũng là hành vi đang chạy ở `hotel-option-card.tsx`.

**Cả hai đều không đụng wire protocol** — hai bước chỉ hoãn thời điểm gửi đúng chuỗi đó.
Đây là quyết định sản phẩm, không phải ràng buộc kỹ thuật → đã ghi vào Phase 8 là **chưa chốt,
hỏi trước khi implement bước 4**.

---

## 3. Phase 10 tự mâu thuẫn — đã sửa

| Dòng | Trước | Sau |
|---|---|---|
| Tiêu chí tile | "tile **OSM** và attribution đầy đủ" | "tile **Mapbox raster** và attribution Mapbox + OSM" |
| Tiêu chí legend | "chỉ có **một** nhãn phương tiện (ô tô)" | "ô tô + đi bộ khi dữ liệu có, cộng mục ước lượng; không có cáp treo" |

Cả hai là tàn dư của bản nháp trước khi có Phase 12 (Mapbox thay OSRM, và `walking` trở thành
profile thật). Phần kiến trúc của chính Phase 10 đã nói đúng; chỉ tiêu chí hoàn thành còn cũ —
và tiêu chí mới là thứ người implement dùng để tự nghiệm thu, nên mâu thuẫn này có thật.

---

## 4. Vùng design **làm được** nhưng plan chưa nêu nguồn — đã bổ sung

Không phải lệch quyết định, mà là chỗ plan mô tả quá gọn nên dễ implement sai:

- **Badge tình trạng phòng** → ánh xạ `price.sold_out`. `price: null` thì **không hiện badge**.
- **`distToSights`** → `nearby_attractions` jsonb. **Shape chưa xác nhận** — Phase 3 bước 7 phải
  báo cáo nó có `km`/`mins` hay chỉ có tên. Nếu chỉ có tên thì render tên, không tự tính km.
- **Giá "tổng"** trên hotel card → cần số đêm từ `intake.start_date`/`end_date`. Thiếu ngày thì
  chỉ hiện giá mỗi đêm.
- **Badge hero `PlaceDetail`** ("Ngày N · giờ") → **không** từ `GET /attractions/{id}`; là ngữ
  cảnh timeline, phải truyền `{ dayNumber, startTime }` vào panel.
- **`det.route`** (3 ô di chuyển ở panel địa điểm) → `route_to_next` của item liền trước; item
  đầu ngày hoặc route null thì ẩn cả hàng.
- **Màu ngày** của `DayCard` và của route trên map phải dùng chung `lib/map-colors.ts`, nếu
  không hai chỗ sẽ trôi dạt khác màu cho cùng một ngày.
- **Nút "Chia sẻ"** ở header workspace: design có nút, **không có hành vi**. Không ship nút bấm
  vào không làm gì.

---

## 5. Traceability

Mọi phase frontend đang trích dẫn `V-OTA Planner.dc.html:NNN` — đếm dòng trong file monolith
2613 dòng ở `data/design/`. Bản `trip_planner_components/` là **cùng design đã tách component**
(đã verify: markup và token trùng khớp), dễ đối chiếu hơn nhiều.

Đã thêm bảng ánh xạ "vùng UI → file component → phase" vào `plan.md` §Tổng quan. Các tham
chiếu dòng cũ vẫn đúng và được giữ lại.

---

## Phần plan bám design đúng — không cần sửa

- Phase 7: từ chối danh sách 6 bước có tick tuần tự — đúng, backend không phát tiến độ theo bước.
- Phase 9: thay card "Cập nhật / Giữ kết quả" bằng `adjustments[]` — đúng, backend không phát diff.
- Phase 10: từ chối nhãn cáp treo — đúng, Mapbox không có profile đó.
- Phase 4 + `conversation-list.tsx`: nút xoá hội thoại của `HistoryRow.dc.html` **đã có** endpoint
  `DELETE /chat/{session_id}` và đã implement. Không phải lỗ hổng.
- Bốn trạng thái leg pill của Phase 9 (ô tô / đi bộ / trùng toạ độ / null) — phân biệt đúng và
  chặt hơn design.

## File đã sửa

- `plan.md` — thêm §"Nguồn design chuẩn để đối chiếu" + 5 dòng register (17-21)
- `phase-08-fe-stage-hotels-focus.md` — §"Đối chiếu design", 4 tiêu chí mới
- `phase-09-fe-stage-workspace-focus.md` — §"Đối chiếu design", 6 tiêu chí mới
- `phase-10-fe-map.md` — sửa 2 tiêu chí mâu thuẫn, thêm §thẻ chú thích map

## Quyết định đã chốt (06/08/2026)

1. **Chọn khách sạn: hai bước** theo design. Bấm card chỉ đánh dấu `selectedIndex`; nút
   "Tạo lịch trình từ khách sạn này" ở header stage là chỗ **duy nhất** gửi
   `String(hotel.index)`. Wire value giống hệt — chỉ hoãn thời điểm gửi. Đây là **đổi hành vi**
   so với code hiện tại, đã ghi vào Phase 8 (§Chọn khách sạn, bước 4/4b, 4 tiêu chí) và Phase 11
   (kịch bản hồi quy giờ kiểm tra cả ba đường: card+xác nhận, chip, gõ số).
2. **Bỏ nút "Chia sẻ"** ở header workspace. Ghi mục 22 bảng "Phần chưa làm"; Phase 9 header
   chỉ còn nút "Tạo lại".

3. **`nearby_attractions` shape đã xác nhận** — `{name, category, coordinates, distance_km,
   distance_text}`. Có khoảng cách, **không có thời lượng**. Hệ quả: `distToSights` render hai
   cột thay vì ba (mục 23 mới), và km phải format từ `distance_km` chứ **không** dùng
   `distance_text` — đó là chuỗi VI đã format sẵn trong DB (`"4,81 km"`), sẽ rò tiếng Việt vào
   UI tiếng Anh đúng như `intake.people` đang bị. Đã ghi vào `plan.md` §contract, `phase-03`
   §`GET /hotels/{id}`, và `phase-08`.

## Câu hỏi chưa giải quyết

Không còn.
