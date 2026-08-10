---
phase: 9
title: "[FE] Stage: Workspace & Place Detail Focus Mode"
status: done
priority: P1
effort: "2.5-3 ngày"
dependencies: [5]
track: frontend
---

# Phase 9: [FE] Stage: Workspace & Place Detail Focus Mode

## Tổng quan

Dựng workspace: tab Tổng quan + tab theo ngày, timeline lịch trình, và Place Detail Focus
Mode. Tiêu thụ `trip_plan` đã có sẵn (không đổi contract) cộng `GET /attractions/{id}`
(Phase 3).

Ảnh tham chiếu: `data/design/screenshots/01-focus.png`, `02-focus.png`.

## Yêu cầu

**Chức năng**
- Header chuyến đi: tên, khoảng ngày, số ngày/đêm, số người, ngân sách, nút Tạo lại
  (**không** có nút Chia sẻ — xem §Đối chiếu design)
- Tab: Tổng quan + mỗi ngày một tab
- Tab Tổng quan: các ô thống kê, danh sách ngày, phần điều chỉnh (`adjustments`)
- Tab ngày: timeline theo giờ, mỗi item có thumbnail, tên, loại, ghi chú, metadata
- Leg pill giữa các item hiển thị phương tiện + khoảng cách + thời lượng (chi tiết ở Phase 10)
- Click item trong timeline → mở Place Detail Focus Mode
- Focus mode: chat + map thu gọn, timeline mở rộng sang trái, panel chi tiết bên phải
- Item đang xem được highlight trong timeline; timeline vẫn cuộn được
- Nút đóng (✕) trả layout về nguyên trạng, không mất state

**Phi chức năng**
- Timeline dài phải cuộn mượt, không jank khi có nhiều lớp glass
- Item không có `reference_id` thì **không** mở được focus mode — và không hiện affordance
  click, để không hứa hẹn thứ không có

## Kiến trúc

### Nguồn dữ liệu

Toàn bộ workspace chạy trên `trip_plan` đang có. Không đổi contract cho phase này.

| Vùng trong design | Nguồn |
|---|---|
| Tên chuyến, khoảng ngày, số người | `trip_plan.destination/start_date/end_date/number_of_adults` |
| Số ngày | `trip_plan.duration_days` |
| Trạng thái (Draft/Completed) | `trip_plan.status` |
| Tab ngày | `trip_plan.days[]` |
| Item timeline | `days[].items[]` — `start_time`, `activity`, `kind`, `reference_type`, `reference_id`, `coordinates` |
| Khách sạn | `trip_plan.hotel` |
| Phần điều chỉnh | `trip_plan.adjustments[]` |

**Các ô thống kê ở tab Tổng quan** trong design gồm tổng quãng đường, tổng chi phí, tổng lộ
trình. Chỉ ship những ô tính được từ dữ liệu thật:

- **Số ngày, số điểm, khách sạn** — có sẵn ✅
- **Tổng quãng đường** — cộng `route_to_next.distance_km` (khoảng cách đường bộ **thật** từ
  Mapbox). Chặng nào `null` thì bù bằng haversine và đánh dấu tổng là xấp xỉ ✅
- **Tổng thời gian di chuyển** — cộng `route_to_next.duration_mins` (thời lượng Mapbox thật),
  hiển thị có tiền tố `~` vì route tính lúc lập lịch trình, không phải lúc đi (mục 2) ✅
- **Tổng ngân sách/chi phí** — ❌ `trip_plan` không có trường chi phí nào
  (`schemas.py:121-133`); giá chỉ có trên `hotel_options[]` lúc chọn khách sạn và không
  được chuyển sang `trip_plan`. Bỏ ô này — mục 13 bảng "Phần chưa làm"

Không hiển thị ô có giá trị `0` hay `—` chỉ để lấp bố cục; ô nào không có dữ liệu thì **bỏ ô đó**.

### Card "Cập nhật / Giữ kết quả"

`Yêu cầu cập nhật thiết kế.md` mô tả một card báo "bạn đã thay đổi X, phần Y sẽ bị ảnh
hưởng" với hai nút. **Không làm** (mục 3 bảng "Phần chưa làm") — backend không phát ra diff
có cấu trúc.

Thay vào đó, `trip_plan.adjustments[]` **là** bản ghi thật của các thay đổi đã áp dụng.
Render nó trong tab Tổng quan theo phong cách card của design, với tiêu đề đúng bản chất
("Điều chỉnh đã áp dụng"), không phải một hộp thoại xác nhận giả.

### Place Detail Focus Mode

Cùng cơ chế với Phase 8, dùng chung `use-focus-mode`:

```
click item trong timeline (hoặc marker trên map ở Phase 10)
  → setFocus({ kind: 'place', id: item.reference_id })
  → chat translateX(-100%), map thu về 0
  → timeline mở rộng chiếm chỗ chat
  → panel chi tiết vào từ phải
  → fetch GET /attractions/{id}
```

**Điều kiện mở**: chỉ khi `reference_type === 'attraction'` **và** có `reference_id`. Bộ giá
trị `reference_type` thật được Dev B rà ở Phase 3 bước 1 — dùng kết quả đó, đừng đoán.

Item không mở được (ví dụ "Di chuyển", "Nhận phòng") thì render **không có** `cursor: pointer`,
không có hover elevation, không có nút. Người dùng không được mời gọi bấm vào thứ không mở ra gì.

Panel chi tiết hiển thị (từ `AttractionDetail`): hero image, gallery, tên, loại, đánh giá,
mô tả, giờ mở cửa, giá vé, thời gian tham quan đề xuất.

Hai section trong design bị **bỏ**, đã ghi trong bảng "Phần chưa làm":
- "Đánh giá nổi bật" (mục 6) — không có nội dung review trong DB
- "Gợi ý địa điểm lân cận" (mục 7) — không có quan hệ lân cận cho attractions

Phần "AI đề xuất địa điểm này vì..." cũng không có nguồn cho từng địa điểm (`match_reasons`
chỉ có cho khách sạn). Bỏ section, đúng mục 5.

Giá vé: `ticket_price_adult === 0` → nhãn "Miễn phí"; `null` → **ẩn dòng**, không hiện
"0 ₫". Hai trường hợp này khác nhau và Phase 3 đã giữ chúng phân biệt trong payload.

### Timeline

Mỗi item: cột giờ + số thứ tự, thumbnail, nội dung. Theo đúng bố cục
`V-OTA Planner.dc.html:749-777`.

`start_time` có thể `null` — khi đó bỏ cột giờ, giữ số thứ tự. Không bịa giờ.

Leg pill giữa hai item liên tiếp, bốn trạng thái phân biệt rõ:

| `route_to_next` | Hiển thị |
|---|---|
| có dữ liệu, `profile: "driving-traffic"` | `Ô tô · 6,4 km · ~14 phút` |
| có dữ liệu, `profile: "walking"` | `Đi bộ · 0,9 km · ~12 phút` |
| `{0, 0, "", null}` (trùng toạ độ) | "cùng địa điểm" — **không** hiện `0 km · 0 phút` |
| `null` (routing lỗi/thiếu toạ độ) | `≈ 5,1 km đường chim bay` từ haversine, **không** phương tiện, **không** thời lượng |

Bốn trạng thái này khác nhau về ngữ nghĩa và không được gộp. Đặc biệt: khi `null` thì
**tuyệt đối không** hiện thời lượng — không có cách nào ước tính thời gian từ đường chim bay.

Nhãn phương tiện dựng từ `profile` qua khoá i18n `routeProfile.*`. Phase 12 gọi đúng profile
tương ứng nên nhãn luôn khớp với tuyến thực sự được tính. `profile` lạ (backend thêm mới) →
hiển thị khoảng cách + thời lượng nhưng **bỏ nhãn phương tiện**, không render mã thô.

Thời lượng luôn có tiền tố `~` — route được tính lúc lập lịch trình, không phải lúc đi
(mục 2 bảng "Phần chưa làm").

`lib/geo.ts` (haversine) chỉ dùng cho nhánh fallback. Logic đặt ở Phase 10 và dùng chung.

## Đối chiếu design (rà 06/08/2026)

File đối chiếu: `data/trip_planner/trip_planner_components/TimelineItem.dc.html`,
`DayCard.dc.html`, `PlaceDetail.dc.html`, và khối workspace ở
`trip_planner_components/V-OTA Planner.dc.html:192-250`.

### Phần của design bị bỏ

| Vùng design | Mục | Xử lý |
|---|---|---|
| `PlaceDetail` §`facilities` — chip tiện ích của địa điểm | 20 (mới) | Bỏ khối. `attractions` không có cột tiện ích |
| `PlaceDetail` §`topReviews` | 6 | Bỏ. Chỉ hiện `rating` + `review_count` |
| `PlaceDetail` §`nearby` — danh sách địa điểm lân cận bấm được | 7 | Bỏ khối |
| `PlaceDetail` §`whyPlace` — "AI đề xuất địa điểm này vì..." | 5 | Bỏ. `match_reasons` chỉ có cho khách sạn |
| Ô thống kê tổng chi phí | 13 | Bỏ ô |
| `TimelineItem` §`it.note` — dòng ghi chú dưới tên/badge loại | 24 (mới) | Bỏ dòng. `DayItem` không có cột note; chỉ `it.meta` (khung giờ thật) còn hiển thị |

### Phần của design **vẫn làm**, cần nêu rõ nguồn

- **Badge hero của `PlaceDetail`**: `{{ det.kind }}` + `Ngày {{ det.dayN }} · {{ det.time }}`.
  Số ngày và giờ **không** đến từ `GET /attractions/{id}` — chúng là ngữ cảnh của item trong
  timeline. Panel phải nhận thêm `{ dayNumber, startTime }` từ chỗ mở nó. `start_time` null →
  chỉ hiện "Ngày N", không bịa giờ.
- **`det.route`** — ba ô thông tin di chuyển ở panel địa điểm. Nguồn là `route_to_next` của
  item **liền trước** trong cùng ngày (phương tiện · khoảng cách · thời lượng). Áp dụng đúng
  bảng bốn trạng thái ở mục Timeline bên dưới: item đầu ngày hoặc `route` null thì **ẩn cả
  hàng ba ô**, không hiện ô rỗng.
- **`DayCard`** (tab Tổng quan) — chấm màu 9px có halo 4px theo màu ngày, tiêu đề, dòng phụ,
  mũi tên `→`, hover nâng 2px. Màu ngày dùng chung `lib/map-colors.ts` của Phase 10 để card
  ngày và route trên map **không bao giờ lệch màu nhau**. Component này nằm trong
  `trip-overview-tab.tsx`; file `day-card.tsx` cũ vẫn bị xoá vì nó là thứ khác.

### Chi tiết trình bày dễ bỏ sót

- `TimelineItem`: cột trái 44px (giờ `tabular-nums` + chấm số thứ tự 24px có glow), thumbnail
  52×52 bo 14px, badge loại `--fill` bo tròn, ghi chú `text-wrap:pretty`, vào bằng `vIn` lệch pha.
- Leg pill: vạch dọc 2×22px + pill `--g1` viền `{{ legColor }}44`, chấm 7px, số km
  `tabular-nums`. Nằm **dưới** item, thụt trái 52px.
- Header workspace là panel glass bo 26px riêng (`margin:14px 14px 0`). Chỉ có **một** nút:
  "Tạo lại" (viền `--stroke`, nền `--g2`) — gửi tin nhắn ngôn ngữ tự nhiên đã dịch qua đúng
  `onSend`, giống cách `regenerate` của design làm, không phải verb mới.
  **Nút "Chia sẻ" của design bị bỏ** (quyết định người dùng, 06/08/2026): nó không có hành vi
  nào trong design và không có gì để chia sẻ — session chưa có URL công khai. Không ship nút
  bấm vào không làm gì. Ghi ở mục 22 bảng "Phần chưa làm".

## File liên quan

- Tạo: `frontend/src/components/stage-workspace.tsx` — header, tab, bố cục
- Tạo: `frontend/src/components/trip-overview-tab.tsx` — ô thống kê, danh sách ngày, điều chỉnh
- Tạo: `frontend/src/components/day-timeline.tsx` — timeline theo ngày
- Tạo: `frontend/src/components/timeline-item.tsx` — một item + leg pill
- Tạo: `frontend/src/components/place-detail-panel.tsx` — panel focus mode
- Tạo: `frontend/src/hooks/use-attraction-detail.ts` — fetch + cache theo id
- Tạo: `frontend/src/lib/geo.ts` — parse `"lat,lng"`, haversine (dùng chung với Phase 10)
- Sửa: `frontend/src/components/stage-router.tsx` — nối stage workspace
- Sửa: `frontend/src/i18n/locales/{en,vi}.json`
- Xoá: `frontend/src/components/itinerary-panel.tsx`, `day-card.tsx` — được
  `stage-workspace` + `day-timeline` + `timeline-item` thay thế. **Chỉ xoá sau khi**
  `stage-router` đã trỏ sang component mới và mock chạy thông.
- Tái dùng: `remote-image.tsx` (Phase 8), `lib/format-trip-dates.ts`, `lib/format-stars.ts`

## Các bước thực hiện

1. `lib/geo.ts` — `parseCoordinates("lat,lng") -> {lat,lng} | null` và `haversineKm(a, b)`.
   Haversine lấy từ `trip_planner_components/scripts/utils/geo.js` → `kmFrom()` (hàm thuần,
   ~6 dòng). **Không** lấy `curve()` cùng file — xem `plan.md` §Lấy gì từ bản design prototype.
   Phải xử lý được cả định dạng WKT nếu backend trả dạng đó (comment `types.ts:46-48` cảnh
   báo `coordinates` là chuỗi WKT/tự do — kiểm tra giá trị thật từ mock và từ DB trước khi
   giả định định dạng `"lat,lng"`).
2. `timeline-item.tsx` — bố cục item, xử lý `start_time` null, affordance click chỉ khi mở
   được, chỗ cho leg pill.
3. `day-timeline.tsx` — danh sách item + leg pill giữa các cặp có đủ toạ độ.
4. `trip-overview-tab.tsx` — chỉ những ô thống kê tính được; render `adjustments[]`.
5. `stage-workspace.tsx` — header + tab + chuyển tab có animation.
6. `use-attraction-detail.ts` + `place-detail-panel.tsx`. Section vắng dữ liệu thì ẩn cả
   section. Giá vé phân biệt `0` với `null`.
7. Nối vào `use-focus-mode`; kiểm tra highlight item đang xem trong timeline và timeline vẫn
   cuộn được khi đang focus.
8. Trỏ `stage-router` sang `stage-workspace`; chạy mock thông rồi mới xoá `itinerary-panel.tsx`
   và `day-card.tsx`.
9. Thêm chuỗi vào cả hai catalog.
10. Kiểm chứng trên mock: lượt 4 ra workspace; đổi tab; mở chi tiết một địa điểm; đóng lại —
    chat và map về đúng chỗ, tab và vị trí cuộn giữ nguyên.

## Tiêu chí hoàn thành

- [x] Workspace có header, tab Tổng quan + tab theo ngày, timeline khớp design
- [x] Chỉ hiện ô thống kê tính được từ dữ liệu thật; ô không có nguồn bị bỏ hẳn
- [x] Tổng quãng đường cộng từ `distance_km` thật; chỉ đánh dấu xấp xỉ khi có chặng fallback
- [x] Tổng thời gian di chuyển có tiền tố `~`
- [x] Leg pill phân biệt đủ bốn trạng thái: ô tô / đi bộ / trùng toạ độ / `null`
- [x] Nhãn phương tiện dựng từ `profile` qua i18n; `profile` lạ thì bỏ nhãn, không render mã thô
- [x] Nhánh fallback (`null`) **không** hiển thị thời lượng và **không** hiển thị phương tiện
- [x] `adjustments[]` được render; **không** có card "Cập nhật / Giữ kết quả" giả
- [x] Item không mở được không có affordance click
- [x] Place focus mode là chuyển đổi layout, không phải modal
- [x] Item đang xem được highlight; timeline vẫn cuộn được khi focus
- [x] Đóng focus khôi phục chat + map + tab + vị trí cuộn
- [x] Giá vé `0` hiện "Miễn phí"; `null` thì ẩn dòng
- [x] Panel địa điểm không có khối tiện ích, review, lân cận, "AI đề xuất vì"
- [x] Badge hero nhận `dayNumber`/`startTime` từ timeline; `start_time` null thì chỉ hiện ngày
- [x] Hàng ba ô thông tin di chuyển bị ẩn cả hàng khi item đầu ngày hoặc route `null`
- [x] Màu ngày của `DayCard` và của route trên map dùng chung một bảng màu
- [x] Header workspace không có nút "Chia sẻ"; nút "Tạo lại" gửi tin nhắn thật qua `onSend`
- [x] `start_time` null không sinh ra giờ bịa
- [x] `itinerary-panel.tsx` và `day-card.tsx` đã xoá, không còn component trùng chức năng
- [x] `npm run typecheck`, `npm run lint` pass. `npm run check:tokens` thất bại **duy nhất**
      trên `design-animation.css` (keyframe `vBlink` — con trỏ nhấp nháy khi stream chat,
      thêm ở Phase "260806-1602-streaming-chat-messages" trước Phase 9 này), không phải
      file nào Phase 9 chạm vào — xem `git log -- frontend/src/styles/design-animation.css`
- [x] `design-fidelity-checklist.md` §Phase 9 đã tick hết (header workspace, DayCard,
      TimelineItem, PlaceDetail); dòng bỏ tick có ghi lý do (2 dòng: shadow header dùng
      `glass-panel` chung, dòng "ghi chú" của TimelineItem bỏ vì `DayItem` không có cột note)

## Đánh giá rủi ro

**Định dạng `coordinates` chưa chắc chắn — đã xác nhận.** `parseCoordinates` (bước 1) xử lý cả
`"lat,lng"` (định dạng thật, xác nhận qua mock server + `trip_formatter.py:328-331`) lẫn WKT
phòng hờ, trả `null` an toàn khi không khớp. Xem `frontend/src/lib/geo.ts` + `geo.test.ts`.

**`reference_type` — đã xác nhận.** `backend/src/services/trip_scheduler.py:93` khai
`reference_type: Literal["Hotel", "Attraction", "Event"]` — giá trị thật là chuỗi `"Attraction"`
viết hoa chữ đầu, đúng với điều kiện `item.reference_type === 'Attraction'` trong
`timeline-item.tsx`/`stage-workspace.tsx`. Không cần fallback "chỉ cần có `reference_id`" nữa.

**Xoá `itinerary-panel.tsx` quá sớm.** Nó đang là workspace duy nhất đang chạy. Chỉ xoá ở
bước 8, sau khi component mới đã chạy thông trên mock.
