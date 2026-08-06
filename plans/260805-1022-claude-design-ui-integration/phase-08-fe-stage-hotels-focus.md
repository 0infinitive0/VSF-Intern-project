---
phase: 8
title: "[FE] Stage: Khách sạn & Hotel Detail Focus Mode"
status: pending
priority: P1
effort: "2.5-3 ngày"
dependencies: [5]
track: frontend
---

# Phase 8: [FE] Stage: Khách sạn & Hotel Detail Focus Mode

## Tổng quan

Dựng màn hình đề xuất khách sạn dạng split view và Hotel Detail Focus Mode — một trong hai
tính năng đinh của bản design. Tiêu thụ `hotel_options[]` đã mở rộng (Phase 2) và
`GET /hotels/{id}` (Phase 3), cả hai đã có fixture mock từ Phase 1.

Ảnh tham chiếu: `data/design/screenshots/hotel-focus.png`.

## Yêu cầu

**Chức năng**
- Danh sách card khách sạn dạng premium glass: ảnh, tên, sao, điểm đánh giá, giá, khoảng
  cách/khu vực, tiện nghi nổi bật, vòng AI Match Score, lý do đề xuất, nút chọn
- Hover card → highlight marker trên map; hover marker → highlight card (nối ở Phase 10)
- Card đã chọn có trạng thái selected rõ ràng
- Nút "Xem chi tiết" và click vào card → mở Hotel Detail Focus Mode
- Focus mode: chat + map thu gọn, danh sách khách sạn mở rộng sang trái, panel chi tiết bên phải
- Đang focus vẫn chọn được khách sạn khác trong danh sách; chỉ panel chi tiết đổi, **không**
  đóng focus mode
- Panel chi tiết: hero image, gallery, thông tin, tiện nghi, chính sách nhận/trả phòng,
  địa điểm lân cận, danh sách phòng (mở rộng được)
- Nút đóng (✕) trả layout về nguyên trạng, **không mất state nào**

**Phi chức năng**
- Vị trí cuộn của danh sách được giữ khi vào/ra focus mode
- Mọi ô ảnh có placeholder dự phòng khi URL 404
- Panel chi tiết fetch một lần cho mỗi khách sạn và cache trong phiên

## Kiến trúc

### Chọn khách sạn — không đổi verb

Hành động chốt khách sạn vẫn là gửi `String(hotel.index)` như một tin nhắn thường, đúng chuỗi
mà `hotel-option-card.tsx:97` đang gửi. **Không có endpoint mới, không có verb mới.**

Cái **đổi** là thời điểm gửi: xem §"Chọn khách sạn: hai bước (đã chốt)" bên dưới — bấm card
chỉ đánh dấu cục bộ, nút xác nhận ở header stage mới gửi. Byte gửi lên backend giống hệt.

### Vòng AI Match Score

`match_score` là số thật 0..1 từ ranking backend (Phase 2). Render dưới dạng vòng tròn
tiến độ với phần trăm, đúng như design.

**Nhãn phải nói đúng bản chất**: đây là điểm phù hợp/độ khớp, không phải xác suất hài lòng
hay điểm chất lượng. Chữ "MATCH" trong design đã đúng — giữ nguyên tinh thần đó khi dịch
sang tiếng Việt ("ĐỘ KHỚP").

Khi `match_score` vắng mặt (backend chưa lên Phase 2), **không render vòng tròn** — không
hiển thị 0% hay giá trị mặc định.

### Lý do đề xuất

`match_reasons[]` là mảng `{ code, value }`. Frontend dựng câu từ catalog i18n:

```ts
// vi.json
"matchReason.budget_fit": "Vừa đúng {{value}}% ngân sách dành cho khách sạn",
"matchReason.high_rating": "Điểm đánh giá {{value}}/10 từ khách đã ở",
"matchReason.amenity_match": "Có {{value}} như bạn mong muốn",
"matchReason.star_rating": "Khách sạn {{value}} sao",
"matchReason.strong_similarity": "Khớp với mô tả chuyến đi của bạn",
"matchReason.near_center": "Nằm ở {{value}}, gần trung tâm"
```

Mã lạ (backend thêm mã mới mà frontend chưa biết) thì **bỏ qua im lặng**, không render chuỗi
thô. Đây là điều giữ cho contract tiến hoá được mà không vỡ UI.

### Hotel Detail Focus Mode

Trạng thái do `use-focus-mode` (Phase 5) sở hữu. Luồng:

```
click card / nút "Xem chi tiết" / marker trên map
  → setFocus({ kind: 'hotel', id })
  → app-shell transform: chat translateX(-100%), map thu về 0
  → danh sách khách sạn mở rộng chiếm chỗ chat
  → panel chi tiết vào từ phải (vRise + hero reveal)
  → fetch GET /hotels/{id} (cache theo id)
```

Đóng thì đảo ngược transform. **Không unmount chat, không unmount map, không reset dữ liệu,
không tải lại danh sách khách sạn** — đây là yêu cầu tường minh của `Hotel Detail Focus.md`
§Navigation và §State Preservation.

Giữ vị trí cuộn: lưu `scrollTop` của container danh sách khi vào focus, khôi phục khi ra.

### Danh sách phòng

Từ `GET /hotels/{id}` → `rooms[]`. Mỗi card phòng: ảnh, tên, giá, diện tích, sức chứa, loại
giường, view, tiện nghi. Click thì **mở rộng tại chỗ** (accordion) để hiện thêm ảnh, mô tả,
tiện nghi đầy đủ — không mở màn hình mới, không popup, đúng như `Hotel Detail Focus.md`
§Room Detail.

**Không có nút "Chọn phòng"** — backend không có verb chọn phòng. Đã ghi ở mục 4 bảng "Phần
chưa làm". Card phòng là chỉ đọc.

Khi `room.price` là `null` (không có dòng `room_prices` khớp khoảng ngày) thì hiển thị nhãn
"giá theo yêu cầu" đã dịch, **không** hiển thị 0 và **không** mượn giá cấp khách sạn.

### Xử lý ảnh

`images[]` và `image_url` là URL ngoài, có thể 404 hoặc rỗng. Cần một component ảnh dùng
chung:

- đang tải → khối shimmer
- lỗi / rỗng → placeholder icon Material trung tính trong khung đúng tỉ lệ (đúng tiền lệ
  hiện có ở `hotel-option-card.tsx:44-48`)
- thành công → ảnh, `object-cover`, có `alt` mô tả

Đây là component sẽ dùng lại ở Phase 9 cho ảnh địa điểm.

## Đối chiếu design (rà 06/08/2026)

File đối chiếu: `data/trip_planner/trip_planner_components/HotelCard.dc.html`,
`HotelDetail.dc.html`, `RoomCard.dc.html`, và khối stage khách sạn ở
`trip_planner_components/V-OTA Planner.dc.html:157-190`.

### Chọn khách sạn: hai bước (đã chốt)

**Quyết định của người dùng, 06/08/2026: làm hai bước theo design.**

Đây là **thay đổi hành vi** so với hiện tại. `hotel-option-card.tsx` đang gửi
`String(hotel.index)` ngay khi bấm; sau phase này nó không gửi gì cả.

| Bước | Hành động | Gửi gì lên backend |
|---|---|---|
| 1 | Bấm nút "Chọn" trên card | **không gì cả** — chỉ set `selectedIndex` cục bộ |
| 2 | Bấm "Tạo lịch trình từ khách sạn này" ở header stage | `String(hotel.index)` của card đang chọn, qua đúng `onSend` như một tin nhắn thường |

**Wire protocol không đổi** — vẫn đúng chuỗi đó, đúng đường đi đó, chỉ hoãn thời điểm gửi.
Không có verb mới, không có endpoint mới.

Ba vùng bấm trên card là **ba việc khác nhau**, đúng như design (`HotelCard.dc.html`):
bấm **thân card** hoặc nút "Xem chi tiết" → mở focus mode; bấm nút **"Chọn"** → đánh dấu.
Nút "Chọn" phải `stopPropagation` để không mở luôn panel chi tiết.

Header stage (`V-OTA Planner.dc.html:160-168`) gồm:

- Nút xác nhận `L.buildFromHotel`: nền `--btn` khi đã chọn, `--fill2`/`--t4` khi chưa; **vô
  hiệu hoá khi chưa chọn** — không gửi tin nhắn rỗng.
- Badge trạng thái bên trái nút: chưa chọn → "Chọn một khách sạn để xem khoảng cách tới các
  điểm nổi bật"; đã chọn → "*Tên khách sạn* — điểm xuất phát & kết thúc mỗi ngày". Cả hai đều
  mô tả trạng thái thật, dịch qua i18n.

Hệ quả cần xử lý:

- `selectedIndex` giờ là state **có ý nghĩa với người dùng** (nó điều khiển nút xác nhận),
  không còn chỉ là phản hồi lạc quan. Vẫn không có khái niệm "đã chọn" phía server — nhưng
  bây giờ nó sống đủ lâu để người dùng mở chi tiết, so sánh, rồi mới chốt. Đó chính là giá
  trị của hai bước.
- Sau khi gửi, `hotel_options` bị xoá ở lượt kế tiếp như cũ; reset `selectedIndex` khi đó.
- Comment ở `hotel-option-card.tsx:112-115` (giải thích vì sao `selectedIndex` là tạm thời)
  phải viết lại cho khớp hành vi mới — đừng để lại lời giải thích của cơ chế cũ.

### Phần của design bị bỏ (đã ghi vào bảng "Phần chưa làm")

| Vùng design | Mục | Xử lý |
|---|---|---|
| `HotelDetail` §`topReviews` — card review có tên/thời điểm/nội dung | 17 | Bỏ. Chỉ hiện `review_score` + `review_count` |
| `HotelDetail` §`contact` — 2 ô liên hệ | 18 | Bỏ cả khối |
| "cách trung tâm X" trên card và hero | 19 | Thay bằng `area_name` thật |
| `HotelDetail` ô "Phòng đã chọn" | 21 | Bỏ — hệ quả của mục 4, không có verb chọn phòng |
| `RoomCard` 2 ô chính sách huỷ / thanh toán | 21 | Bỏ |
| `RoomCard` nút "Chọn phòng" | 4 | Bỏ — card phòng chỉ đọc |

### Phần của design **vẫn làm**, cần nêu rõ nguồn

- **Badge tình trạng phòng** (`r.avail`) — ánh xạ từ `price.sold_out` thật, không phải bịa.
  `sold_out: true` → nhãn "hết phòng"; `false` → "còn phòng"; `price: null` → **không hiện
  badge** (không biết tình trạng thì không tuyên bố).
- **`distToSights`** — nguồn là `nearby_attractions` từ `GET /hotels/{id}`. Shape đã xác nhận
  06/08/2026:

  ```jsonc
  { "name": "Sân bay Quốc tế Đà Nẵng (DAD)", "category": "Sân bay lân cận",
    "coordinates": "16.056327,108.200833", "distance_km": 4.81, "distance_text": "4,81 km" }
  ```

  Ba hệ quả:

  1. **Bỏ cột phút.** Design có ba cột (tên · km · phút) nhưng dữ liệu **không có thời lượng**.
     Không suy ra từ km — tốc độ di chuyển là thứ bịa. Render hai cột. Mục 23 bảng "Phần chưa làm".
  2. **Format km từ `distance_km` (số), không dùng `distance_text`.** `distance_text` là chuỗi
     tiếng Việt đã format sẵn trong DB (`"4,81 km"` — dấu phẩy thập phân) và sẽ hiện tiếng Việt
     kể cả khi UI đang tiếng Anh. Dùng `distance_km` qua `Intl.NumberFormat` như mọi con số
     khác. Đây đúng cái bẫy mà `intake.people` đã mắc phải (xem Phase 7).
  3. **`category` cũng là nhãn tiếng Việt của DB** — hiển thị được (nó là dữ liệu, không phải
     chuỗi UI), nhưng đừng đặt tiêu đề section là "địa điểm tham quan lân cận": danh sách này
     gồm cả sân bay và bến xe. Đặt tiêu đề trung tính, ví dụ "Khoảng cách tới các điểm chính".
- **Giá "tổng"** trên card (`mỗi đêm · {{ h.total }}`) — cần số đêm. Lấy từ
  `intake.start_date`/`end_date` (đã có ở `ChatState`), **không** từ hằng số. Thiếu một trong
  hai ngày → chỉ hiện giá mỗi đêm, bỏ phần tổng.

### Chi tiết trình bày dễ bỏ sót

- Card có **hai nút** ở đáy: "Chọn" (nền `--btn`/`--fill2` theo trạng thái) và "Xem chi tiết"
  (viền `--stroke`, nền `--g2`).
- Ảnh khách sạn 112×112 bo 20px, có overlay `vSheen` chạy vô hạn; card vào bằng `vFade` lệch
  pha theo `delay`; hover có ring + transform.
- Vòng match: `conic-gradient` 62px ngoài / 50px trong (card) và 58/46 (panel chi tiết).
- Panel chi tiết là **flex sibling thứ ba** (danh sách | map | chi tiết), không phải overlay —
  khớp với yêu cầu "không phải modal".

## File liên quan

- Tạo: `frontend/src/components/stage-hotels.tsx` — split view danh sách + chỗ cho map
- Tạo: `frontend/src/components/hotel-detail-panel.tsx` — panel focus mode
- Tạo: `frontend/src/components/room-card.tsx` — card phòng có accordion
- Tạo: `frontend/src/components/match-score-ring.tsx` — vòng tròn điểm khớp
- Tạo: `frontend/src/components/match-reasons.tsx` — bullet lý do đã dịch
- Tạo: `frontend/src/components/remote-image.tsx` — ảnh có placeholder dự phòng
- Tạo: `frontend/src/api/place-client.ts` — gọi `/hotels/{id}`, `/attractions/{id}`
- Tạo: `frontend/src/hooks/use-hotel-detail.ts` — fetch + cache theo id
- Sửa: `frontend/src/components/hotel-option-card.tsx` — restyle theo card design đầy đủ
- Sửa: `frontend/src/components/stage-router.tsx` — nối stage hotels
- Sửa: `frontend/src/i18n/locales/{en,vi}.json` — chuỗi khách sạn + mã `matchReason.*`

## Các bước thực hiện

1. `remote-image.tsx` với ba trạng thái (tải / lỗi / có ảnh). Làm trước vì mọi thứ khác dùng nó.
2. `match-score-ring.tsx` — vòng SVG, ẩn hoàn toàn khi `match_score` vắng mặt.
3. `match-reasons.tsx` — ánh xạ mã → khoá i18n, bỏ qua mã lạ.
4. Restyle `hotel-option-card.tsx` theo card design đầy đủ, và **đổi `onPick` thành đánh dấu
   cục bộ** (`selectedIndex`) thay vì gửi ngay — hai bước, xem §"Chọn khách sạn". Mọi field
   mới đều optional — card phải render đẹp cả khi backend chưa lên Phase 2.
4b. Header stage với nút xác nhận `buildFromHotel` (vô hiệu khi chưa chọn) + badge trạng thái.
   Nút này là **chỗ duy nhất** gửi `String(hotel.index)`. Ghi lại baseline chuỗi gửi trước và
   sau khi đổi, diff để chắc chắn byte giống hệt.
5. `stage-hotels.tsx` — split view; cột map để chỗ trống cho Phase 10 (dùng `MapPanel` hiện
   tại làm tạm).
6. `place-client.ts` + `use-hotel-detail.ts` với cache theo id và xử lý lỗi (404 → panel báo
   "không có thông tin chi tiết", không phải màn hình lỗi).
7. `room-card.tsx` — accordion mở tại chỗ, chỉ đọc, xử lý `price: null`.
8. `hotel-detail-panel.tsx` — hero, gallery, thông tin, tiện nghi, chính sách, lân cận, danh
   sách phòng, nút đóng. Mọi section vắng dữ liệu thì **ẩn cả section**, không hiện tiêu đề rỗng.
9. Nối vào `use-focus-mode`: mở/đóng/đổi khách sạn khi đang focus. Kiểm tra đổi khách sạn
   **không** đóng focus mode.
10. Lưu và khôi phục vị trí cuộn của danh sách quanh việc vào/ra focus.
11. Thêm chuỗi vào cả hai catalog.
12. Kiểm chứng trên mock: lượt 3 ra danh sách khách sạn có ảnh + match ring; mở focus, đổi
    sang khách sạn khác, đóng lại — chat và map trở về đúng chỗ, danh sách giữ nguyên cuộn.

## Tiêu chí hoàn thành

- [ ] Card khách sạn khớp design với dữ liệu thật (ảnh, tiện nghi, đánh giá, match score)
- [ ] Chốt khách sạn vẫn gửi `String(hotel.index)` byte giống hệt, không có verb mới
- [ ] Bấm card **không** gửi gì; chỉ nút xác nhận ở header gửi
- [ ] Nút xác nhận vô hiệu khi chưa chọn khách sạn nào
- [ ] Badge header đổi đúng theo trạng thái chọn; cả hai chuỗi đều qua i18n
- [ ] Vòng match score ẩn hoàn toàn khi không có `match_score`
- [ ] Lý do đề xuất dựng từ catalog i18n; mã lạ bị bỏ qua im lặng
- [ ] Focus mode là chuyển đổi layout, không phải modal/popup
- [ ] Đang focus vẫn đổi được khách sạn mà không đóng focus mode
- [ ] Đóng focus khôi phục chat + map + vị trí cuộn, không tải lại dữ liệu
- [ ] Card phòng chỉ đọc, không có nút "Chọn phòng"
- [ ] Không có khối review khách sạn, khối liên hệ, ô "Phòng đã chọn", ô chính sách phòng
- [ ] Không hiển thị "cách trung tâm"; chỗ đó là `area_name` thật
- [ ] Badge tình trạng phòng chỉ hiện khi có `price`; ánh xạ từ `sold_out`, không đoán
- [ ] Giá tổng chỉ hiện khi có đủ `start_date` + `end_date`; không có số đêm mặc định
- [ ] Danh sách lân cận có hai cột (tên · km), **không** có cột phút
- [ ] Km format từ `distance_km` theo locale; **không** render `distance_text` của DB
- [ ] `room.price = null` hiện "giá theo yêu cầu", không hiện 0, không mượn giá khách sạn
- [ ] Mọi ô ảnh có placeholder dự phòng khi lỗi
- [ ] Section vắng dữ liệu bị ẩn cả section, không có tiêu đề rỗng
- [ ] Toàn bộ render đẹp với backend **chưa** có Phase 2/3 (mọi field mới đều optional)
- [ ] `npm run typecheck`, `npm run lint`, `npm run check:tokens` pass
- [ ] `design-fidelity-checklist.md` §Phase 8 đã tick hết (HotelCard, HotelDetail, RoomCard);
      dòng bỏ tick có ghi lý do

## Đánh giá rủi ro

**Panel chi tiết render rỗng nếu dữ liệu seed thưa.** Báo cáo mức phủ field từ Phase 3 bước 7
là đầu vào bắt buộc cho phase này. Nếu `images`, `nearby_attractions`, `check_in_time` phần
lớn rỗng thì panel sẽ trông nghèo nàn — cần biết trước để thiết kế empty state, chứ không
phải phát hiện lúc demo.

**Focus mode giữ state là yêu cầu dễ vi phạm nhất.** Rất dễ vô tình unmount danh sách hoặc
reset cuộn khi transform. Bước 10 và tiêu chí "đóng focus khôi phục vị trí cuộn" phải được
test tay, không chỉ đọc code.

**Component ảnh dùng chung phải làm trước.** Nếu để sau, mỗi chỗ sẽ tự xử lý fallback theo
một kiểu khác nhau — đúng loại trùng lặp mà quy tắc dự án cấm.
