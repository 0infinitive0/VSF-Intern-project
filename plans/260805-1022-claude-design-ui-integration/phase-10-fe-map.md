---
phase: 10
title: "[FE] Leaflet Map & Route"
status: pending
priority: P2
effort: "2-2.5 ngày"
dependencies: [9]
track: frontend
---

# Phase 10: [FE] Leaflet Map & Route

## Tổng quan

Thay `MapPanel` placeholder bằng bản đồ Leaflet thật: marker, **route bám đường thật từ
OSRM**, đồng bộ hover hai chiều với timeline và danh sách khách sạn.

**Đã có sẵn một bản chạy được để port**: `backend/src/airflow/dashboard/templates/index.html`
là dashboard Airflow đang hoạt động, đã giải mã polyline OSRM và vẽ route nhiều màu theo
ngày trên Leaflet, kèm fallback đường thẳng. Phase này **port logic đó sang React**, không
phải phát minh lại. Đọc `index.html:769-1000` trước khi viết dòng code đầu tiên.

## Yêu cầu

**Chức năng**
- Bản đồ Leaflet với tile OSM, chrome dạng glass theo design
- Stage `hotels`: marker cho từng khách sạn; hover card ↔ hover marker; click marker → mở
  Hotel Detail Focus Mode
- Stage `workspace` tab Tổng quan: route toàn chuyến, mỗi ngày một màu, có legend
- Stage `workspace` tab ngày: chỉ route của ngày đang chọn
- Hover item timeline → highlight marker + đoạn route liên quan, giảm opacity các đoạn khác
- Click marker → cuộn tới card/item tương ứng
- Marker Start/End rõ ràng; khách sạn là điểm đầu và cuối mỗi ngày
- Animation khi route xuất hiện
- Chrome bản đồ (legend, nhãn, controls) được dịch

**Phi chức năng**
- Bản đồ thu gọn mượt khi vào focus mode, không remount
- Tile OSM tuân thủ chính sách sử dụng (có attribution)
- Bộ lọc tile theo theme sáng/tối như bản export làm

## Kiến trúc

### Dependency

Thêm `leaflet` + `@types/leaflet`. Bản export dùng Leaflet 1.9.4 qua CDN; ở đây cài qua npm
để đi qua bundler.

**Không** dùng `react-leaflet` — bản export điều khiển Leaflet trực tiếp qua ref, và thêm
một lớp wrapper React nữa sẽ làm phức tạp phần đồng bộ hover mà không mang lại gì. Một hook
`use-leaflet-map` quản lý vòng đời map là đủ, và khớp với quy ước hook hiện có của dự án.

### Toạ độ

`lib/geo.ts` (tạo ở Phase 9) là nơi duy nhất parse toạ độ. **Phải xử lý được mọi định dạng
backend thực sự trả về** — xem cảnh báo ở Phase 9 về việc `hotel.coordinates` có thể là WKT
còn item coordinates là `"lat,lng"`.

Toạ độ không parse được → **bỏ điểm đó khỏi map**, không đặt marker ở `(0,0)`. Một marker
giữa Đại Tây Dương tệ hơn là không có marker.

Nếu một ngày có ít hơn 2 điểm parse được thì không vẽ route cho ngày đó.

### Route — polyline thật, fallback đường thẳng

Mỗi chặng vẽ theo đúng thứ tự ưu tiên mà dashboard Airflow đã dùng
(`index.html:871-876, 896-919`):

```
1. có route_to_next.polyline  → decodePolyline() → đường bám thật
2. không có / giải mã ra < 2 điểm → đường thẳng [điểm A, điểm B]
```

Bước 2 **bắt buộc**, không phải tuỳ chọn: OSRM public demo có thể rate-limit hoặc timeout,
khi đó backend trả `null` và map vẫn phải vẽ được cái gì đó.

Cấu trúc mỗi ngày: `route_from_hotel` (chặng khách sạn → điểm đầu) → các `route_to_next`
giữa các item → `route_to_next` của item cuối (quay về khách sạn). Đúng cấu trúc mà
`recalculate_itinerary_routes` (`routing.py:120-145`) tạo ra.

**`route_from_hotel` gần như luôn `null`** sau round-trip DB (mục 15 bảng "Phần chưa làm" —
`ITEM_RPC_FIELDS` lọc nó ra trước khi persist). Chặng đầu mỗi ngày vì vậy thường là đường
thẳng. Đây là hành vi bình thường, không phải bug — đừng đi "sửa" nó ở frontend.

### Giải mã polyline

`polyline` là Google Encoded Polyline precision 1e5. **Port hàm `decodePolyline` từ
`index.html:769-795`** — nó ngắn (~25 dòng), đã chạy đúng trong production, và tránh được
việc thêm dependency chỉ để làm một việc.

Không cài `@mapbox/polyline` — YAGNI, và bản port đã có sẵn.

Animation xuất hiện dùng `stroke-dasharray` + keyframe `vDash` đã port ở Phase 1.

Bảng màu theo ngày: dùng token accent + các màu phụ trong design, đủ tương phản ở cả hai
theme. Tham khảo `routeColors` trong `index.html` để giữ nhất quán với dashboard.

### Legend — nói đúng sự thật

Legend liệt kê **màu theo ngày**. Về phương tiện:

- Khi chặng có route thật: một nhãn duy nhất "ô tô" — OSRM luôn được gọi với profile
  `/driving` hardcode (`routing.py:11`), nên đó chính xác là thứ đã được tính
- Khi chặng là fallback: không có nhãn phương tiện

Design có **ba** mức (ô tô / đi bộ / cáp treo). **Chỉ ship một** — hệ thống không hề biết
chặng nào nên đi bộ hay đi cáp treo. Mục 1 bảng "Phần chưa làm".

Chặng fallback nên vẽ khác chặng thật (ví dụ nét đứt thưa hơn) để người dùng phân biệt được
đâu là tuyến đường thật và đâu là đường nối ước lượng.

### Đồng bộ hover

Trạng thái hover dùng chung giữa timeline/danh sách và map. Một hook nhẹ:

```ts
// hooks/use-map-sync.ts
// { hoveredId, setHoveredId, focusOn(id) }
```

Timeline và map cùng đọc `hoveredId`. Tránh đặt state hover trong context toàn app — nó đổi
liên tục theo chuột và sẽ làm render lại quá rộng. Giữ ở cấp stage.

Click marker → `focusOn(id)` cuộn phần tử `[data-card="{id}"]` vào tầm nhìn, đúng cơ chế
`data-card` mà bản export dùng (`V-OTA Planner.dc.html:751`).

### Thu gọn khi focus

Map không unmount khi vào focus mode; nó bị thu về bề rộng 0 bằng transition flex. **Phải gọi
`map.invalidateSize()`** sau khi transition kết thúc, nếu không Leaflet sẽ render sai kích
thước khi mở lại. Đây là lỗi kinh điển của Leaflet trong layout động.

### Theme

Bản export lọc tile theo theme (`--tile`, `V-OTA Planner.dc.html:61`):
- sáng: `saturate(.55) brightness(1.06) contrast(.9)`
- tối: `saturate(.35) brightness(.72) contrast(1.04) invert(.92) hue-rotate(180deg)`

Port nguyên. Cách này cho dark map từ tile OSM thường mà không cần nhà cung cấp tile riêng.

## File liên quan

- Tạo: `frontend/src/components/map-view.tsx` — component map thật
- Tạo: `frontend/src/components/map-legend.tsx` — legend dạng glass
- Tạo: `frontend/src/hooks/use-leaflet-map.ts` — vòng đời map, invalidateSize
- Tạo: `frontend/src/hooks/use-map-sync.ts` — trạng thái hover/focus dùng chung
- Tạo: `frontend/src/lib/map-colors.ts` — bảng màu theo ngày
- Sửa: `frontend/src/lib/geo.ts` — bổ sung helper bounds/center
- Sửa: `frontend/src/components/stage-hotels.tsx` — nối map + hover khách sạn
- Sửa: `frontend/src/components/stage-workspace.tsx` — nối map + hover timeline
- Sửa: `frontend/src/components/timeline-item.tsx` — phát sự kiện hover, `data-card`
- Sửa: `frontend/src/components/hotel-option-card.tsx` — phát sự kiện hover, `data-card`
- Sửa: `frontend/src/styles.css` — bộ lọc tile theo theme, style marker
- Sửa: `frontend/package.json` — thêm `leaflet`, `@types/leaflet`
- Sửa: `frontend/src/i18n/locales/{en,vi}.json` — chuỗi map
- Xoá: `frontend/src/components/map-panel.tsx` — được `map-view.tsx` thay thế

## Các bước thực hiện

0. **Đọc `backend/src/airflow/dashboard/templates/index.html:769-1000` trước.** Đây là bản
   tham chiếu đang chạy: `decodePolyline`, dựng segment theo ngày, fallback đường thẳng,
   `routeColors`. Port, đừng phát minh lại.
1. Cài `leaflet` + `@types/leaflet`. Import CSS của Leaflet trong `styles.css`.
   **Không** cài thư viện giải mã polyline.
2. Kiểm tra định dạng `coordinates` thật (mock **và** DB) rồi hoàn thiện `parseCoordinates`.
   Đối chiếu với `parse_coordinates` phía backend (`routing.py:57-70`) — nó chỉ chấp nhận
   `"lat,lng"` hoặc tuple, nên nếu comment WKT ở `types.ts:46-48` đúng thì backend đã không
   route được cho khách sạn. Kết luận của Phase 1 bước 2 là nguồn sự thật ở đây.
   Viết một vài case kiểm tra, gồm cả input rác.
2b. Port `decodePolyline` sang `lib/polyline.ts` + case kiểm tra (chuỗi rỗng, chuỗi rác,
   chuỗi hợp lệ đã biết kết quả).
3. `use-leaflet-map.ts` — khởi tạo, dọn dẹp, `invalidateSize` sau transition (dùng
   `transitionend` hoặc `ResizeObserver`, không dùng `setTimeout` đoán mò).
4. `map-view.tsx` với tile OSM + attribution + bộ lọc theme.
5. `map-colors.ts` — màu theo ngày, kiểm tra tương phản ở cả hai theme.
6. Marker: khách sạn (biểu tượng riêng) và điểm tham quan (số thứ tự). Bỏ điểm không parse được.
7. Polyline theo ngày: ưu tiên `route_to_next.polyline` đã giải mã, fallback đường thẳng khi
   `null` hoặc giải mã ra < 2 điểm. Chèn khách sạn đầu/cuối. Chặng fallback vẽ khác chặng
   thật. Animation `vDash`.
8. `use-map-sync.ts` + gắn `data-card` và sự kiện hover vào timeline item và hotel card.
9. Highlight khi hover: marker phóng to, đoạn route liên quan giữ nguyên opacity, các đoạn
   khác giảm.
10. Click marker → cuộn tới card; click marker khách sạn → mở Hotel Detail Focus Mode.
11. `map-legend.tsx` — chỉ màu theo ngày. **Không** có nhãn phương tiện.
12. Thay `MapPanel` bằng `MapView` trong cả hai stage; chạy thông rồi xoá `map-panel.tsx`.
13. Thêm chuỗi map vào cả hai catalog.
14. Kiểm chứng: marker đúng vị trí trên bản đồ Đà Nẵng; đổi tab ngày đổi route; hover đồng bộ
    hai chiều; vào/ra focus mode rồi map vẫn render đúng kích thước.

## Tiêu chí hoàn thành

- [ ] Map Leaflet thật với tile OSM và attribution đầy đủ
- [ ] Marker vẽ từ `coordinates` thật; toạ độ hỏng bị bỏ, không có marker ở `(0,0)`
- [ ] Route vẽ từ `polyline` OSRM đã giải mã — **bám đường thật**, không phải đường thẳng
- [ ] Fallback đường thẳng hoạt động khi `route_to_next` là `null` hoặc polyline hỏng
- [ ] Chặng fallback vẽ khác chặng thật để phân biệt được bằng mắt
- [ ] `decodePolyline` port từ dashboard Airflow, có case kiểm tra; **không** thêm dependency
- [ ] Route theo ngày, mỗi ngày một màu; tab Tổng quan hiện toàn chuyến, tab ngày chỉ ngày đó
- [ ] Khách sạn là điểm đầu và cuối mỗi ngày khi có toạ độ
- [ ] Chặng đầu ngày là đường thẳng khi `route_from_hotel` là `null` — đúng hành vi, không "sửa"
- [ ] Hover đồng bộ hai chiều timeline ↔ map; các đoạn route khác giảm opacity
- [ ] Click marker cuộn tới card tương ứng
- [ ] Legend chỉ có **một** nhãn phương tiện ("ô tô"), không phải ba mức của design
- [ ] Map thu gọn/mở lại quanh focus mode mà vẫn đúng kích thước (`invalidateSize`)
- [ ] Bộ lọc tile hoạt động ở cả theme sáng và tối
- [ ] `map-panel.tsx` đã xoá
- [ ] `npm run typecheck` và `npm run lint` pass

## Đánh giá rủi ro

**Định dạng toạ độ là rủi ro số một của phase này.** Nếu `parseCoordinates` hiểu sai định
dạng, marker sẽ nằm sai chỗ **một cách âm thầm** — không có lỗi, chỉ là bản đồ sai. Giảm
thiểu: bước 2 kiểm tra giá trị thật từ cả hai nguồn, có case kiểm tra, và bước 14 xác minh
bằng mắt rằng marker rơi vào đúng Đà Nẵng.

**`invalidateSize` bị quên là lỗi Leaflet kinh điển.** Map thu về 0 rồi mở lại sẽ hiện tile
xám hoặc lệch. Phải gắn vào `transitionend`/`ResizeObserver`, không phải `setTimeout` với số
giây đoán mò.

**Cám dỗ thêm nhãn phương tiện cho "đủ giống design".** OSRM luôn chạy profile `/driving`,
nên chỉ có một phương tiện là thật. Thêm "đi bộ" cho chặng ngắn và "cáp treo" cho chặng lên
núi là suy đoán, không phải dữ liệu. Mục 1 bảng "Phần chưa làm"; tiêu chí hoàn thành nêu
tường minh là chỉ **một** nhãn.

**OSRM public demo server là điểm phụ thuộc ngoài không có SLA.** `router.project-osrm.org`
có thể rate-limit, chậm, hoặc chết. Backend đã xử lý đúng (timeout 5s, `lru_cache`, trả
`None`), nhưng hệ quả với frontend là: **tỉ lệ chặng có route thật có thể rất thấp** trong
môi trường dev. Đường fallback không phải nhánh hiếm — nó phải được test kỹ như nhánh chính.
Lấy số liệu thật từ báo cáo Phase 2 bước 11 trước khi đánh giá kết quả phase này.

**Hiệu năng khi hover.** `hoveredId` đổi theo từng chuyển động chuột. Giữ state ở cấp stage,
memo hoá marker, và cập nhật style Leaflet trực tiếp qua ref thay vì render lại cả cây React.
