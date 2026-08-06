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
Mapbox**, đồng bộ hover hai chiều với timeline và danh sách khách sạn.

**Đã có sẵn một bản chạy được để port**: `backend/src/airflow/dashboard/templates/index.html`
là dashboard Airflow đang hoạt động, đã giải mã polyline và vẽ route nhiều màu theo
ngày trên Leaflet, kèm fallback đường thẳng. Phase này **port logic đó sang React**, không
phải phát minh lại. Đọc `index.html:769-1000` trước khi viết dòng code đầu tiên.

## Yêu cầu

**Chức năng**
- Bản đồ Leaflet với tile Mapbox (`light-v11`/`dark-v11`), chrome dạng glass theo design
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
- Attribution Mapbox + OpenStreetMap hiển thị đầy đủ theo điều khoản sử dụng
- Đổi style tile theo theme, không dùng bộ lọc CSS giả dark mode

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

Bước 2 **bắt buộc**, không phải tuỳ chọn: routing API có thể lỗi, hết quota, hoặc backend
chưa cấu hình token — khi đó `route_to_next` là `null` và map vẫn phải vẽ được cái gì đó.

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

Legend liệt kê **màu theo ngày**, cộng phần chú giải phương tiện dựng từ các `profile`
**thực sự xuất hiện** trong lịch trình đang xem:

- `driving-traffic` → "ô tô" (nét liền)
- `walking` → "đi bộ" (nét đứt dày)
- chặng fallback (`null`) → "ước lượng" (nét đứt thưa, màu nhạt)

Chỉ render mục nào thật sự có trong dữ liệu — lịch trình toàn ô tô thì không hiện mục "đi bộ".

Design có **ba** mức: ô tô / đi bộ / **cáp treo**. Hai mức đầu là thật (Phase 12 gọi đúng
profile). **Cáp treo không ship** — Mapbox không có profile đó và DB không có dữ liệu nào
cho biết chặng nào đi cáp. Mục 1 bảng "Phần chưa làm".

Chặng fallback nên vẽ khác chặng thật (ví dụ nét đứt thưa hơn) để người dùng phân biệt được
đâu là tuyến đường thật và đâu là đường nối ước lượng.

### Thẻ chú thích trên map ở stage khách sạn

Design đặt một card glass ở góc trên trái map trong stage khách sạn
(`trip_planner_components/V-OTA Planner.dc.html:178-181`): nhãn uppercase số khách sạn +
một dòng gợi ý đổi theo trạng thái chọn. Nội dung thật của dòng đó là
"Chọn một khách sạn để xem khoảng cách tới các điểm nổi bật" khi chưa chọn, và
"*Tên khách sạn* — điểm xuất phát & kết thúc mỗi ngày" khi đã chọn — cả hai đều là câu mô tả
trạng thái thật, không phải dữ liệu bịa, nên ship được. Nối vào cùng state chọn khách sạn của
Phase 8 (xem quyết định một bước / hai bước ở phase đó).

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

### Tile — Mapbox raster, không phải OSM

Dùng **Mapbox raster tiles** nạp vào Leaflet, **không** chuyển sang Mapbox GL JS. Đổi mỗi
URL tile; toàn bộ phần còn lại của phase (marker, polyline, hover sync, `invalidateSize`)
giữ nguyên vì vẫn là Leaflet.

```
https://api.mapbox.com/styles/v1/mapbox/{style}/tiles/{z}/{x}/{y}?access_token={token}
   style sáng: light-v11        style tối: dark-v11
```

Đổi style theo `data-theme` → **bỏ được hack CSS** `invert(.92) hue-rotate(180deg)` mà bản
export dùng để giả dark mode (`V-OTA Planner.dc.html:61`). Dark map thật đẹp hơn hẳn và đúng
tinh thần Apple HIG của design.

**Token tile là token THỨ HAI**, khác token server của Phase 12:

| | Phase 12 (Directions) | Phase 10 (tile) |
|---|---|---|
| Loại | secret | public |
| Nơi dùng | backend | trình duyệt |
| Restriction | không | **bắt buộc có URL restriction** |
| Scope | directions | chỉ `styles:tiles`, `styles:read` |

Token tile **lộ ra trong bundle trình duyệt** — đó là bình thường và không tránh được, nên
URL restriction là biện pháp bảo vệ duy nhất. Đặt qua `VITE_MAPBOX_TOKEN` (tiền tố `VITE_`
nên nó cố ý đi vào bundle). **Tuyệt đối không** dùng token server ở đây.

Attribution của Mapbox và OpenStreetMap là **bắt buộc** theo điều khoản sử dụng — giữ
control attribution của Leaflet, đừng ẩn đi.

Nếu thiếu `VITE_MAPBOX_TOKEN`: fallback về tile OSM + bộ lọc CSS cũ, và log cảnh báo. Map
vẫn chạy được cho dev chưa cấu hình token.

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
4. `map-view.tsx` với **Mapbox raster tiles** (`light-v11` / `dark-v11` theo `data-theme`),
   attribution Mapbox + OSM, token từ `VITE_MAPBOX_TOKEN`. Fallback tile OSM + bộ lọc CSS
   khi thiếu token. **Không** dùng token server của Phase 12 ở đây.
5. `map-colors.ts` — lấy thẳng `DAY_COLORS` + `LEG_COLORS` từ
   `trip_planner_components/scripts/constants/config.js` (đây là bảng màu chuẩn của design);
   kiểm tra tương phản ở cả hai theme. Phase 9 `DayCard` **dùng chung đúng file này**.
   **Không** dùng `geo.js:curve()` cho bất kỳ chặng nào — nó bẻ cong đường thẳng thành cung
   để trông giống tuyến đường thật, biến fallback thành lời nói dối bằng đồ hoạ. Xem
   `plan.md` §Lấy gì từ bản design prototype.
6. Marker: khách sạn (biểu tượng riêng) và điểm tham quan (số thứ tự). Bỏ điểm không parse được.
7. Polyline theo ngày: ưu tiên `route_to_next.polyline` đã giải mã, fallback đường thẳng khi
   `null` hoặc giải mã ra < 2 điểm. Chèn khách sạn đầu/cuối. Chặng fallback vẽ khác chặng
   thật. Animation `vDash`.
8. `use-map-sync.ts` + gắn `data-card` và sự kiện hover vào timeline item và hotel card.
9. Highlight khi hover: marker phóng to, đoạn route liên quan giữ nguyên opacity, các đoạn
   khác giảm.
10. Click marker → cuộn tới card; click marker khách sạn → mở Hotel Detail Focus Mode.
11. `map-legend.tsx` — màu theo ngày + chú giải phương tiện dựng từ các `profile` thật sự
    xuất hiện trong dữ liệu. **Không** có mục cáp treo.
12. Thay `MapPanel` bằng `MapView` trong cả hai stage; chạy thông rồi xoá `map-panel.tsx`.
13. Thêm chuỗi map vào cả hai catalog.
14. Kiểm chứng: marker đúng vị trí trên bản đồ Đà Nẵng; đổi tab ngày đổi route; hover đồng bộ
    hai chiều; vào/ra focus mode rồi map vẫn render đúng kích thước.

## Tiêu chí hoàn thành

- [ ] Map Leaflet thật với tile Mapbox raster và attribution Mapbox + OSM đầy đủ
- [ ] Marker vẽ từ `coordinates` thật; toạ độ hỏng bị bỏ, không có marker ở `(0,0)`
- [ ] Route vẽ từ `polyline` Mapbox đã giải mã — **bám đường thật**, không phải đường thẳng
- [ ] Fallback đường thẳng hoạt động khi `route_to_next` là `null` hoặc polyline hỏng
- [ ] Chặng fallback vẽ khác chặng thật để phân biệt được bằng mắt
- [ ] Chặng fallback là **đường thẳng**, không bị bẻ cong thành cung (`curve()` không được dùng)
- [ ] `decodePolyline` port từ dashboard Airflow, có case kiểm tra; **không** thêm dependency
- [ ] Route theo ngày, mỗi ngày một màu; tab Tổng quan hiện toàn chuyến, tab ngày chỉ ngày đó
- [ ] Khách sạn là điểm đầu và cuối mỗi ngày khi có toạ độ
- [ ] Chặng đầu ngày là đường thẳng khi `route_from_hotel` là `null` — đúng hành vi, không "sửa"
- [ ] Hover đồng bộ hai chiều timeline ↔ map; các đoạn route khác giảm opacity
- [ ] Click marker cuộn tới card tương ứng
- [ ] Legend có ô tô và đi bộ khi dữ liệu thật sự có profile đó, cộng mục "ước lượng" cho
      chặng fallback; **không** có mục cáp treo
- [ ] Map thu gọn/mở lại quanh focus mode mà vẫn đúng kích thước (`invalidateSize`)
- [ ] Tile Mapbox đổi style theo theme (`light-v11` / `dark-v11`); **không** còn hack CSS `invert()`
- [ ] Thiếu `VITE_MAPBOX_TOKEN` → fallback tile OSM, map vẫn chạy
- [ ] Token tile là public + có URL restriction; **không** phải token server của Phase 12
- [ ] Attribution Mapbox + OSM hiển thị, không bị ẩn
- [ ] Legend chỉ hiện phương tiện thật sự có trong dữ liệu; không có mục cáp treo
- [ ] `map-panel.tsx` đã xoá
- [ ] `npm run typecheck`, `npm run lint`, `npm run check:tokens` pass
- [ ] `design-fidelity-checklist.md` §Phase 10 đã tick hết (khung map, thẻ chú thích, tile
      theo theme); dòng bỏ tick có ghi lý do

## Đánh giá rủi ro

**Định dạng toạ độ là rủi ro số một của phase này.** Nếu `parseCoordinates` hiểu sai định
dạng, marker sẽ nằm sai chỗ **một cách âm thầm** — không có lỗi, chỉ là bản đồ sai. Giảm
thiểu: bước 2 kiểm tra giá trị thật từ cả hai nguồn, có case kiểm tra, và bước 14 xác minh
bằng mắt rằng marker rơi vào đúng Đà Nẵng.

**`invalidateSize` bị quên là lỗi Leaflet kinh điển.** Map thu về 0 rồi mở lại sẽ hiện tile
xám hoặc lệch. Phải gắn vào `transitionend`/`ResizeObserver`, không phải `setTimeout` với số
giây đoán mò.

**Token tile lộ trong bundle.** Không tránh được với tile phía trình duyệt. URL restriction
là biện pháp bảo vệ duy nhất và **bắt buộc** phải bật trước khi deploy — nếu không, token bị
lấy đi dùng và tính tiền vào tài khoản. Đây cũng là lý do nó phải khác token server Phase 12:
token server bị lộ thì mất nhiều hơn nhiều.

**Cám dỗ thêm nhãn cáp treo cho "đủ giống design".** Ô tô và đi bộ là thật vì Phase 12 gọi
đúng profile tương ứng. Cáp treo thì không có profile, không có dữ liệu — thêm vào là suy
đoán. Mục 1 bảng "Phần chưa làm"; tiêu chí hoàn thành nêu tường minh.

**Route có thể vắng trong môi trường dev.** Nếu backend chưa cấu hình `MAPBOX_ACCESS_TOKEN`
thì mọi `route_to_next` là `null` và toàn bộ map chạy nhánh fallback đường thẳng. Đường
fallback không phải nhánh hiếm — phải test kỹ như nhánh chính. Lấy số liệu thật (tỉ lệ chặng
có route + phân bố profile) từ báo cáo Phase 12 bước 8 trước khi đánh giá kết quả phase này.

**Hiệu năng khi hover.** `hoveredId` đổi theo từng chuyển động chuột. Giữ state ở cấp stage,
memo hoá marker, và cập nhật style Leaflet trực tiếp qua ref thay vì render lại cả cây React.
